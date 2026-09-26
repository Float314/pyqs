"""Turn XML/LaTeX question banks into :mod:`pyqs.models` objects.

The parser is deliberately forgiving about *vocabulary* (a question type may be
written ``mcq``, ``MCQ`` or ``multiple_choice``) and strict about *structure*
(no questions found is an error, not an empty result).

Supported shape::

    <pyqs year="2024" subject="Mathematics">
      <question_body id="Q1" type="mcq" marks="1" topic="Calculus">
        <question>...</question>
        <option name="A">...</option>
        <answer>B</answer>
      </question_body>
    </pyqs>

Namespaces are ignored, and a file may hold several ``<paper>`` sections, each
becoming its own :class:`~pyqs.models.Paper`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from pyqs.errors import InputError, ParseError, SchemaError
from pyqs.models import Option, Paper, Part, Question, clean_text

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

QUESTION_TAGS = frozenset(
    {"question_body", "questionbody", "question", "pyq", "item", "question_item", "q"}
)
PAPER_TAGS = frozenset(
    {
        "pyqs",
        "pyq",
        "paper",
        "papers",
        "question_paper",
        "questionpaper",
        "bank",
        "question_bank",
        "questionbank",
        "exam",
        "section",
        "paper_section",
    }
)
QUESTION_TEXT_TAGS = frozenset(
    {"question", "question_text", "questiontext", "stem", "text", "body", "content"}
)
OPTION_TAGS = frozenset({"option", "choice"})
OPTION_CONTAINER_TAGS = frozenset({"options", "option_list", "choices"})
ANSWER_TAGS = frozenset(
    {"answer", "answer_text", "answertext", "solution", "key", "correct_answer"}
)
ASSERTION_TAGS = frozenset({"assertion", "statement"})
REASON_TAGS = frozenset({"reason", "explanation"})
PARTS_CONTAINER_TAGS = frozenset(
    {"parts", "part_list", "subparts", "sub_parts", "subquestions", "sub_questions"}
)
PART_TAGS = frozenset({"part", "subpart", "sub_part", "subquestion", "sub_question"})
TOPIC_TAGS = frozenset({"topic", "chapter", "unit", "module", "area", "section", "subject_area"})
CONCEPT_TAGS = frozenset({"concept", "concepts", "tag", "tags", "keyword", "keywords", "syllabus"})
METADATA_TAGS = TOPIC_TAGS | CONCEPT_TAGS

ATTR_ID = ("id", "qid", "q_id", "number", "no", "index", "qno", "q_no")
ATTR_TYPE = ("type", "question_type", "questiontype", "category", "kind", "qtype")
ATTR_MARKS = ("marks", "mark", "points", "score", "weight", "credit")
ATTR_TOPIC = ("topic", "chapter", "unit", "area", "module")
ATTR_YEAR = ("year", "yr", "session", "session_year")
ATTR_LABEL = ("name", "label", "id", "value")

TYPE_ALIASES = {
    "mcq": "mcq",
    "mcq1": "mcq",
    "mcq_single": "mcq",
    "single_choice": "mcq",
    "single_correct": "mcq",
    "single_mcq": "mcq",
    "multiple_choice_single": "mcq",
    "multiple_choice": "mcq",
    "single_option": "mcq",
    "mcq_multiple": "mcq_multiple",
    "multiple_mcq": "mcq_multiple",
    "multiple_correct": "mcq_multiple",
    "multiple_choice_multiple": "mcq_multiple",
    "mcc": "mcq_multiple",
    "assertion_reason": "assertion_reason",
    "assertionreason": "assertion_reason",
    "assertion-reason": "assertion_reason",
    "ar": "assertion_reason",
    "statement_reason": "assertion_reason",
    "numerical": "numerical",
    "numerical_answer": "numerical",
    "numeric": "numerical",
    "nat": "numerical",
    "integer": "numerical",
    "integer_type": "numerical",
    "decimal": "numerical",
    "short_answer": "short_answer",
    "shortanswer": "short_answer",
    "short": "short_answer",
    "sa": "short_answer",
    "2_mark": "short_answer",
    "long_answer": "long_answer",
    "longanswer": "long_answer",
    "long": "long_answer",
    "subjective": "long_answer",
    "essay": "long_answer",
    "subjective_long": "long_answer",
    "4_mark": "long_answer",
    "matching": "matching",
    "match": "matching",
    "list_match": "matching",
    "matrix_match": "matching",
    "comprehension": "matching",
    "case_based": "case_based",
    "casebased": "case_based",
    "case_study": "case_based",
    "case_study_based": "case_based",
    "paragraph": "case_based",
    "true_false": "true_false",
    "tf": "true_false",
    "unknown": "unknown",
}

TYPE_ORDER = (
    "mcq",
    "mcq_multiple",
    "assertion_reason",
    "numerical",
    "short_answer",
    "long_answer",
    "case_based",
    "matching",
    "true_false",
    "unknown",
)

TYPE_LABELS = {
    "mcq": "MCQ",
    "mcq_multiple": "MCQ (multi)",
    "assertion_reason": "Assertion-Reason",
    "numerical": "Numerical",
    "short_answer": "Short Answer",
    "long_answer": "Long Answer",
    "case_based": "Case Based",
    "matching": "Matching",
    "true_false": "True/False",
    "unknown": "Unclassified",
}

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PART_LETTERS = "abcdefghijklmnopqrstuvwxyz"

_MARKS_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(?:marks?|m|pts?|points?)?\s*$", re.IGNORECASE)
_YEAR_IN_NAME = re.compile(r"(19|20)\d{2}")
_SPLIT_RE = re.compile(r"\s*[,;]\s*")
_WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_TOPIC = "Unclassified"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def local_name(tag: str) -> str:
    """Strip an XML namespace from ``tag`` and lower-case the result."""

    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    return tag.lower()


def attr(element: ET.Element, names: Sequence[str]) -> str | None:
    """Return the first present attribute from ``names`` (namespace agnostic)."""

    wanted = {name.lower() for name in names}
    for key, value in element.attrib.items():
        if local_name(key) in wanted:
            return value
    return None


def normalise_type(raw: str | None) -> str:
    """Map a free-form type string onto the canonical vocabulary."""

    if not raw:
        return "unknown"
    key = _SPLIT_RE.sub(" ", raw.strip()).casefold()
    key = re.sub(r"\([^)]*\)", " ", key)  # drop "(single)", "(multiple)", ...
    key = re.sub(r"[\s\-]+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_")
    if not key:
        return "unknown"
    if key in TYPE_ALIASES:
        return TYPE_ALIASES[key]
    collapsed = key.replace("_", "")
    if collapsed in TYPE_ALIASES:
        return TYPE_ALIASES[collapsed]
    return key


def parse_marks(raw: str | None) -> tuple[float | None, str | None]:
    """Parse a marks attribute.

    Returns ``(value, warning)``. Accepts ``2``, ``2.0`` and ``2 marks``; anything
    else produces a warning instead of a silent guess.
    """

    if raw is None:
        return None, None
    text = raw.strip()
    if not text:
        return None, None
    match = _MARKS_RE.match(text)
    if match:
        return float(match.group(1)), None
    return None, f"could not read marks {raw!r}"


def infer_year(path: str | None) -> int | None:
    """Pull a four digit year out of a file name, e.g. ``jee_main_2024.xml``."""

    if not path:
        return None
    match = _YEAR_IN_NAME.search(Path(path).name)
    return int(match.group(0)) if match else None


def parse_year(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.search(r"(19|20)\d{2}", raw)
    return int(match.group(0)) if match else None


def parse_bool(raw: str | None, default: bool = True) -> bool:
    if raw is None:
        return default
    return raw.strip().casefold() not in {"false", "0", "no", "off", "none", ""}


def format_type_name(value: str) -> str:
    """Human label for a canonical type key."""

    return TYPE_LABELS.get(value, value.replace("_", " ").title())


def type_sort_key(value: str) -> tuple[int, str]:
    try:
        return (TYPE_ORDER.index(value), value)
    except ValueError:
        return (len(TYPE_ORDER), value)


def _text_of(element: ET.Element) -> str:
    return clean_text("".join(element.itertext()))


def _split_values(raw: str) -> list[str]:
    return [part.strip() for part in _SPLIT_RE.split(raw) if part.strip()]


def _part_letter(index: int) -> str:
    if index < len(PART_LETTERS):
        return PART_LETTERS[index]
    return f"p{index + 1}"


def _option_letter(index: int) -> str:
    if index < len(LETTERS):
        return LETTERS[index]
    return str(index + 1)


# --------------------------------------------------------------------------- #
# Question construction
# --------------------------------------------------------------------------- #


def _is_question_element(element: ET.Element) -> bool:
    """True when ``element`` describes a question rather than a question stem.

    ``<question>`` is ambiguous: it is both a common stem tag and a plausible
    container name. It only counts as a question when it carries question
    metadata (``type``/``marks``).
    """

    tag = local_name(element.tag)
    if tag not in QUESTION_TAGS:
        return False
    if tag in {"question", "q"}:
        return attr(element, ATTR_TYPE) is not None or attr(element, ATTR_MARKS) is not None
    return True


def _first_child_text(element: ET.Element, tags: frozenset) -> str | None:
    for child in element:
        if local_name(child.tag) in tags:
            return _text_of(child)
    return None


def _option_elements(element: ET.Element) -> Iterator[ET.Element]:
    """Yield option elements, descending through ``<options>`` style wrappers."""

    for child in element:
        tag = local_name(child.tag)
        if tag in OPTION_TAGS:
            yield child
        elif tag in OPTION_CONTAINER_TAGS:
            for grandchild in child:
                if local_name(grandchild.tag) in OPTION_TAGS:
                    yield grandchild


def _collect_options(element: ET.Element) -> list[Option]:
    options: list[Option] = []
    for child in _option_elements(element):
        index = len(options)
        raw_label = attr(child, ATTR_LABEL)
        if raw_label:
            candidate = _WHITESPACE_RE.sub("", raw_label)
            label = candidate if candidate and len(candidate) <= 3 else _option_letter(index)
        else:
            label = _option_letter(index)
        options.append(Option(label=label, text=_text_of(child)))
    return options


def _collect_concepts(element: ET.Element) -> list[str]:
    concepts: list[str] = []
    for child in element:
        if local_name(child.tag) not in CONCEPT_TAGS:
            continue
        nested = [node for node in child if isinstance(node.tag, str)]
        if nested:
            for node in nested:
                value = _text_of(node)
                if value:
                    concepts.extend(_split_values(value))
        else:
            concepts.extend(_split_values(_text_of(child)))
    return concepts


def _collect_parts(element: ET.Element, warnings: list[str], hint: str) -> list[Part]:
    parts: list[Part] = []
    counter = {"index": 0}

    def build(node: ET.Element, depth: int) -> Part:
        position = counter["index"]
        counter["index"] += 1
        raw_id = attr(node, ATTR_ID)
        part_id = raw_id.strip() if raw_id and raw_id.strip() else _part_letter(position)
        marks, warning = parse_marks(attr(node, ATTR_MARKS))
        if warning:
            warnings.append(f"{hint} part {part_id}: {warning}")

        # The part's own text plus the text of any non-part child; the tail of a
        # sub-part belongs to this part, the sub-part's text to the sub-part.
        pieces = [node.text or ""]
        subparts: list[Part] = []
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if local_name(child.tag) in PART_TAGS:
                subparts.append(build(child, depth + 1))
            elif local_name(child.tag) not in METADATA_TAGS:
                pieces.append(_text_of(child))
            if child.tail:
                pieces.append(child.tail)
        return Part(
            id=part_id,
            text=clean_text(" ".join(piece for piece in pieces if piece.strip())),
            marks=marks,
            subparts=tuple(subparts),
        )

    containers = [
        child for child in element if local_name(child.tag) in PARTS_CONTAINER_TAGS
    ]
    for container in containers:
        for child in container:
            if local_name(child.tag) in PART_TAGS:
                parts.append(build(child, 0))

    if not parts:
        for child in element:
            if local_name(child.tag) in PART_TAGS:
                parts.append(build(child, 0))
    return parts


def _collect_topic(element: ET.Element) -> str | None:
    raw = attr(element, ATTR_TOPIC)
    if raw and raw.strip():
        return raw.strip()
    child_topic = _first_child_text(element, TOPIC_TAGS)
    if child_topic:
        return child_topic
    return None


def build_question(element: ET.Element, index: int, warnings: list[str], source: str) -> Question:
    """Build a :class:`~pyqs.models.Question` from a question-shaped element."""

    raw_id = attr(element, ATTR_ID)
    question_id = raw_id.strip() if raw_id and raw_id.strip() else f"Q{index + 1}"
    if not raw_id or not raw_id.strip():
        warnings.append(f"{source} #{index + 1}: question without an id, generated {question_id!r}")

    marks, marks_warning = parse_marks(attr(element, ATTR_MARKS))
    if marks_warning:
        warnings.append(f"{source} {question_id}: {marks_warning}")

    text = _first_child_text(element, QUESTION_TEXT_TAGS)
    if not text and local_name(element.tag) in QUESTION_TEXT_TAGS:
        text = _text_of(element)

    assertion = _first_child_text(element, ASSERTION_TAGS)
    reason = _first_child_text(element, REASON_TAGS)
    question_type = normalise_type(attr(element, ATTR_TYPE))
    if not text:
        text = clean_text(" ".join(chunk for chunk in (assertion, reason) if chunk))
        if text and question_type != "assertion_reason":
            warnings.append(
                f"{source} {question_id}: no <question> element, used assertion/reason as the stem"
            )

    if attr(element, ATTR_TYPE) is None:
        warnings.append(f"{source} {question_id}: no type attribute, classified as 'unknown'")

    options = _collect_options(element)
    answer = _first_child_text(element, ANSWER_TAGS)
    parts = _collect_parts(element, warnings, f"{source} {question_id}")
    if not options and not answer and not parts:
        warnings.append(f"{source} {question_id}: no options, answer or parts recorded")

    known = {name.lower() for name in ATTR_ID + ATTR_TYPE + ATTR_MARKS + ATTR_TOPIC}
    extra: dict[str, str] = {
        local_name(key): value
        for key, value in element.attrib.items()
        if local_name(key) not in known
    }

    return Question(
        id=question_id,
        type=question_type,
        marks=marks,
        text=text or "",
        topic=_collect_topic(element),
        options=options,
        answer=answer,
        assertion=assertion,
        reason=reason,
        parts=parts,
        concepts=_collect_concepts(element),
        source=source,
        extra=extra,
    )


# --------------------------------------------------------------------------- #
# Paper construction
# --------------------------------------------------------------------------- #


def _inherited(element: ET.Element, names: Sequence[str], parent: Paper | None) -> str | None:
    value = attr(element, names)
    if value and value.strip():
        return value.strip()
    if parent is None:
        return None
    return getattr(parent, _ATTR_TO_FIELD[names[0]], None)


_ATTR_TO_FIELD = {
    "exam": "exam",
    "subject": "subject",
    "board": "board",
    "title": "title",
}


def _paper_from_element(element: ET.Element, source: str, parent: Paper | None) -> Paper:
    year = parse_year(attr(element, ATTR_YEAR))
    if year is None and parent is not None:
        year = parent.year
    if year is None:
        year = infer_year(source)
    return Paper(
        path=source,
        exam=_inherited(element, ("exam", "examination", "test", "competition"), parent),
        year=year,
        subject=_inherited(element, ("subject", "discipline", "paper_subject"), parent),
        board=_inherited(element, ("board", "council", "institution", "university"), parent),
        title=_inherited(element, ("title", "name", "paper_name"), parent),
        latex=parse_bool(attr(element, ("latex", "math", "use_latex")), default=True),
        schema_version=attr(element, ("version", "schema_version", "schema")),
    )


def _question_elements(root: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and _is_question_element(element)
    ]


def parse_paper_string(text: str, source: str = "<string>") -> list[Paper]:
    """Parse an XML document held in memory into one or more papers."""

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ParseError(_clean_parse_error(str(exc)), source) from exc

    base = _paper_from_element(root, source, None)
    warnings: list[str] = []

    sections = [
        child
        for child in root
        if isinstance(child.tag, str)
        and local_name(child.tag) in PAPER_TAGS
        and not _is_question_element(child)
    ]
    if sections:
        papers: list[Paper] = []
        for section in sections:
            elements = _question_elements(section)
            if not elements:
                continue
            paper = _paper_from_element(section, source, base)
            paper.extend(
                build_question(element, index, warnings, source)
                for index, element in enumerate(elements)
            )
            paper.warnings.extend(warnings)
            papers.append(paper)
    else:
        elements = _question_elements(root)
        if not elements:
            raise SchemaError("no question elements found", source)
        base.extend(
            build_question(element, index, warnings, source)
            for index, element in enumerate(elements)
        )
        base.warnings.extend(warnings)
        papers = [base]

    if not papers:
        raise SchemaError("no question elements found", source)
    return papers


def _clean_parse_error(message: str) -> str:
    return _WHITESPACE_RE.sub(" ", message).strip()


def parse_paper(path: Path) -> list[Paper]:
    """Parse a single XML file into one or more papers."""

    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InputError(f"no such file: {source}") from exc
    except IsADirectoryError as exc:
        raise InputError(f"expected a file but found a directory: {source}") from exc
    except UnicodeDecodeError as exc:
        raise ParseError(f"file is not valid UTF-8 ({exc.reason})", source) from exc
    except OSError as exc:
        raise InputError(f"could not read {source}: {exc.strerror or exc}") from exc
    return parse_paper_string(text, source)


def load_paper(path: Path) -> Paper:
    """Parse a file that is expected to hold exactly one paper."""

    papers = parse_paper(path)
    if len(papers) > 1:
        raise SchemaError(
            f"expected a single paper but found {len(papers)} sections in this file", str(path)
        )
    return papers[0]


def load_papers(paths: Iterable[Path]) -> list[Paper]:
    """Parse several files, preserving input order."""

    papers: list[Paper] = []
    for path in paths:
        papers.extend(parse_paper(path))
    return papers
