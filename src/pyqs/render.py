"""Presentation layer: turn reports into tables, JSON, CSV or Markdown.

The analysis layer never imports this module. Each renderer takes a report
object and returns a string, so the CLI stays a thin switchboard.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from typing import Any, Callable, ClassVar

from pyqs.analysis import (
    ComparisonReport,
    ConceptReport,
    MarksReport,
    QuestionListReport,
    Summary,
    TopicReport,
    TrendReport,
    TypeReport,
    ValidationReport,
)
from pyqs.models import format_marks

FORMATS = ("table", "json", "csv", "md")
_FORMAT_ALIASES = {
    "table": "table",
    "text": "table",
    "plain": "table",
    "json": "json",
    "csv": "csv",
    "md": "md",
    "markdown": "md",
}


def is_known_format(value: str) -> bool:
    """Was this a format name the CLI understands?"""

    return value.strip().casefold() in _FORMAT_ALIASES


def resolve_format(value: str) -> str:
    """Normalise a user supplied ``--format`` value."""

    return _FORMAT_ALIASES.get(value.strip().casefold(), "table")


# --------------------------------------------------------------------------- #
# Terminal styling
# --------------------------------------------------------------------------- #


class Glyphs:
    """Table glyphs, with an ASCII fallback for legacy terminal code pages."""

    def __init__(
        self,
        horizontal: str = "\u2500",
        vertical: str = "\u2502",
        top_left: str = "\u250c",
        top_right: str = "\u2510",
        bottom_left: str = "\u2514",
        bottom_right: str = "\u2518",
        tee_down: str = "\u252c",
        tee_up: str = "\u2534",
        tee_right: str = "\u2524",
        tee_left: str = "\u251c",
        full_block: str = "\u2588",
        light_block: str = "\u2591",
        ellipsis: str = "\u2026",
        delta: str = "\u0394",
    ) -> None:
        self.horizontal = horizontal
        self.vertical = vertical
        self.top_left = top_left
        self.top_right = top_right
        self.bottom_left = bottom_left
        self.bottom_right = bottom_right
        self.tee_down = tee_down
        self.tee_up = tee_up
        self.tee_right = tee_right
        self.tee_left = tee_left
        self.full_block = full_block
        self.light_block = light_block
        self.ellipsis = ellipsis
        self.delta = delta


UNICODE_GLYPHS = Glyphs()
ASCII_GLYPHS = Glyphs(
    horizontal="-",
    vertical="|",
    top_left="+",
    top_right="+",
    bottom_left="+",
    bottom_right="+",
    tee_down="+",
    tee_up="+",
    tee_right="+",
    tee_left="+",
    full_block="#",
    light_block=".",
    ellipsis="...",
    delta="chg",
)


def can_encode(text: str, stream: Any = None) -> bool:
    """Can ``text`` be written to ``stream`` without encoding errors?"""

    target = stream if stream is not None else sys.stdout
    encoding = getattr(target, "encoding", None) or "utf-8"
    try:
        text.encode(encoding, errors="strict")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


class Theme:
    """ANSI styling plus glyph selection.

    Colours degrade to plain text when the output is not a terminal, and box
    drawing degrades to ASCII on code pages that cannot represent it (a very
    common Windows console situation).
    """

    CODES: ClassVar[dict[str, str]] = {
        "bold": "1",
        "dim": "2",
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
    }

    def __init__(self, color: bool = False, glyphs: Glyphs | None = None) -> None:
        self.color = color
        self.glyphs = glyphs or UNICODE_GLYPHS

    @property
    def ascii_only(self) -> bool:
        return self.glyphs is ASCII_GLYPHS

    def __call__(self, text: str, *styles: str) -> str:
        if not self.color or not styles:
            return text
        codes = ";".join(self.CODES[style] for style in styles if style in self.CODES)
        if not codes:
            return text
        return f"\033[{codes}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self(text, "bold")

    def dim(self, text: str) -> str:
        return self(text, "dim")


def wants_color(no_color: bool = False, stream: Any = None) -> bool:
    """Colour only for real terminals, unless ``FORCE_COLOR`` says otherwise."""

    if no_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def terminal_width(default: int = 100) -> int:
    try:
        width = shutil.get_terminal_size((default, 24)).columns
    except (OSError, ValueError):
        return default
    return max(40, min(width, 200))


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def num(value: float | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.{digits}f}%"


def signed(value: float, digits: int = 0) -> str:
    if digits:
        return f"{value:+.{digits}f}"
    return f"{int(value):+d}" if float(value).is_integer() else f"{value:+.2f}"


def bar(value: float, maximum: float, width: int = 18, glyphs: Glyphs | None = None) -> str:
    """A block bar, scaled against ``maximum``."""

    glyphs = glyphs or UNICODE_GLYPHS
    if maximum <= 0:
        return ""
    filled = round((value / maximum) * width)
    filled = max(0, min(width, filled))
    return glyphs.full_block * filled + glyphs.light_block * (width - filled)


def truncate(text: str, width: int, ellipsis: str = "\u2026") -> str:
    """Cut ``text`` to ``width`` characters, adding an ellipsis when needed."""

    flat = one_line(text)
    if width <= 0:
        return ""
    if len(flat) <= width:
        return flat
    if width <= len(ellipsis):
        return ellipsis[:width]
    return flat[: width - len(ellipsis)] + ellipsis


def one_line(text: str) -> str:
    """Flatten a multi-line stem into a single line."""

    return " ".join((text or "").split())


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def display_width(text: str) -> int:
    """Width of ``text`` ignoring ANSI escape sequences."""

    length = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\033":
            end = text.find("m", index)
            if end == -1:
                break
            index = end + 1
            continue
        length += 1
        index += 1
    return length


def pad(text: str, width: int, align: str = "left") -> str:
    padding = " " * max(0, width - display_width(text))
    if align == "right":
        return padding + text
    if align == "center":
        left = len(padding) // 2
        return " " * left + text + " " * (len(padding) - left)
    return text + padding


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    aligns: Sequence[str] | None = None,
    theme: Theme | None = None,
) -> str:
    """Render a bordered table."""

    theme = theme or Theme(False)
    glyphs = theme.glyphs
    alignment = list(aligns or ["left"] * len(headers))
    widths = [display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], display_width(str(cell)))

    def rule(left: str, join: str, right: str) -> str:
        return left + join.join(glyphs.horizontal * (width + 2) for width in widths) + right

    def line(cells: list[str]) -> str:
        return glyphs.vertical + " " + f" {glyphs.vertical} ".join(cells) + " " + glyphs.vertical

    out = [rule(glyphs.top_left, glyphs.horizontal, glyphs.top_right)]
    header_cells = [
        theme(pad(header, widths[index], alignment[index]), "bold")
        for index, header in enumerate(headers)
    ]
    out.append(line(header_cells))
    out.append(rule(glyphs.tee_left, glyphs.tee_down, glyphs.tee_right))
    for row in rows:
        cells = [
            pad(str(cell), widths[index], alignment[index])
            for index, cell in enumerate(row)
        ]
        out.append(line(cells))
    out.append(rule(glyphs.bottom_left, glyphs.tee_up, glyphs.bottom_right))
    return "\n".join(out)


def key_values(pairs: Iterable[tuple[str, str]], theme: Theme | None = None) -> str:
    """A two column metric/value block."""

    theme = theme or Theme(False)
    items = list(pairs)
    width = max((len(label) for label, _ in items), default=0)
    return "\n".join(f"  {theme(pad(label, width), 'dim')}  {value}" for label, value in items)


# --------------------------------------------------------------------------- #
# Report renderers (table format)
# --------------------------------------------------------------------------- #


def render_summary(report: Summary, theme: Theme) -> str:
    lines = [theme("Overview", "bold"), ""]
    lines.append(
        key_values(
            [
                ("papers", num(report.papers)),
                ("questions", theme(str(report.questions), "bold")),
                ("total marks", num(report.marks)),
                ("topics", num(report.topics)),
                ("question types", num(report.types)),
                ("years", ", ".join(str(year) for year in report.years) or "-"),
                ("mean marks/question", num(round(report.mean_marks, 2))),
                ("median marks/question", num(round(report.median_marks, 2))),
            ],
            theme,
        )
    )
    if report.paper_rows:
        rows = [
            [
                row["name"],
                str(row["year"] or "-"),
                row["subject"] or "-",
                str(row["total_questions"]),
                format_marks(row["total_marks"]),
                pct(row["share"] / 100),
                str(len(row["warnings"])),
            ]
            for row in report.paper_rows
        ]
        lines.extend(
            [
                "",
                theme("Papers", "bold"),
                render_table(
                    ["paper", "year", "subject", "questions", "marks", "share", "warnings"],
                    rows,
                    ["left", "right", "left", "right", "right", "right", "right"],
                    theme,
                ),
            ]
        )
    if report.warnings:
        lines.extend(["", theme(f"Warnings ({len(report.warnings)})", "yellow")])
        lines.extend(f"  - {warning}" for warning in report.warnings[:20])
        if len(report.warnings) > 20:
            lines.append(theme(f"  ... {len(report.warnings) - 20} more", "dim"))
    return "\n".join(lines)


def render_topics(report: TopicReport, theme: Theme, width: int = 100) -> str:
    if not report.rows:
        return theme("No topics matched.", "yellow")
    maximum = max(row.questions for row in report.rows)
    text_width = max(24, min(46, width - 52))
    rows = [
        [
            truncate(row.topic, text_width, theme.glyphs.ellipsis),
            str(row.questions),
            format_marks(row.marks),
            pct(row.share),
            pct(row.marks_share),
            num(round(row.avg_marks, 2)),
            str(row.papers),
            theme(bar(row.questions, maximum, width=12, glyphs=theme.glyphs), "cyan"),
        ]
        for row in report.rows
    ]
    lines = [
        render_table(
            ["topic", "questions", "marks", "% q", "% marks", "avg", "papers", ""],
            rows,
            ["left", "right", "right", "right", "right", "right", "right", "left"],
            theme,
        )
    ]
    lines.append(
        theme.dim(
            f"  {report.total_questions} questions, {format_marks(report.total_marks)} marks, "
            f"{len(report.rows)} topics"
        )
    )
    if report.filters:
        lines.append(theme.dim(f"  filter: {report.filters}"))
    return "\n".join(lines)


def render_types(report: TypeReport, theme: Theme) -> str:
    rows = [
        [
            row.label,
            str(row.questions),
            format_marks(row.marks),
            pct(row.share),
            pct(row.marks_share),
            num(round(row.avg_marks, 2)),
            str(row.topics),
            str(row.papers),
        ]
        for row in report.rows
    ]
    table = render_table(
        ["type", "questions", "marks", "% q", "% marks", "avg", "topics", "papers"],
        rows,
        ["left", "right", "right", "right", "right", "right", "right", "right"],
        theme,
    )
    footer = theme.dim(
        f"  {report.total_questions} questions, {format_marks(report.total_marks)} marks"
    )
    if report.filters:
        footer += theme.dim(f"  |  filter: {report.filters}")
    return f"{table}\n{footer}"


def render_marks(report: MarksReport, theme: Theme) -> str:
    maximum = max((bucket.questions for bucket in report.buckets), default=0)
    rows = [
        [
            format_marks(bucket.marks),
            str(bucket.questions),
            pct(bucket.share),
            pct(bucket.cumulative_share),
            theme(bar(bucket.questions, maximum, width=20, glyphs=theme.glyphs), "magenta"),
        ]
        for bucket in report.buckets
    ]
    lines = [
        key_values(
            [
                ("questions", str(report.total_questions)),
                ("total marks", format_marks(report.total_marks)),
                ("mean marks", num(round(report.mean_marks, 2))),
                ("median marks", num(round(report.median_marks, 2))),
                ("range", f"{format_marks(report.min_marks)} - {format_marks(report.max_marks)}"),
                ("marks from parts", format_marks(report.inferred_marks)),
                ("questions without marks", str(report.missing_marks)),
            ],
            theme,
        ),
        "",
        theme("Marks histogram", "bold"),
        render_table(
            ["marks", "questions", "% q", "cumulative", ""],
            rows,
            ["right", "right", "right", "right", "left"],
            theme,
        ),
        "",
        theme("Marks by type", "bold"),
        render_table(
            ["type", "questions", "marks", "% marks", "avg"],
            [
                [
                    row.label,
                    str(row.questions),
                    format_marks(row.marks),
                    pct(row.marks_share),
                    num(round(row.avg_marks, 2)),
                ]
                for row in report.by_type
            ],
            ["left", "right", "right", "right", "right"],
            theme,
        ),
    ]
    if report.filters:
        lines.append(theme.dim(f"  filter: {report.filters}"))
    return "\n".join(lines)


def render_concepts(report: ConceptReport, theme: Theme) -> str:
    if not report.rows:
        return theme("No concepts matched.", "yellow")
    maximum = max(row.questions for row in report.rows)
    rows = [
        [
            truncate(row.concept, 40, theme.glyphs.ellipsis),
            str(row.questions),
            pct(row.share),
            str(row.papers),
            ", ".join(str(year) for year in row.years) or "-",
            ", ".join(f"{key}:{value}" for key, value in sorted(row.sources.items())),
            theme(bar(row.questions, maximum, width=12, glyphs=theme.glyphs), "green"),
        ]
        for row in report.rows
    ]
    lines = [
        render_table(
            ["concept", "questions", "% q", "papers", "years", "sources", ""],
            rows,
            ["left", "right", "right", "right", "right", "left", "left"],
            theme,
        ),
        theme.dim(
            f"  {len(report.rows)} concepts from {', '.join(report.sources)} sources "
            f"over {report.total_questions} questions"
        ),
    ]
    if report.filters:
        lines.append(theme.dim(f"  filter: {report.filters}"))
    return "\n".join(lines)


def render_questions(report: QuestionListReport, theme: Theme, width: int = 100) -> str:
    rows = [
        [
            row.id,
            str(row.year or "-"),
            row.type,
            format_marks(row.marks),
            str(row.parts),
            truncate(row.topic, 20, theme.glyphs.ellipsis),
            truncate(one_line(row.text), max(20, min(60, width - 60)), theme.glyphs.ellipsis),
        ]
        for row in report.rows
    ]
    lines = [
        render_table(
            ["id", "year", "type", "marks", "parts", "topic", "question"],
            rows,
            ["left", "right", "left", "right", "right", "left", "left"],
            theme,
        ),
        theme.dim(
            f"  {len(report.rows)} of {report.total_questions} questions, "
            f"{format_marks(report.total_marks)} marks"
        ),
    ]
    if report.filters:
        lines.append(theme.dim(f"  filter: {report.filters}"))
    return "\n".join(lines)


def render_comparison(report: ComparisonReport, theme: Theme, width: int = 100) -> str:
    header = key_values(
        [
            ("baseline", report.baseline_label),
            ("variant", report.variant_label),
            (
                "questions",
                f"{report.baseline.questions} -> {report.variant.questions} "
                f"({_delta_text(report.question_delta)})",
            ),
            (
                "marks",
                f"{format_marks(report.baseline.marks)} -> {format_marks(report.variant.marks)} "
                f"({_delta_text(report.marks_delta)})",
            ),
        ],
        theme,
    )
    text_width = max(20, min(40, width - 56))
    status_styles = {
        "up": "green",
        "down": "red",
        "new": "cyan",
        "dropped": "yellow",
        "flat": "dim",
    }
    delta = theme.glyphs.delta
    rows = [
        [
            truncate(row.topic, text_width, theme.glyphs.ellipsis),
            str(row.baseline_questions),
            str(row.variant_questions),
            theme(_delta_text(row.question_delta), status_styles[row.status]),
            format_marks(row.baseline_marks),
            format_marks(row.variant_marks),
            _delta_text(row.marks_delta),
            theme(row.status, status_styles[row.status]),
        ]
        for row in report.rows
    ]
    lines = [
        theme("Comparison", "bold"),
        header,
        "",
        render_table(
            [
                "topic",
                "base",
                "new",
                f"{delta} q",
                "base marks",
                "new marks",
                f"{delta} marks",
                "status",
            ],
            rows,
            ["left", "right", "right", "right", "right", "right", "right", "left"],
            theme,
        ),
    ]
    if report.added_topics:
        lines.append(theme(f"  new topics: {', '.join(report.added_topics)}", "cyan"))
    if report.removed_topics:
        lines.append(theme(f"  dropped topics: {', '.join(report.removed_topics)}", "yellow"))
    return "\n".join(lines)


def _delta_text(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):+d}"
    return f"{value:+.1f}"


def render_trend(report: TrendReport, theme: Theme) -> str:
    topic_names = [change["topic"] for change in report.changes]
    label_width = max(
        [len(truncate(name, 28, theme.glyphs.ellipsis)) for name in topic_names], default=10
    )
    max(4, max((len(str(year)) for year in report.years), default=4))
    cell_width = 7
    header = " " * (label_width + 2) + "".join(
        pad(str(year), cell_width, "right") for year in report.years
    )
    lines = [
        theme("Per-year totals", "bold"),
        render_table(
            ["year", "questions", "marks", "topics", "papers"],
            [
                [
                    str(row["year"]),
                    str(row["questions"]),
                    format_marks(row["marks"]),
                    str(row["topics"]),
                    str(row["papers"]),
                ]
                for row in report.per_year
            ],
            ["right", "right", "right", "right", "right"],
            theme,
        ),
        "",
        theme(f"Topic counts by year (columns are {report.years[0]}-{report.years[-1]})", "bold"),
        theme.dim(header.rstrip()),
    ]
    for change in report.changes:
        cells = ""
        for count in change["series"]:
            text = str(count)
            style = "bold" if count == max(change["series"]) and count else ""
            cells += pad(theme(text, style) if style else text, cell_width, "right")
        delta = change["delta"]
        style = "green" if delta > 0 else ("red" if delta < 0 else "dim")
        label = pad(truncate(change["topic"], label_width, theme.glyphs.ellipsis), label_width)
        lines.append(f"  {label}  {cells}  {theme(_delta_text(delta), style)}")
    if report.filters:
        lines.append(theme.dim(f"  filter: {report.filters}"))
    return "\n".join(lines)


def render_validation(report: ValidationReport, theme: Theme) -> str:
    rows = [
        [
            truncate(item.path, 44, theme.glyphs.ellipsis),
            theme("ok", "green") if item.ok else theme("failed", "red"),
            str(item.papers),
            str(item.questions),
            format_marks(item.marks),
            str(len(item.warnings)),
            truncate(item.error or "", 40, theme.glyphs.ellipsis) if item.error else "",
        ]
        for item in report.files
    ]
    lines = [
        render_table(
            ["file", "status", "papers", "questions", "marks", "warnings", "error"],
            rows,
            ["left", "left", "right", "right", "right", "right", "left"],
            theme,
        )
    ]
    for item in report.files:
        for warning in item.warnings:
            lines.append(theme(f"  warning  {item.path}: {warning}", "yellow"))
    failed = len(report.failures)
    verdict = f"{failed} file(s) failed" if failed else "all files parsed"
    style = "green" if not failed else "red"
    lines.append(theme(f"  {verdict}, {report.warning_count} warning(s)", style))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Format dispatch
# --------------------------------------------------------------------------- #


def to_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def to_csv(rows: Sequence[dict[str, Any]]) -> str:
    if not rows:
        return ""
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return buffer.getvalue().rstrip("\n")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value


def to_markdown(rows: Sequence[dict[str, Any]], title: str = "") -> str:
    if not rows:
        return f"# {title}\n\n_No rows._" if title else "_No rows._"
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    lines: list[str] = []
    if title:
        lines.extend([f"# {title}", ""])
    lines.append("| " + " | ".join(_md_escape(key) for key in fieldnames) + " |")
    lines.append("| " + " | ".join("---" for _ in fieldnames) + " |")
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_md_escape(_md_value(row.get(key))) for key in fieldnames)
            + " |"
        )
    return "\n".join(lines)


def _md_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.2f}"
    return str(value)


def emit(
    report: Any,
    fmt: str,
    text_renderer: Callable[[Theme], str],
    theme: Theme,
    title: str = "",
    stream: Any = None,
) -> None:
    """Write ``report`` to ``stream`` in the requested format."""

    target = stream if stream is not None else sys.stdout
    resolved = resolve_format(fmt)
    if resolved == "table":
        text = text_renderer(theme)
        if text:
            print(text, file=target)
        return
    if resolved == "json":
        print(to_json(report.to_dict()), file=target)
        return
    rows = report.to_rows()
    text = to_csv(rows) if resolved == "csv" else to_markdown(rows, title)
    if text:
        print(text, file=target)
