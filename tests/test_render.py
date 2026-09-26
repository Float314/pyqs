"""Rendering: tables, colour, ASCII fallback and the machine formats."""

from __future__ import annotations

import csv
import io
import json

from pyqs import analysis, render
from pyqs.analysis import Filters
from pyqs.render import ASCII_GLYPHS, UNICODE_GLYPHS, Theme


def render_to_string(report, renderer, fmt: str = "table") -> str:
    buffer = io.StringIO()
    render.emit(report, fmt, renderer, Theme(False), title="t", stream=buffer)
    return buffer.getvalue().rstrip("\n")


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #


def test_theme_is_plain_without_colour():
    theme = Theme(False)
    assert theme("x", "bold", "red") == "x"
    assert theme.bold("x") == "x"
    assert theme.dim("x") == "x"


def test_theme_wraps_with_ansi_when_enabled():
    theme = Theme(True)
    assert theme("x", "red") == "\033[31mx\033[0m"
    assert theme("x", "bold", "dim") == "\033[1;2mx\033[0m"
    assert theme("x", "not-a-style") == "x"


def test_resolve_format():
    assert render.resolve_format("table") == "table"
    assert render.resolve_format(" JSON ") == "json"
    assert render.resolve_format("markdown") == "md"
    assert render.resolve_format("md") == "md"
    assert render.resolve_format("csv") == "csv"
    assert render.resolve_format("nonsense") == "table"
    assert render.FORMATS == ("table", "json", "csv", "md")


def test_render_table_alignment_and_borders():
    text = render.render_table(["a", "bb"], [["1", "2"]], ["right", "left"])
    lines = text.splitlines()
    assert lines[0].startswith(UNICODE_GLYPHS.top_left)
    assert lines[0].endswith(UNICODE_GLYPHS.top_right)
    assert lines[-1].endswith(UNICODE_GLYPHS.bottom_right)
    assert len(lines) == 5
    assert render.display_width(lines[0]) == render.display_width(lines[1])


def test_render_table_ignores_ansi_in_widths():
    text = render.render_table(["x"], [[Theme(True)("abc", "red")]])
    assert len({render.display_width(line) for line in text.splitlines()}) == 1


def test_ascii_glyph_fallback():
    text = render.render_table(["a"], [["1"]], theme=Theme(False, ASCII_GLYPHS))
    assert text.splitlines()[0] == "+---+"
    assert "+" in text and "\u2500" not in text
    assert Theme(False, ASCII_GLYPHS).ascii_only is True


def test_can_encode(tmp_path):
    target = tmp_path / "out.txt"
    with open(target, "w", encoding="utf-8") as handle:
        assert render.can_encode("\u2500", handle) is True
    with open(target, "w", encoding="cp1252") as handle:
        assert render.can_encode("\u2500", handle) is False
        assert render.can_encode("-", handle) is True


def test_wants_color(monkeypatch):
    class FakeTTY:
        encoding = "utf-8"

        def isatty(self):
            return True

    class FakePipe:
        encoding = "utf-8"

        def isatty(self):
            return False

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert render.wants_color(False, FakeTTY()) is True
    assert render.wants_color(True, FakeTTY()) is False
    assert render.wants_color(False, FakePipe()) is False
    monkeypatch.setenv("NO_COLOR", "1")
    assert render.wants_color(False, FakeTTY()) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert render.wants_color(False, FakePipe()) is True


def test_truncate_and_one_line():
    assert render.one_line("a\n  b\tc") == "a b c"
    assert render.truncate("abcdef", 4) == "abc\u2026"
    assert render.truncate("abc", 10) == "abc"
    assert render.truncate("abcdef", 0) == ""
    assert render.truncate("abcdef", 1) == "\u2026"
    assert render.truncate("abcdef", 6, "...") == "abcdef"


def test_bar_scales_and_handles_zero():
    assert render.bar(0, 0) == ""
    assert render.bar(5, 10, width=10) == "\u2588" * 5 + "\u2591" * 5
    assert render.bar(20, 10, width=4) == "\u2588" * 4
    assert render.bar(1, 2, width=4, glyphs=ASCII_GLYPHS) == "##.."


def test_num_and_pct():
    assert render.num(None) == "-"
    assert render.num(3) == "3"
    assert render.num(3.0) == "3"
    assert render.num(3.5) == "3.5"
    assert render.pct(0.5) == "50.0%"
    assert render.pct(None) == "-"
    assert render.signed(2) == "+2"
    assert render.signed(-2.5, digits=1) == "-2.5"


def test_terminal_width_is_sane():
    assert 40 <= render.terminal_width() <= 200


# --------------------------------------------------------------------------- #
# machine readable formats
# --------------------------------------------------------------------------- #


def test_to_csv_quotes_and_orders(papers):
    rows = analysis.question_rows(papers).to_rows()
    text = render.to_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert parsed[0]["id"] == "Q1"
    assert "concepts" in parsed[0]
    assert render.to_csv([]) == ""


def test_to_csv_serialises_nested_values():
    rows = list(csv.DictReader(io.StringIO(render.to_csv([{"a": {"b": 1}, "c": [1, 2]}]))))
    assert rows == [{"a": '{"b": 1}', "c": "[1, 2]"}]


def test_to_markdown_escapes_pipes():
    text = render.to_markdown([{"topic": "Vectors | 3-D"}], title="pyqs topics")
    lines = text.splitlines()
    assert lines[0] == "# pyqs topics"
    assert lines[2] == "| topic |"
    assert lines[3] == "| --- |"
    assert lines[4] == "| Vectors \\| 3-D |"
    assert render.to_markdown([]) == "_No rows._"
    assert render.to_markdown([], title="t") == "# t\n\n_No rows._"


def test_to_json_is_valid(papers):
    payload = json.loads(render.to_json(analysis.summarise(papers).to_dict()))
    assert payload["questions"] == 2


# --------------------------------------------------------------------------- #
# report rendering
# --------------------------------------------------------------------------- #


def test_render_summary(papers):
    text = render.render_summary(analysis.summarise(papers), Theme(False))
    assert "Overview" in text
    assert "questions" in text
    assert "Papers" in text


def test_render_summary_lists_warnings():
    from pyqs.parser import parse_paper_string

    paper = parse_paper_string(
        '<pyqs year="2024"><question_body type="mcq" marks="1" topic="x"><question>q</question></question_body></pyqs>'
    )
    text = render.render_summary(analysis.summarise(paper), Theme(False))
    assert "Warnings (2)" in text
    assert "without an id" in text


def test_render_topics_types_marks_concepts(papers, example_file):
    theme = Theme(False)
    assert "topic" in render.render_topics(analysis.topic_stats(papers), theme)
    assert "MCQ" in render.render_types(analysis.type_stats(papers), theme)
    assert "Marks histogram" in render.render_marks(analysis.marks_distribution(papers), theme)
    concepts = render.render_concepts(analysis.concept_stats(papers), theme)
    assert "concept" in concepts


def test_render_empty_topics_message():
    from pyqs.analysis import TopicReport

    empty = TopicReport(rows=[], total_questions=0, total_marks=0.0, papers=1)
    assert "No topics matched" in render.render_topics(empty, Theme(False))
    from pyqs.analysis import ConceptReport

    empty_concepts = ConceptReport(rows=[], total_questions=0, papers=1, sources=[])
    assert "No concepts matched" in render.render_concepts(empty_concepts, Theme(False))


def test_render_questions_and_full_mode(papers):
    text = render.render_questions(analysis.question_rows(papers), Theme(False), width=100)
    assert "2 of 2 questions" in text
    assert "Q1" in text


def test_render_comparison(two_year_bank):
    baseline, variant = two_year_bank
    report = analysis.compare([baseline], [variant])
    text = render.render_comparison(report, Theme(False, ASCII_GLYPHS))
    assert "Comparison" in text
    assert "new topics" in text
    assert "chg q" in text  # ASCII delta header


def test_render_trend(two_year_bank):
    text = render.render_trend(analysis.trend(two_year_bank), Theme(False))
    assert "Per-year totals" in text
    assert "Topic counts by year" in text
    assert "Limits" in text


def test_render_validation(tmp_path, example_file):
    from pathlib import Path

    report = analysis.validate_files([Path(example_file)])
    text = render.render_validation(report, Theme(False))
    assert "all files parsed" in text

    bad = tmp_path / "bad.xml"
    bad.write_text("<pyqs>", encoding="utf-8")
    failed = render.render_validation(analysis.validate_files([bad]), Theme(False))
    assert "1 file(s) failed" in failed
    assert "failed" in failed


def test_emit_dispatches_on_format(papers):
    report = analysis.summarise(papers)
    assert render_to_string(report, lambda theme: "TABLE") == "TABLE"
    assert json.loads(render_to_string(report, lambda theme: "", "json"))["questions"] == 2
    assert "papers" in render_to_string(report, lambda theme: "", "csv")
    assert render_to_string(report, lambda theme: "", "md").startswith("# t")


def test_emit_skips_empty_text(papers):
    buffer = io.StringIO()
    render.emit(analysis.summarise(papers), "table", lambda theme: "", Theme(False), stream=buffer)
    assert buffer.getvalue() == ""


def test_filter_description_is_rendered(papers):
    report = analysis.topic_stats(papers, filters=Filters(types=("mcq",)))
    assert "filter:" in render.render_topics(report, Theme(False))
