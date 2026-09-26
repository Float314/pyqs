"""Statistical analysis over parsed papers.

Every public function takes an iterable of :class:`~pyqs.models.Paper` and
returns a *report* object. Reports are plain dataclasses that know how to
serialise themselves (:meth:`to_dict`, :meth:`to_rows`) so the CLI can render
them as a table, JSON, CSV or Markdown without the analysis layer importing any
presentation code.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyqs import concepts as concept_tools
from pyqs.errors import NoDataError
from pyqs.models import Paper, Question
from pyqs.parser import DEFAULT_TOPIC, format_type_name, parse_paper, type_sort_key

# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


@dataclass
class Filters:
    """Restrict a question set before analysis."""

    topics: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    years: tuple[int, ...] = ()
    min_marks: float | None = None
    max_marks: float | None = None
    grep: str | None = None
    ids: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(
            self.topics
            or self.types
            or self.years
            or self.min_marks is not None
            or self.max_marks is not None
            or self.grep
            or self.ids
        )

    def matches(self, question: Question) -> bool:
        if self.topics and (question.topic or DEFAULT_TOPIC).casefold() not in self.topics:
            return False
        if self.types and question.type not in self.types:
            return False
        if self.years and (question.year is None or question.year not in self.years):
            return False
        marks = question.effective_marks
        if self.min_marks is not None and marks < self.min_marks:
            return False
        if self.max_marks is not None and marks > self.max_marks:
            return False
        if self.ids and question.id.casefold() not in self.ids:
            return False
        return not (self.grep and not question.matches_text(self.grep))

    def describe(self) -> str:
        parts: list[str] = []
        if self.topics:
            parts.append("topic in " + ", ".join(self.topics))
        if self.types:
            parts.append("type in " + ", ".join(format_type_name(t) for t in self.types))
        if self.years:
            parts.append("year in " + ", ".join(str(y) for y in self.years))
        if self.min_marks is not None:
            parts.append(f"marks >= {self.min_marks:g}")
        if self.max_marks is not None:
            parts.append(f"marks <= {self.max_marks:g}")
        if self.grep:
            parts.append(f"text contains {self.grep!r}")
        if self.ids:
            parts.append("id in " + ", ".join(self.ids))
        return "; ".join(parts)


def select_questions(papers: Sequence[Paper], filters: Filters | None = None) -> list[Question]:
    """All questions of ``papers``, optionally narrowed by ``filters``."""

    active = filters or Filters()
    questions: list[Question] = []
    for paper in papers:
        for question in paper.questions:
            if active.matches(question):
                questions.append(question)
    return questions


def _require(questions: Sequence[Any], what: str) -> None:
    if not questions:
        raise NoDataError(f"no {what} matched the given inputs and filters")


def _ratio(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


@dataclass
class Summary:
    """Headline numbers for a set of papers."""

    papers: int
    questions: int
    marks: float
    topics: int
    types: int
    years: list[int]
    mean_marks: float
    median_marks: float
    paper_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "papers": self.papers,
            "questions": self.questions,
            "marks": self.marks,
            "topics": self.topics,
            "types": self.types,
            "years": self.years,
            "mean_marks": self.mean_marks,
            "median_marks": self.median_marks,
            "paper_details": self.paper_rows,
            "warnings": self.warnings,
        }

    def to_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = [
            {"metric": "papers", "value": self.papers},
            {"metric": "questions", "value": self.questions},
            {"metric": "total marks", "value": self.marks},
            {"metric": "topics", "value": self.topics},
            {"metric": "question types", "value": self.types},
            {"metric": "years", "value": ", ".join(str(y) for y in self.years) or "-"},
            {"metric": "mean marks / question", "value": round(self.mean_marks, 2)},
            {"metric": "median marks / question", "value": round(self.median_marks, 2)},
            {"metric": "warnings", "value": len(self.warnings)},
        ]
        rows.extend({"metric": "paper", "value": row["name"]} for row in self.paper_rows)
        return rows


@dataclass
class TopicStat:
    topic: str
    questions: int
    marks: float
    share: float
    marks_share: float
    avg_marks: float
    min_marks: float
    max_marks: float
    papers: int
    types: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "questions": self.questions,
            "marks": self.marks,
            "share": self.share,
            "marks_share": self.marks_share,
            "avg_marks": self.avg_marks,
            "min_marks": self.min_marks,
            "max_marks": self.max_marks,
            "papers": self.papers,
            "types": dict(sorted(self.types.items(), key=lambda kv: -kv[1])),
        }


@dataclass
class TopicReport:
    rows: list[TopicStat]
    total_questions: int
    total_marks: float
    papers: int
    filters: str = ""

    @property
    def topics(self) -> list[str]:
        return [row.topic for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "total_marks": self.total_marks,
            "papers": self.papers,
            "filters": self.filters,
            "topics": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "topic": row.topic,
                "questions": row.questions,
                "marks": row.marks,
                "share": round(row.share * 100, 2),
                "marks_share": round(row.marks_share * 100, 2),
                "avg_marks": round(row.avg_marks, 2),
                "min_marks": row.min_marks,
                "max_marks": row.max_marks,
                "papers": row.papers,
                "types": ", ".join(
                    f"{k}={v}" for k, v in sorted(row.types.items(), key=lambda kv: -kv[1])
                ),
            }
            for row in self.rows
        ]


@dataclass
class TypeStat:
    type: str
    label: str
    questions: int
    marks: float
    share: float
    marks_share: float
    avg_marks: float
    papers: int
    topics: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "questions": self.questions,
            "marks": self.marks,
            "share": self.share,
            "marks_share": self.marks_share,
            "avg_marks": self.avg_marks,
            "papers": self.papers,
            "topics": self.topics,
        }


@dataclass
class TypeReport:
    rows: list[TypeStat]
    total_questions: int
    total_marks: float
    papers: int
    filters: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "total_marks": self.total_marks,
            "papers": self.papers,
            "filters": self.filters,
            "types": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "type": row.type,
                "label": row.label,
                "questions": row.questions,
                "marks": row.marks,
                "share": round(row.share * 100, 2),
                "marks_share": round(row.marks_share * 100, 2),
                "avg_marks": round(row.avg_marks, 2),
                "papers": row.papers,
                "topics": row.topics,
            }
            for row in self.rows
        ]


@dataclass
class MarksBucket:
    marks: float
    questions: int
    share: float
    cumulative_share: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "marks": self.marks,
            "questions": self.questions,
            "share": self.share,
            "cumulative_share": self.cumulative_share,
        }


@dataclass
class MarksReport:
    total_marks: float
    total_questions: int
    mean_marks: float
    median_marks: float
    min_marks: float
    max_marks: float
    inferred_marks: float
    missing_marks: int
    buckets: list[MarksBucket]
    by_type: list[TypeStat]
    filters: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_marks": self.total_marks,
            "total_questions": self.total_questions,
            "mean_marks": self.mean_marks,
            "median_marks": self.median_marks,
            "min_marks": self.min_marks,
            "max_marks": self.max_marks,
            "inferred_marks": self.inferred_marks,
            "missing_marks": self.missing_marks,
            "filters": self.filters,
            "histogram": [bucket.to_dict() for bucket in self.buckets],
            "by_type": [row.to_dict() for row in self.by_type],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "marks": bucket.marks,
                "questions": bucket.questions,
                "share": round(bucket.share * 100, 2),
                "cumulative_share": round(bucket.cumulative_share * 100, 2),
            }
            for bucket in self.buckets
        ]


@dataclass
class ConceptStat:
    concept: str
    questions: int
    share: float
    papers: int
    years: list[int]
    sources: dict[str, int]
    topics: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "questions": self.questions,
            "share": self.share,
            "papers": self.papers,
            "years": self.years,
            "sources": dict(self.sources),
            "topics": list(self.topics),
        }


@dataclass
class ConceptReport:
    rows: list[ConceptStat]
    total_questions: int
    papers: int
    sources: list[str]
    filters: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "papers": self.papers,
            "sources": self.sources,
            "filters": self.filters,
            "concepts": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "concept": row.concept,
                "questions": row.questions,
                "share": round(row.share * 100, 2),
                "papers": row.papers,
                "years": ", ".join(str(year) for year in row.years) or "-",
                "sources": ", ".join(
                    f"{k}={v}" for k, v in sorted(row.sources.items(), key=lambda kv: -kv[1])
                ),
                "topics": ", ".join(row.topics),
            }
            for row in self.rows
        ]


@dataclass
class QuestionRow:
    id: str
    type: str
    marks: float
    topic: str
    year: int | None
    parts: int
    concepts: list[str]
    text: str
    source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "marks": self.marks,
            "topic": self.topic,
            "year": self.year,
            "parts": self.parts,
            "concepts": list(self.concepts),
            "text": self.text,
            "source": self.source,
        }


@dataclass
class QuestionListReport:
    rows: list[QuestionRow]
    total_questions: int
    total_marks: float
    filters: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_questions": self.total_questions,
            "total_marks": self.total_marks,
            "filters": self.filters,
            "questions": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "id": row.id,
                "type": row.type,
                "marks": row.marks,
                "topic": row.topic,
                "year": row.year if row.year is not None else "",
                "parts": row.parts,
                "concepts": ", ".join(row.concepts),
                "text": row.text,
                "source": row.source or "",
            }
            for row in self.rows
        ]


@dataclass
class TopicDelta:
    topic: str
    baseline_questions: int
    variant_questions: int
    question_delta: int
    baseline_marks: float
    variant_marks: float
    marks_delta: float
    share_delta: float
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "baseline_questions": self.baseline_questions,
            "variant_questions": self.variant_questions,
            "question_delta": self.question_delta,
            "baseline_marks": self.baseline_marks,
            "variant_marks": self.variant_marks,
            "marks_delta": self.marks_delta,
            "share_delta": self.share_delta,
            "status": self.status,
        }


@dataclass
class ComparisonReport:
    baseline_label: str
    variant_label: str
    baseline: Summary
    variant: Summary
    rows: list[TopicDelta]
    added_topics: list[str]
    removed_topics: list[str]

    @property
    def question_delta(self) -> int:
        return self.variant.questions - self.baseline.questions

    @property
    def marks_delta(self) -> float:
        return self.variant.marks - self.baseline.marks

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": {"label": self.baseline_label, **self.baseline.to_dict()},
            "variant": {"label": self.variant_label, **self.variant.to_dict()},
            "question_delta": self.question_delta,
            "marks_delta": self.marks_delta,
            "added_topics": self.added_topics,
            "removed_topics": self.removed_topics,
            "topics": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "topic": row.topic,
                "baseline_questions": row.baseline_questions,
                "variant_questions": row.variant_questions,
                "question_delta": row.question_delta,
                "baseline_marks": row.baseline_marks,
                "variant_marks": row.variant_marks,
                "marks_delta": row.marks_delta,
                "share_delta": round(row.share_delta * 100, 2),
                "status": row.status,
            }
            for row in self.rows
        ]


@dataclass
class TrendRow:
    year: int
    topic: str
    questions: int
    marks: float
    share: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "topic": self.topic,
            "questions": self.questions,
            "marks": self.marks,
            "share": self.share,
        }


@dataclass
class TrendReport:
    years: list[int]
    rows: list[TrendRow]
    per_year: list[dict[str, Any]]
    changes: list[dict[str, Any]]
    papers: int
    filters: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "years": self.years,
            "papers": self.papers,
            "filters": self.filters,
            "per_year": self.per_year,
            "changes": self.changes,
            "series": [row.to_dict() for row in self.rows],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "year": row.year,
                "topic": row.topic,
                "questions": row.questions,
                "marks": row.marks,
                "share": round(row.share * 100, 2),
            }
            for row in self.rows
        ]


@dataclass
class FileValidation:
    path: str
    ok: bool
    papers: int
    questions: int
    marks: float
    warnings: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "papers": self.papers,
            "questions": self.questions,
            "marks": self.marks,
            "warnings": list(self.warnings),
            "error": self.error,
        }

    def to_row(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": "yes" if self.ok else "no",
            "papers": self.papers,
            "questions": self.questions,
            "marks": self.marks,
            "warnings": len(self.warnings),
            "error": self.error or "",
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [self.to_row()]


@dataclass
class ValidationReport:
    files: list[FileValidation]
    filters: str = ""

    @property
    def failures(self) -> list[FileValidation]:
        return [item for item in self.files if not item.ok]

    @property
    def warning_count(self) -> int:
        return sum(len(item.warnings) for item in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [item.to_dict() for item in self.files],
            "ok": not self.failures,
            "files_checked": len(self.files),
            "failures": len(self.failures),
            "warnings": self.warning_count,
        }

    def to_rows(self) -> list[dict[str, Any]]:
        return [item.to_row() for item in self.files]


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #


def summarise(papers: Sequence[Paper], questions: Sequence[Question] | None = None) -> Summary:
    """Headline statistics for a set of papers."""

    selected = list(questions) if questions is not None else select_questions(papers)
    marks = [question.effective_marks for question in selected]
    topics = {(question.topic or DEFAULT_TOPIC) for question in selected}
    types = {question.type for question in selected}
    years = sorted({paper.year for paper in papers if paper.year is not None})
    paper_rows = [{**paper.to_dict(), "share": 0.0} for paper in papers]
    total_questions = max(len(selected), 1)
    for row in paper_rows:
        row["share"] = round(_ratio(row["total_questions"], total_questions) * 100, 2)
    _disambiguate_names(paper_rows)
    return Summary(
        papers=len(papers),
        questions=len(selected),
        marks=float(sum(marks)),
        topics=len(topics),
        types=len(types),
        years=years,
        mean_marks=float(statistics.fmean(marks)) if marks else 0.0,
        median_marks=float(statistics.median(marks)) if marks else 0.0,
        paper_rows=paper_rows,
        warnings=[f"{paper.name}: {warning}" for paper in papers for warning in paper.warnings],
    )


def _disambiguate_names(rows: list[dict[str, Any]]) -> None:
    """Append the file name when several papers share the same label."""

    totals: dict[str, int] = {}
    for row in rows:
        totals[row["name"]] = totals.get(row["name"], 0) + 1
    for row in rows:
        if totals[row["name"]] > 1 and row.get("path"):
            file_name = str(Path(row["path"])).replace("\\", "/").rsplit("/", 1)[-1]
            row["name"] = f"{row['name']} ({file_name})"


def topic_stats(
    papers: Sequence[Paper],
    filters: Filters | None = None,
    sort: str = "questions",
    limit: int | None = None,
    min_questions: int = 1,
) -> TopicReport:
    """Per-topic question counts, marks and shares."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")

    buckets: dict[str, list[Question]] = {}
    for question in questions:
        buckets.setdefault(question.topic or DEFAULT_TOPIC, []).append(question)

    total_questions = len(questions)
    total_marks = float(sum(question.effective_marks for question in questions))
    papers_by_topic: dict[str, set] = {}

    rows: list[TopicStat] = []
    for topic, items in buckets.items():
        marks = [item.effective_marks for item in items]
        topic_marks = float(sum(marks))
        types: dict[str, int] = {}
        for item in items:
            types[item.type] = types.get(item.type, 0) + 1
        papers_by_topic[topic] = {item.paper_key for item in items}
        rows.append(
            TopicStat(
                topic=topic,
                questions=len(items),
                marks=topic_marks,
                share=_ratio(len(items), total_questions),
                marks_share=_ratio(topic_marks, total_marks),
                avg_marks=topic_marks / len(items),
                min_marks=min(marks),
                max_marks=max(marks),
                papers=len(papers_by_topic[topic]),
                types=types,
            )
        )

    rows = [row for row in rows if row.questions >= min_questions]
    rows = _sort_rows(rows, sort, "topic")
    if limit is not None:
        rows = rows[:limit]
    return TopicReport(
        rows=rows,
        total_questions=total_questions,
        total_marks=total_marks,
        papers=len(papers),
        filters=active.describe(),
    )


def _sort_rows(rows: list[Any], sort: str, name_key: str) -> list[Any]:
    """Sort report rows, tolerating rows that lack some statistics."""

    def name(row: Any) -> str:
        return getattr(row, name_key).casefold()

    def marks(row: Any) -> float:
        return float(getattr(row, "marks", 0) or 0)

    keys = {
        "questions": lambda row: (-row.questions, -marks(row), name(row)),
        "papers": lambda row: (-row.papers, -row.questions, name(row)),
        "marks": lambda row: (-marks(row), -row.questions, name(row)),
        "avg": lambda row: (-row.avg_marks, -row.questions, name(row)),
        "name": name,
        "share": lambda row: (-row.share, -row.questions, name(row)),
    }
    if sort == "count":
        sort = "questions"
    if sort == "total":
        sort = "marks"
    return sorted(rows, key=keys.get(sort, keys["questions"]))


def type_stats(
    papers: Sequence[Paper], filters: Filters | None = None
) -> TypeReport:
    """Distribution of question types (MCQ, numerical, short answer, ...)."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")

    buckets: dict[str, list[Question]] = {}
    for question in questions:
        buckets.setdefault(question.type, []).append(question)

    total_questions = len(questions)
    total_marks = float(sum(question.effective_marks for question in questions))

    rows: list[TypeStat] = []
    for key, items in buckets.items():
        type_marks = float(sum(item.effective_marks for item in items))
        rows.append(
            TypeStat(
                type=key,
                label=format_type_name(key),
                questions=len(items),
                marks=type_marks,
                share=_ratio(len(items), total_questions),
                marks_share=_ratio(type_marks, total_marks),
                avg_marks=type_marks / len(items),
                papers=len({item.paper_key for item in items}),
                topics=len({item.topic or DEFAULT_TOPIC for item in items}),
            )
        )
    rows.sort(key=lambda row: (type_sort_key(row.type), row.label.casefold()))
    return TypeReport(
        rows=rows,
        total_questions=total_questions,
        total_marks=total_marks,
        papers=len(papers),
        filters=active.describe(),
    )


def marks_distribution(
    papers: Sequence[Paper], filters: Filters | None = None
) -> MarksReport:
    """How marks are spread: histogram, mean/median, and marks per type."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")

    marks = [question.effective_marks for question in questions]
    total_marks = float(sum(marks))

    counts: dict[float, int] = {}
    for value in marks:
        counts[value] = counts.get(value, 0) + 1

    buckets: list[MarksBucket] = []
    running = 0
    for value in sorted(counts):
        count = counts[value]
        share = _ratio(count, len(questions))
        running += share
        buckets.append(
            MarksBucket(
                marks=value,
                questions=count,
                share=share,
                cumulative_share=running,
            )
        )

    return MarksReport(
        total_marks=total_marks,
        total_questions=len(questions),
        mean_marks=float(statistics.fmean(marks)),
        median_marks=float(statistics.median(marks)),
        min_marks=min(marks),
        max_marks=max(marks),
        inferred_marks=float(
            sum(
                question.effective_marks
                for question in questions
                if question.marks is None and question.has_declared_marks
            )
        ),
        missing_marks=sum(1 for question in questions if not question.has_declared_marks),
        buckets=buckets,
        by_type=type_stats(papers, active).rows,
        filters=active.describe(),
    )


def concept_stats(
    papers: Sequence[Paper],
    filters: Filters | None = None,
    sources: Sequence[str] | None = None,
    sort: str = "questions",
    limit: int | None = None,
    min_questions: int = 1,
    min_papers: int = 1,
) -> ConceptReport:
    """How often each concept appears, and how widely it is spread."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")
    selected_sources = list(sources) if sources else list(concept_tools.SOURCES)
    if not selected_sources:
        raise NoDataError("no concept sources selected")

    hits_by_concept: dict[str, list[tuple[Question, str]]] = {}
    display: dict[str, str] = {}
    for question in questions:
        for hit in concept_tools.extract_concepts(question, selected_sources):
            key = hit.name.casefold()
            display.setdefault(key, hit.name)
            hits_by_concept.setdefault(key, []).append((question, hit.source))

    total_questions = len(questions)
    if not hits_by_concept:
        raise NoDataError("no concepts matched the selected sources")
    rows: list[ConceptStat] = []
    for key, hits in hits_by_concept.items():
        unique_questions = {id(question) for question, _ in hits}
        sources_counts: dict[str, int] = {}
        topics: dict[str, int] = {}
        for question, source in hits:
            sources_counts[source] = sources_counts.get(source, 0) + 1
            topic = question.topic or DEFAULT_TOPIC
            topics[topic] = topics.get(topic, 0) + 1
        papers_seen = {question.paper_key for question, _ in hits}
        if len(papers_seen) < min_papers:
            continue
        questions_seen = len(unique_questions)
        if questions_seen < min_questions:
            continue
        rows.append(
            ConceptStat(
                concept=display[key],
                questions=questions_seen,
                share=_ratio(questions_seen, total_questions),
                papers=len(papers_seen),
                years=sorted({q.year for q, _ in hits if q.year is not None}),
                sources=sources_counts,
                topics=[
                    name for name, _ in sorted(topics.items(), key=lambda kv: (-kv[1], kv[0]))
                ][:4],
            )
        )

    rows = _sort_rows(rows, sort, "concept")
    if limit is not None:
        rows = rows[:limit]
    return ConceptReport(
        rows=rows,
        total_questions=total_questions,
        papers=len(papers),
        sources=selected_sources,
        filters=active.describe(),
    )


def question_rows(
    papers: Sequence[Paper],
    filters: Filters | None = None,
    sort: str = "paper",
    limit: int | None = None,
) -> QuestionListReport:
    """One row per question, for inspection and export."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")

    keyed = [
        (index, question)
        for index, paper in enumerate(papers)
        for question in paper.questions
        if active.matches(question)
    ]
    key_funcs = {
        "paper": lambda item: (item[0], item[1].id),
        "marks": lambda item: (-item[1].effective_marks, item[1].id),
        "id": lambda item: (item[1].id,),
        "type": lambda item: (type_sort_key(item[1].type), item[1].id),
        "topic": lambda item: ((item[1].topic or DEFAULT_TOPIC).casefold(), item[1].id),
    }
    keyed.sort(key=key_funcs.get(sort, key_funcs["paper"]))
    if limit is not None:
        keyed = keyed[:limit]

    rows = [
        QuestionRow(
            id=question.id,
            type=question.type,
            marks=question.effective_marks,
            topic=question.topic or DEFAULT_TOPIC,
            year=question.year,
            parts=question.part_count,
            concepts=sorted(
                {hit.name for hit in concept_tools.extract_concepts(question)},
                key=str.casefold,
            ),
            text=question.text,
            source=question.source,
        )
        for _, question in keyed
    ]
    return QuestionListReport(
        rows=rows,
        total_questions=len(questions),
        total_marks=float(sum(question.effective_marks for question in questions)),
        filters=active.describe(),
    )


def compare(
    baseline_papers: Sequence[Paper], variant_papers: Sequence[Paper]
) -> ComparisonReport:
    """Compare two sets of papers topic by topic."""

    baseline_questions = select_questions(baseline_papers)
    variant_questions = select_questions(variant_papers)
    _require(baseline_questions, "questions in the baseline set")
    _require(variant_questions, "questions in the variant set")

    baseline = summarise(baseline_papers, baseline_questions)
    variant = summarise(variant_papers, variant_questions)

    baseline_map = {row.topic: row for row in topic_stats(baseline_papers).rows}
    variant_map = {row.topic: row for row in topic_stats(variant_papers).rows}

    rows: list[TopicDelta] = []
    for topic in sorted(set(baseline_map) | set(variant_map)):
        base_row = baseline_map.get(topic)
        var_row = variant_map.get(topic)
        base_count = base_row.questions if base_row else 0
        var_count = var_row.questions if var_row else 0
        base_marks = base_row.marks if base_row else 0.0
        var_marks = var_row.marks if var_row else 0.0
        delta = var_count - base_count
        if base_count == 0:
            status = "new"
        elif var_count == 0:
            status = "dropped"
        elif delta > 0:
            status = "up"
        elif delta < 0:
            status = "down"
        else:
            status = "flat"
        rows.append(
            TopicDelta(
                topic=topic,
                baseline_questions=base_count,
                variant_questions=var_count,
                question_delta=delta,
                baseline_marks=base_marks,
                variant_marks=var_marks,
                marks_delta=var_marks - base_marks,
                share_delta=(
                    (var_row.share if var_row else 0.0) - (base_row.share if base_row else 0.0)
                ),
                status=status,
            )
        )

    rows.sort(key=lambda row: (-abs(row.question_delta), -row.marks_delta, row.topic.casefold()))
    return ComparisonReport(
        baseline_label=_label(baseline_papers),
        variant_label=_label(variant_papers),
        baseline=baseline,
        variant=variant,
        rows=rows,
        added_topics=sorted(topic for topic in variant_map if topic not in baseline_map),
        removed_topics=sorted(topic for topic in baseline_map if topic not in variant_map),
    )


def trend(
    papers: Sequence[Paper], filters: Filters | None = None, limit: int | None = None
) -> TrendReport:
    """Year-on-year movement of topics. Requires at least two distinct years."""

    active = filters or Filters()
    questions = select_questions(papers, active)
    _require(questions, "questions")

    by_year_topic: dict[int, dict[str, list[Question]]] = {}
    for question in questions:
        year = question.year
        if year is None:
            continue
        by_year_topic.setdefault(year, {}).setdefault(
            question.topic or DEFAULT_TOPIC, []
        ).append(question)

    years = sorted(by_year_topic)
    if len(years) < 2:
        found = ", ".join(str(year) for year in years) or "none"
        raise NoDataError(
            "trend needs at least two distinct years in the input; found: " + found
        )

    rows: list[TrendRow] = []
    per_year: list[dict[str, Any]] = []
    for year in years:
        topics = by_year_topic[year]
        year_questions = [question for items in topics.values() for question in items]
        year_marks = float(sum(question.effective_marks for question in year_questions))
        per_year.append(
            {
                "year": year,
                "questions": len(year_questions),
                "marks": year_marks,
                "topics": len(topics),
                "papers": len({q.paper_key for q in year_questions}),
            }
        )
        for topic, items in topics.items():
            rows.append(
                TrendRow(
                    year=year,
                    topic=topic,
                    questions=len(items),
                    marks=float(sum(item.effective_marks for item in items)),
                    share=_ratio(len(items), len(year_questions)),
                )
            )

    totals = {
        topic: sum(row.questions for row in rows if row.topic == topic)
        for topic in {row.topic for row in rows}
    }
    changes: list[dict[str, Any]] = []
    for topic, total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0].casefold())):
        series = {row.year: row.questions for row in rows if row.topic == topic}
        first, last = years[0], years[-1]
        changes.append(
            {
                "topic": topic,
                "questions": total,
                "first_year": first,
                "first_count": series.get(first, 0),
                "last_year": last,
                "last_count": series.get(last, 0),
                "delta": series.get(last, 0) - series.get(first, 0),
                "series": [series.get(year, 0) for year in years],
            }
        )
    changes.sort(key=lambda row: (-row["questions"], row["topic"].casefold()))
    if limit is not None:
        changes = changes[:limit]

    return TrendReport(
        years=years,
        rows=rows,
        per_year=per_year,
        changes=changes,
        papers=len(papers),
        filters=active.describe(),
    )


def _label(papers: Sequence[Paper]) -> str:
    if not papers:
        return "(empty)"
    if len(papers) == 1:
        return papers[0].name
    return f"{len(papers)} papers"


def validate_files(paths: Iterable[Path], filters: Filters | None = None) -> ValidationReport:
    """Parse each file independently and report the outcome (used by ``pyqs validate``)."""

    results: list[FileValidation] = []
    for path in paths:
        try:
            papers = parse_paper(path)
        except Exception as exc:
            results.append(
                FileValidation(
                    path=str(path),
                    ok=False,
                    papers=0,
                    questions=0,
                    marks=0.0,
                    warnings=[],
                    error=str(exc),
                )
            )
            continue
        questions = select_questions(papers, filters)
        results.append(
            FileValidation(
                path=str(path),
                ok=True,
                papers=len(papers),
                questions=len(questions),
                marks=float(sum(question.effective_marks for question in questions)),
                warnings=[warning for paper in papers for warning in paper.warnings],
            )
        )
    return ValidationReport(files=results, filters=(filters or Filters()).describe())
