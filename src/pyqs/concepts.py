"""Concept extraction: how often does a concept appear across papers?

Three complementary sources are combined, each tagged so reports can show *why*
a concept was counted, and listed here in decreasing order of trust:

``tag``
    Concepts declared in the XML (``<concept>``, ``<tags>``, ``<keywords>``).
``latex``
    LaTeX commands that imply a subject area (``\\int`` implies Integration).
    Checked before keywords because ``\\lim`` would otherwise be read as the
    English word fragment "lim".
``keyword``
    A curated English lexicon matched against the question prose.

Concept names are normalised so ``"Case-based"``, ``"case based"`` and
``"Case Based"`` all collapse into a single bucket.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pyqs.models import Question

SOURCES = ("tag", "latex", "keyword")

_SOURCE_RANK = {name: index for index, name in enumerate(SOURCES)}

_NORMALISE_STRIP = re.compile(r"^[\s\"'`(\[{<*_#-]+|[\s\"'`)\]}>*_#.,;:!?-]+$")
_NORMALISE_SPACE = re.compile(r"[\s_-]+")
_LATEX_TOKEN = re.compile(r"\\([a-zA-Z]+)")
_LATEX_MATH_DELIMS = re.compile(r"\$\$?|\\\[|\\\]|\\\(|\\\)")


def normalise_concept(name: str) -> str:
    """Normalise a concept name for grouping."""

    text = _LATEX_MATH_DELIMS.sub(" ", name or "")
    text = text.replace("\u00a0", " ")
    text = _NORMALISE_STRIP.sub("", text)
    text = _NORMALISE_SPACE.sub(" ", text)
    return text.strip()


def _key(name: str) -> str:
    return name.casefold()


# --------------------------------------------------------------------------- #
# Lexicons
# --------------------------------------------------------------------------- #

# (regex, canonical concept). Order matters: the first match wins.
KEYWORD_LEXICON: tuple[tuple[str, str], ...] = (
    (r"\bdifferentiat\w*|\bderivativ\w*|\bdy/dx\b|\bf\s*'\s*\(|\bslope\b", "Differentiation"),
    (r"\bintegrat\w*|\bantiderivativ\w*|\barea under\b", "Integration"),
    (r"\blimit\w*|\bcontinuit\w*|\bl['\u2019]?hopital\b", "Limits & Continuity"),
    (
        r"\btrigonometr\w*|\btrig\b|\bsin\b|\bcos\b|\btan\b|\bsine\b|\bcosine\b|\bsec\b|\bcot\b",
        "Trigonometry",
    ),
    (r"\bmatrix\b|\bmatrices\b|\bdeterminant\w*|\bdeterminat\b", "Matrices & Determinants"),
    (r"\bvector\w*|\bscalar\b|\bcollinear\b|\bunit vector\b", "Vectors"),
    (
        r"\barithmetic (?:mean|progression)\b|\bgeometric (?:mean|progression)\b"
        r"|\bsequence\w*|\bseries\b|\bsummation\b|\bsigma\b",
        "Sequences & Series",
    ),
    (
        r"\bbinomial\b|\bcombination\w*|\bpermutation\w*|\barrangement\w*|\bfactorial\b|\bp\(\s*n",
        "Permutations & Combinations",
    ),
    (
        r"\bprobability\b|\brandom\b|\bbayes\b|\bconditional probability\b|\bsample space\b",
        "Probability",
    ),
    (
        r"\bstandard deviation\b|\bmedian\b|\bmean\b|\bstatistics\b|\bhistogram\b"
        r"|\bvariance\b|\bmode\b",
        "Statistics",
    ),
    (r"\bcomplex (?:number|plane|root)\w*|\bimaginary\b|\bargand\b", "Complex Numbers"),
    (r"\bquadratic\b|\broots of (?:the )?equation\b", "Quadratic Equations"),
    (r"\bpolynomial\w*|\bremainder theorem\b|\bhorner\b", "Polynomials"),
    (r"\blogarithm\w*|\blog\b|\bln\b|\blog base\b", "Logarithms"),
    (
        r"\binequalit\w*|\barithmetic-harmonic\b|\bcauchy\s*-?\s*schwarz\b|\bam-?gm\b",
        "Inequalities",
    ),
    (
        r"\bconic\w*|\bellipse\b|\bparabola\w*|\bhyperbola\w*|\bchord\b|\bdirectrix\b"
        r"|\beccentricity\b",
        "Conics",
    ),
    (r"\bcircle\b", "Circles"),
    (
        r"\btriangle\w*|\bquadrilateral\w*|\bpolygon\w*|\brhombus\b|\btrapezium\b"
        r"|\bparallelogram\b|\bsphere\b|\bcylinder\b|\bcone\b",
        "Geometry",
    ),
    (r"\bfunction\w*|\bdomain\b|\brange\b|\bone-one\b|\bonto\b|\bmapping\b", "Functions"),
    (r"\bset\w*|\bsubset\w*|\bunion\b|\bintersection\b|\bvenn\b", "Sets & Relations"),
    (
        r"\bmaximi[sz]\w*|\bminimi[sz]\w*|\boptimi[sz]\w*|\bmaximum value\b|\bminimum value\b",
        "Optimisation",
    ),
)

LATEX_LEXICON: dict[str, str] = {
    "int": "Integration",
    "iint": "Integration",
    "oint": "Integration",
    "lim": "Limits & Continuity",
    "infty": "Limits & Continuity",
    "frac": "Limits & Continuity",
    "partial": "Differentiation",
    "nabla": "Vectors",
    "sin": "Trigonometry",
    "cos": "Trigonometry",
    "tan": "Trigonometry",
    "sec": "Trigonometry",
    "cot": "Trigonometry",
    "arcsin": "Trigonometry",
    "arccos": "Trigonometry",
    "theta": "Trigonometry",
    "alpha": "Trigonometry",
    "beta": "Trigonometry",
    "omega": "Trigonometry",
    "phi": "Trigonometry",
    "log": "Logarithms",
    "ln": "Logarithms",
    "exp": "Exponentials",
    "sum": "Sequences & Series",
    "prod": "Sequences & Series",
    "binom": "Permutations & Combinations",
    "factorial": "Permutations & Combinations",
    "matrix": "Matrices & Determinants",
    "pmatrix": "Matrices & Determinants",
    "bmatrix": "Matrices & Determinants",
    "vmatrix": "Matrices & Determinants",
    "det": "Matrices & Determinants",
    "begin": "Matrices & Determinants",
    "vec": "Vectors",
    "hat": "Vectors",
    "overrightarrow": "Vectors",
    "min": "Optimisation",
    "max": "Optimisation",
    "in": "Sets & Relations",
    "cup": "Sets & Relations",
    "cap": "Sets & Relations",
    "subset": "Sets & Relations",
    "subseteq": "Sets & Relations",
    "mathbb": "Complex Numbers",
    "overline": "Complex Numbers",
    "operatorname": "Functions",
}

_KEYWORD_PATTERNS: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), concept) for pattern, concept in KEYWORD_LEXICON
)

# ``\begin{...}`` is only evidence of a matrix when the environment is one.
_MATRIX_ENVIRONMENTS = frozenset({"matrix", "pmatrix", "bmatrix", "vmatrix", "cases", "array"})
_MATRIX_RE = re.compile(r"\\begin\s*\{\s*([a-zA-Z]+)\s*\}")


@dataclass(frozen=True)
class ConceptHit:
    """A concept found in one question, with the source that produced it."""

    name: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "source": self.source}


def _dedupe(hits: Iterable[ConceptHit]) -> list[ConceptHit]:
    """Keep the highest-priority source per concept name, preserving order."""

    best: dict[str, ConceptHit] = {}
    order: list[str] = []
    for hit in hits:
        key = _key(hit.name)
        existing = best.get(key)
        if existing is None:
            best[key] = hit
            order.append(key)
        elif _SOURCE_RANK.get(hit.source, 99) < _SOURCE_RANK.get(existing.source, 99):
            best[key] = hit
    return [best[key] for key in order]


def concepts_from_tags(question: Question) -> list[ConceptHit]:
    hits: list[ConceptHit] = []
    for raw in question.concepts:
        for piece in re.split(r"[;,/]|\bor\b", raw):
            name = normalise_concept(piece)
            if name:
                hits.append(ConceptHit(name=name, source="tag"))
    return _dedupe(hits)


def concepts_from_keywords(question: Question) -> list[ConceptHit]:
    text = question.all_text
    if not text:
        return []
    hits = [
        ConceptHit(name=concept, source="keyword")
        for pattern, concept in _KEYWORD_PATTERNS
        if pattern.search(text)
    ]
    return _dedupe(hits)


def concepts_from_latex(question: Question) -> list[ConceptHit]:
    text = question.all_text
    if not text:
        return []
    hits: list[ConceptHit] = []
    for match in _LATEX_TOKEN.finditer(text):
        concept = LATEX_LEXICON.get(match.group(1).lower())
        if concept:
            hits.append(ConceptHit(name=concept, source="latex"))
    for match in _MATRIX_RE.finditer(text):
        if match.group(1).lower() in _MATRIX_ENVIRONMENTS:
            hits.append(ConceptHit(name="Matrices & Determinants", source="latex"))
    return _dedupe(hits)


_EXTRACTORS = {
    "tag": concepts_from_tags,
    "keyword": concepts_from_keywords,
    "latex": concepts_from_latex,
}


def extract_concepts(
    question: Question, sources: Sequence[str] | None = None
) -> list[ConceptHit]:
    """Concepts for one question, from the requested ``sources``."""

    selected = tuple(sources) if sources else SOURCES
    hits: list[ConceptHit] = []
    for source in SOURCES:
        if source in selected and source in _EXTRACTORS:
            hits.extend(_EXTRACTORS[source](question))
    return _dedupe(hits)
