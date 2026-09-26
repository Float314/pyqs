"""Domain model for parsed question banks.

A *paper* is one question paper (one XML file, or one ``<paper>`` section of a
file). A *question* is one ``<question_body>`` element. Everything the analysis
engine needs is stored as plain dataclasses so reports can be computed without
touching the XML again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

_WHITESPACE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """Collapse whitespace and strip, keeping the LaTeX payloads intact.

    Newlines inside ``\\[ ... \\]`` display math are collapsed to a single space.
    That keeps stem matching and table rendering predictable while leaving the
    mathematical content untouched.
    """

    if not text:
        return ""
    return _WHITESPACE.sub(" ", text).strip()


def format_marks(value: float | None) -> str:
    """Render a mark count without a pointless ``.0`` suffix."""

    if value is None:
        return "-"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


@dataclass(frozen=True)
class Option:
    """One selectable option of a multiple-choice question."""

    label: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "text": self.text}


@dataclass(frozen=True)
class Part:
    """A sub-part (``<part>``) of a question with its own marks."""

    id: str
    text: str
    marks: float | None = None
    subparts: tuple[Part, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "text": self.text, "marks": self.marks}
        if self.subparts:
            data["subparts"] = [part.to_dict() for part in self.subparts]
        return data


@dataclass
class Question:
    """A single question with its metadata, options, answer and parts."""

    id: str
    type: str
    marks: float | None
    text: str
    topic: str | None = None
    options: list[Option] = field(default_factory=list)
    answer: str | None = None
    assertion: str | None = None
    reason: str | None = None
    parts: list[Part] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    source: str | None = None
    year: int | None = None
    extra: dict[str, str] = field(default_factory=dict)
    paper_id: int | None = field(default=None, compare=False)

    @property
    def paper_key(self) -> tuple[str | None, int | None]:
        """Identity of the owning paper: its file plus its own identity.

        A single file may hold several papers, so the file path alone is not a
        reliable "how many papers did this topic appear in" answer.
        """

        return (self.source, self.paper_id)

    @property
    def effective_marks(self) -> float:
        """Marks attributable to the question.

        Falls back to the sum of the sub-parts when the bank does not declare
        marks on the question itself, and to ``0.0`` when nothing is declared.
        """

        if self.marks is not None:
            return float(self.marks)
        if self.parts:
            return float(sum((part.marks or 0.0) for part in self.all_parts()))
        return 0.0

    @property
    def has_declared_marks(self) -> bool:
        return self.marks is not None or any(part.marks is not None for part in self.all_parts())

    @property
    def part_count(self) -> int:
        return len(self.parts)

    def all_parts(self) -> list[Part]:
        """Every part in the tree, depth-first, parents before children."""

        collected: list[Part] = []
        stack = list(reversed(self.parts))
        while stack:
            part = stack.pop()
            collected.append(part)
            stack.extend(reversed(part.subparts))
        return collected

    @property
    def all_text(self) -> str:
        """Every scrap of prose attached to the question, answer included.

        The answer is part of the record and often names the technique used, so
        it is searched by concept extraction and by ``--grep``.
        """

        chunks = [self.text, self.assertion, self.reason, self.answer]
        chunks.extend(part.text for part in self.all_parts())
        return clean_text(" ".join(chunk for chunk in chunks if chunk))

    @property
    def answer_label(self) -> str | None:
        """The answer reduced to an option label when it points at one."""

        if not self.answer:
            return None
        candidate = self.answer.strip()
        if len(candidate) == 1:
            return candidate.upper()
        return None

    def matches_text(self, needle: str) -> bool:
        return needle.casefold() in self.all_text.casefold()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "marks": self.marks,
            "effective_marks": self.effective_marks,
            "topic": self.topic,
            "text": self.text,
            "options": [option.to_dict() for option in self.options],
            "answer": self.answer,
            "assertion": self.assertion,
            "reason": self.reason,
            "parts": [part.to_dict() for part in self.parts],
            "concepts": list(self.concepts),
            "source": self.source,
            "year": self.year,
        }
        if self.extra:
            data["extra"] = dict(self.extra)
        return data


@dataclass
class Paper:
    """A single question paper: metadata plus the questions it contains."""

    questions: list[Question] = field(default_factory=list)
    path: str | None = None
    exam: str | None = None
    year: int | None = None
    subject: str | None = None
    board: str | None = None
    title: str | None = None
    latex: bool = True
    schema_version: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """A short human label built from the declared metadata."""

        bits = [self.exam, str(self.year) if self.year else None, self.subject]
        label = " ".join(bit for bit in bits if bit)
        if label:
            return label
        if self.title:
            return self.title
        if self.path:
            return self.path.replace("\\", "/").rsplit("/", 1)[-1]
        return "untitled paper"

    @property
    def total_questions(self) -> int:
        return len(self.questions)

    @property
    def total_marks(self) -> float:
        return float(sum(question.effective_marks for question in self.questions))

    def add(self, question: Question) -> None:
        question.source = self.path
        question.year = self.year
        question.paper_id = id(self)
        self.questions.append(question)

    def extend(self, questions: Iterable[Question]) -> None:
        for question in questions:
            self.add(question)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "exam": self.exam,
            "year": self.year,
            "subject": self.subject,
            "board": self.board,
            "latex": self.latex,
            "schema_version": self.schema_version,
            "total_questions": self.total_questions,
            "total_marks": self.total_marks,
            "warnings": list(self.warnings),
        }


def group_by(items: Sequence[Any], key) -> dict[Any, list[Any]]:
    """Minimal ordered ``itertools.groupby``-style grouping helper."""

    grouped: dict[Any, list[Any]] = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return grouped
