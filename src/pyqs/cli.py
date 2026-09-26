"""Command line interface for pyqs.

Exit codes
----------
0   success
1   unexpected internal error
2   usage error (argparse)
3   bad input: missing file, unparsable XML
4   the inputs parsed but nothing matched the filters
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pyqs import analysis, render
from pyqs.analysis import Filters
from pyqs.concepts import SOURCES as CONCEPT_SOURCES
from pyqs.errors import InputError, NoDataError, PyqsError
from pyqs.models import Paper
from pyqs.parser import normalise_type, parse_paper
from pyqs.version import __version__

PROGRAM = "pyqs"
GLOB_MAGIC = "*?["
XML_SUFFIXES = (".xml",)


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def _format_argument(value: str) -> str:
    """argparse type for ``--format``: reject anything unknown with exit code 2."""

    resolved = render.resolve_format(value)
    if not render.is_known_format(value):
        raise argparse.ArgumentTypeError(
            f"unknown format {value!r}; choose from {', '.join(render.FORMATS)}"
        )
    return resolved


def _common_parser() -> argparse.ArgumentParser:
    """Options shared by every sub-command."""

    parser = argparse.ArgumentParser(add_help=False)
    output = parser.add_argument_group("output")
    output.add_argument(
        "-f",
        "--format",
        type=_format_argument,
        default="table",
        metavar="{table,json,csv,md}",
        help="output format (default: table)",
    )
    output.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    output.add_argument(
        "--width",
        type=int,
        default=None,
        metavar="N",
        help="assume a terminal width of N columns (default: detect)",
    )

    selection = parser.add_argument_group("selection")
    selection.add_argument(
        "-t",
        "--topic",
        action="append",
        default=[],
        metavar="NAME",
        help="only questions with this topic (repeatable)",
    )
    selection.add_argument(
        "--type",
        action="append",
        default=[],
        metavar="TYPE",
        help="only questions of this type, e.g. mcq, numerical, short_answer (repeatable)",
    )
    selection.add_argument(
        "--year",
        action="append",
        type=int,
        default=[],
        metavar="YEAR",
        help="only questions from this year (repeatable)",
    )
    selection.add_argument(
        "--min-marks", type=float, default=None, metavar="N", help="minimum marks per question"
    )
    selection.add_argument(
        "--max-marks", type=float, default=None, metavar="N", help="maximum marks per question"
    )
    selection.add_argument(
        "--grep", metavar="TEXT", help="only questions whose text contains TEXT"
    )
    selection.add_argument(
        "--id", action="append", default=[], metavar="ID", help="only this question id (repeatable)"
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Statistics and analysis for XML/LaTeX previous-year question banks. "
            "Every command accepts one or more question bank files, directories or globs."
        ),
        epilog=(
            "exit codes: 0 success, 2 usage error, 3 bad input, 4 nothing matched the filters"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"{PROGRAM} {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    summary = subparsers.add_parser(
        "summary",
        parents=[common],
        help="overall counts, marks and papers",
        description="Overall counts, marks and papers.",
    )
    _add_files(summary, "XML question bank file(s) to analyse")

    topics = subparsers.add_parser(
        "topics", parents=[common], help="question and mark distribution per topic"
    )
    _add_files(topics, "XML question bank file(s) to analyse")
    topics.add_argument(
        "-s",
        "--sort",
        default="questions",
        choices=("questions", "marks", "avg", "share", "name"),
        help="sort order for the table (default: questions)",
    )
    topics.add_argument(
        "-l", "--limit", type=int, default=None, help="keep only the first N topics"
    )
    topics.add_argument(
        "--min-questions",
        type=int,
        default=1,
        metavar="N",
        help="skip topics with fewer than N questions",
    )

    types = subparsers.add_parser(
        "types", parents=[common], help="MCQ / numerical / short answer mix"
    )
    _add_files(types, "XML question bank file(s) to analyse")

    marks = subparsers.add_parser(
        "marks", parents=[common], help="marks distribution and histogram"
    )
    _add_files(marks, "XML question bank file(s) to analyse")

    concepts = subparsers.add_parser(
        "concepts", parents=[common], help="concept frequency across papers"
    )
    _add_files(concepts, "XML question bank file(s) to analyse")
    concepts.add_argument(
        "--source",
        action="append",
        choices=list(CONCEPT_SOURCES),
        default=[],
        metavar="{tag,keyword,latex}",
        help="concept source to use (repeatable, default: all)",
    )
    concepts.add_argument(
        "-s",
        "--sort",
        default="questions",
        choices=("questions", "papers", "name"),
        help="sort order",
    )
    concepts.add_argument(
        "-l", "--limit", type=int, default=None, help="keep only the top N concepts"
    )
    concepts.add_argument(
        "--min-questions", type=int, default=1, metavar="N", help="minimum questions"
    )
    concepts.add_argument(
        "--min-papers",
        type=int,
        default=1,
        metavar="N",
        help="only concepts seen in N or more papers",
    )

    listing = subparsers.add_parser(
        "list", parents=[common], help="list individual questions"
    )
    _add_files(listing, "XML question bank file(s) to list")
    listing.add_argument(
        "-s",
        "--sort",
        default="paper",
        choices=("paper", "id", "type", "topic", "marks"),
        help="sort order (default: paper)",
    )
    listing.add_argument(
        "-l", "--limit", type=int, default=None, help="keep only the first N questions"
    )
    listing.add_argument(
        "--full", action="store_true", help="do not truncate the question text column"
    )

    compare = subparsers.add_parser(
        "compare", parents=[common], help="compare two sets of papers topic by topic"
    )
    compare.add_argument(
        "baseline", nargs="*", default=[], metavar="BASELINE", help="baseline XML file(s)"
    )
    compare.add_argument(
        "-a",
        "--against",
        nargs="+",
        required=True,
        metavar="FILE",
        help="variant XML file(s) to compare against the baseline",
    )

    trend = subparsers.add_parser("trend", parents=[common], help="year-on-year topic movement")
    _add_files(trend, "XML question bank file(s) to analyse")
    trend.add_argument(
        "-l", "--limit", type=int, default=None, help="keep only the N most frequent topics"
    )

    export = subparsers.add_parser(
        "export", parents=[common], help="export parsed questions as json, csv or markdown"
    )
    _add_files(export, "XML question bank file(s) to export")
    export.add_argument(
        "-o", "--output", default=None, metavar="PATH", help="write to PATH instead of stdout"
    )

    validate = subparsers.add_parser(
        "validate", parents=[common], help="check that question banks parse cleanly"
    )
    _add_files(validate, "XML question bank file(s) to validate")
    validate.add_argument(
        "--strict", action="store_true", help="exit non-zero when a file has warnings"
    )

    return parser


def _add_files(parser: argparse.ArgumentParser, help_text: str) -> None:
    parser.add_argument(
        "files", nargs="+", help=help_text + " (directories are searched for *.xml)"
    )


# --------------------------------------------------------------------------- #
# Input handling
# --------------------------------------------------------------------------- #


def expand_inputs(patterns: Sequence[str], suffixes: Sequence[str] = XML_SUFFIXES) -> list[Path]:
    """Turn CLI arguments into a sorted, de-duplicated list of files.

    Accepts explicit paths, glob patterns (handy on Windows, where the shell does
    not expand them) and directories, which are searched one level deep.
    """

    resolved: list[Path] = []
    seen = set()
    missing: list[str] = []
    for pattern in patterns:
        path = Path(pattern)
        if path.is_dir():
            candidates = sorted(
                child
                for child in path.iterdir()
                if child.is_file() and child.suffix.casefold() in suffixes
            )
            if not candidates:
                missing.append(f"{pattern} (directory has no {'/'.join(suffixes)} files)")
                continue
        elif any(char in pattern for char in GLOB_MAGIC):
            matches = sorted(Path(match) for match in glob.glob(pattern, recursive=True))
            candidates = [match for match in matches if match.is_file()]
            if not candidates:
                missing.append(f"{pattern} (pattern matched nothing)")
                continue
        elif path.is_file():
            candidates = [path]
        else:
            missing.append(pattern)
            continue
        for candidate in candidates:
            resolved_path = candidate.resolve()
            if resolved_path not in seen:
                seen.add(resolved_path)
                resolved.append(candidate)
    if missing:
        raise InputError("cannot read: " + ", ".join(missing))
    if not resolved:
        raise InputError("no question bank files were given")
    return resolved


def _filters_from(args: argparse.Namespace) -> Filters:
    topics = tuple(value.strip().casefold() for value in args.topic if value.strip())
    types = tuple(normalise_type(value) for value in args.type if value.strip())
    ids = tuple(value.strip().casefold() for value in args.id if value.strip())
    return Filters(
        topics=topics,
        types=types,
        years=tuple(args.year),
        min_marks=args.min_marks,
        max_marks=args.max_marks,
        grep=args.grep,
        ids=ids,
    )


def _load_papers(patterns: Sequence[str]) -> tuple[list[Paper], list[Path]]:
    paths = expand_inputs(patterns)
    papers: list[Paper] = []
    for path in paths:
        papers.extend(parse_paper(path))
    return papers, paths


def _theme(args: argparse.Namespace, stream=None) -> render.Theme:
    """Pick colours and glyphs based on where the output is going."""

    target = stream if stream is not None else sys.stdout
    probe = render.UNICODE_GLYPHS.horizontal + render.UNICODE_GLYPHS.full_block
    glyphs = render.UNICODE_GLYPHS if render.can_encode(probe, target) else render.ASCII_GLYPHS
    return render.Theme(render.wants_color(args.no_color, target), glyphs)


def _width(args: argparse.Namespace) -> int:
    return args.width if args.width else render.terminal_width()


def _note_warnings(papers: Sequence[Paper], args: argparse.Namespace) -> None:
    count = sum(len(paper.warnings) for paper in papers)
    if count:
        first = next(warning for paper in papers for warning in paper.warnings)
        print(
            render.Theme(False).dim(
                f"note: {count} parse warning(s), e.g. {first}  "
                f"(run '{PROGRAM} validate <file>' for the full list)"
            ),
            file=sys.stderr,
        )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_summary(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.summarise(papers, analysis.select_questions(papers, _filters_from(args)))
    render.emit(
        report,
        args.format,
        lambda theme: render.render_summary(report, theme),
        _theme(args),
        title="pyqs summary",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_topics(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.topic_stats(
        papers,
        filters=_filters_from(args),
        sort=args.sort,
        limit=args.limit,
        min_questions=args.min_questions,
    )
    render.emit(
        report,
        args.format,
        lambda theme: render.render_topics(report, theme, _width(args)),
        _theme(args),
        title="pyqs topics",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_types(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.type_stats(papers, filters=_filters_from(args))
    render.emit(
        report,
        args.format,
        lambda theme: render.render_types(report, theme),
        _theme(args),
        title="pyqs types",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_marks(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.marks_distribution(papers, filters=_filters_from(args))
    render.emit(
        report,
        args.format,
        lambda theme: render.render_marks(report, theme),
        _theme(args),
        title="pyqs marks",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_concepts(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.concept_stats(
        papers,
        filters=_filters_from(args),
        sources=args.source or None,
        sort=args.sort,
        limit=args.limit,
        min_questions=args.min_questions,
        min_papers=args.min_papers,
    )
    render.emit(
        report,
        args.format,
        lambda theme: render.render_concepts(report, theme),
        _theme(args),
        title="pyqs concepts",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_list(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.question_rows(
        papers, filters=_filters_from(args), sort=args.sort, limit=args.limit
    )
    width = _width(args)

    def renderer(theme: render.Theme) -> str:
        if args.full:
            rows = [
                [
                    row.id,
                    str(row.year or "-"),
                    row.type,
                    render.format_marks(row.marks),
                    str(row.parts),
                    row.topic,
                    ", ".join(row.concepts),
                ]
                for row in report.rows
            ]
            return render.render_table(
                ["id", "year", "type", "marks", "parts", "topic", "concepts"],
                rows,
                ["left", "right", "left", "right", "right", "left", "left"],
                theme,
            )
        return render.render_questions(report, theme, width)

    render.emit(
        report,
        args.format,
        renderer,
        _theme(args),
        title="pyqs list",
        stream=stream,
    )
    _note_warnings(papers, args)
    return 0


def cmd_compare(args: argparse.Namespace, stream) -> int:
    baseline_papers, _ = _load_papers(args.baseline)
    variant_papers, _ = _load_papers(args.against)
    report = analysis.compare(baseline_papers, variant_papers)
    render.emit(
        report,
        args.format,
        lambda theme: render.render_comparison(report, theme, _width(args)),
        _theme(args),
        title="pyqs compare",
        stream=stream,
    )
    return 0


def cmd_trend(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    report = analysis.trend(papers, filters=_filters_from(args), limit=args.limit)
    render.emit(
        report,
        args.format,
        lambda theme: render.render_trend(report, theme),
        _theme(args),
        title="pyqs trend",
        stream=stream,
    )
    return 0


def cmd_export(args: argparse.Namespace, stream) -> int:
    papers, _ = _load_papers(args.files)
    filters = _filters_from(args)
    questions = analysis.select_questions(papers, filters)
    if not questions:
        raise NoDataError("no questions matched the given inputs and filters")
    fmt = render.resolve_format(args.format)
    if fmt == "table":
        fmt = "json"
    listing = analysis.question_rows(papers, filters=filters, sort="paper")
    payload = {
        "generator": f"{PROGRAM} {__version__}",
        "papers": [paper.to_dict() for paper in papers],
        "summary": analysis.summarise(papers, questions).to_dict(),
        "questions": [question.to_dict() for question in questions],
    }
    if fmt == "csv":
        text = render.to_csv(listing.to_rows())
    elif fmt == "md":
        text = render.to_markdown(listing.to_rows(), title="pyqs questions")
    else:
        text = render.to_json(payload)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text, file=stream)
    return 0


def cmd_validate(args: argparse.Namespace, stream) -> int:
    paths = expand_inputs(args.files)
    report = analysis.validate_files(paths, filters=_filters_from(args))
    render.emit(
        report,
        args.format,
        lambda theme: render.render_validation(report, theme),
        _theme(args),
        title="pyqs validate",
        stream=stream,
    )
    if report.failures:
        return 3
    if args.strict and report.warning_count:
        print(
            render.Theme(False).dim(
                f"strict mode: {report.warning_count} warning(s) treated as failure"
            ),
            file=sys.stderr,
        )
        return 3
    return 0


COMMANDS = {
    "summary": cmd_summary,
    "topics": cmd_topics,
    "types": cmd_types,
    "marks": cmd_marks,
    "concepts": cmd_concepts,
    "list": cmd_list,
    "compare": cmd_compare,
    "trend": cmd_trend,
    "export": cmd_export,
    "validate": cmd_validate,
}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def _relax_output_encoding() -> None:
    """Never die on a character the console code page cannot represent."""

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(errors="replace")  # pragma: no cover - platform dependent


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _relax_output_encoding()
    handler = COMMANDS[args.command]
    try:
        return handler(args, sys.stdout)
    except PyqsError as exc:
        print(f"{PROGRAM}: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print(f"{PROGRAM}: interrupted", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"{PROGRAM}: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
