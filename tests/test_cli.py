"""End-to-end tests: the command line, its output and its exit codes."""

from __future__ import annotations

import csv
import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from pyqs.cli import build_parser, expand_inputs, main
from pyqs.errors import InputError
from pyqs.version import __version__

pytestmark = pytest.mark.cli


def run(*argv: str) -> tuple:
    """Run the CLI, capturing stdout/stderr and the exit code."""

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as exit_error:  # argparse usage errors
            code = int(exit_error.code or 0)
    return code, out.getvalue(), err.getvalue()


def run_json(*argv: str) -> dict:
    code, out, _ = run(*argv, "--format", "json", "--no-color")
    assert code == 0, out
    return json.loads(out)


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #


def test_version():
    code, out, _ = run("--version")
    assert code == 0
    assert __version__ in out


def test_help_lists_every_command():
    code, out, _ = run("--help")
    assert code == 0
    for command in (
        "summary",
        "topics",
        "types",
        "marks",
        "concepts",
        "list",
        "compare",
        "trend",
        "export",
        "validate",
    ):
        assert command in out


def test_missing_command_is_a_usage_error():
    code, _, _ = run()
    assert code == 2


def test_bad_format_choice_is_rejected():
    code, _, _ = run("summary", "examples", "--format", "nope")
    assert code == 2


def test_parser_exposes_every_command():
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert actions
    assert set(parser._subparsers._group_actions[0].choices) == {
        "summary",
        "topics",
        "types",
        "marks",
        "concepts",
        "list",
        "compare",
        "trend",
        "export",
        "validate",
    }


def test_expand_inputs_handles_dirs_globs_and_files(examples_dir):
    everything = expand_inputs([str(examples_dir)])
    assert len(everything) == 7
    assert all(path.suffix == ".xml" for path in everything)

    globbed = expand_inputs([str(examples_dir / "jee_main_*.xml")])
    assert [path.name for path in globbed] == ["jee_main_2023.xml", "jee_main_2024.xml"]

    single = expand_inputs([str(examples_dir / "example1.xml")])
    assert len(single) == 1

    duplicated = expand_inputs([str(examples_dir / "example1.xml")] * 2)
    assert len(duplicated) == 1


def test_expand_inputs_reports_missing(tmp_path):
    with pytest.raises(InputError):
        expand_inputs([str(tmp_path / "nope.xml")])
    with pytest.raises(InputError):
        expand_inputs([str(tmp_path / "missing_*.xml")])
    with pytest.raises(InputError):
        expand_inputs([str(tmp_path)])
    with pytest.raises(InputError):
        expand_inputs([])


# --------------------------------------------------------------------------- #
# report commands
# --------------------------------------------------------------------------- #


def test_summary_command(examples_dir):
    payload = run_json("summary", str(examples_dir))
    assert payload["questions"] == 64
    assert payload["papers"] == 8
    assert payload["marks"] == 163.0
    assert payload["years"] == [2022, 2023, 2024, 2025]


def test_summary_of_single_file(example_file):
    payload = run_json("summary", str(example_file))
    assert payload["questions"] == 8
    assert payload["marks"] == 16.0


def test_topics_command(example_file):
    payload = run_json("topics", str(example_file))
    topics = {row["topic"]: row for row in payload["topics"]}
    assert topics["Calculus"]["questions"] == 2
    assert payload["total_questions"] == 8
    limited = run_json("topics", str(example_file), "--limit", "2")
    assert len(limited["topics"]) == 2
    assert limited["topics"][0]["topic"] == "Calculus"
    by_name = run_json("topics", str(example_file), "--sort", "name")
    assert by_name["topics"][0]["topic"] == "Algebra"
    sparse = run_json("topics", str(example_file), "--min-questions", "2")
    assert [row["topic"] for row in sparse["topics"]] == ["Calculus"]


def test_types_command(examples_dir):
    payload = run_json("types", str(examples_dir))
    types = {row["type"]: row for row in payload["types"]}
    assert types["mcq"]["label"] == "MCQ"
    assert types["case_based"]["questions"] == 1
    assert types["matching"]["questions"] == 1
    assert sum(row["questions"] for row in payload["types"]) == 64


def test_marks_command(examples_dir):
    payload = run_json("marks", str(examples_dir))
    assert payload["total_questions"] == 64
    assert payload["min_marks"] == 1.0
    assert payload["max_marks"] == 6.0
    assert payload["histogram"]
    assert payload["by_type"]


def test_concepts_command(examples_dir):
    payload = run_json("concepts", str(examples_dir), "--limit", "5")
    assert len(payload["concepts"]) == 5
    assert payload["concepts"][0]["concept"]
    tags = run_json("concepts", str(examples_dir), "--source", "tag")
    assert {row["concept"] for row in tags["concepts"]} >= {"Matrices", "Determinants"}
    assert tags["sources"] == ["tag"]
    wide = run_json("concepts", str(examples_dir), "--min-papers", "2")
    assert all(row["papers"] >= 2 for row in wide["concepts"])


def test_list_command(example_file):
    payload = run_json("list", str(example_file))
    assert len(payload["questions"]) == 8
    first = payload["questions"][0]
    assert first["id"] == "Q1"
    assert first["marks"] == 1.0
    assert "Trigonometry" in first["concepts"]
    limited = run_json("list", str(example_file), "-l", "3")
    assert len(limited["questions"]) == 3
    by_topic = run_json("list", str(example_file), "-s", "topic")
    assert by_topic["questions"][0]["topic"] == "Algebra"


def test_list_table_has_no_traceback(example_file):
    code, out, _ = run("list", str(example_file), "--no-color")
    assert code == 0
    assert "Q1" in out and "Traceback" not in out
    code, out, _ = run("list", str(example_file), "--no-color", "--full")
    assert code == 0
    assert "concepts" in out


def test_compare_command(examples_dir):
    payload = run_json(
        "compare",
        str(examples_dir / "jee_main_2023.xml"),
        "--against",
        str(examples_dir / "jee_main_2024.xml"),
    )
    assert payload["baseline"]["label"] == "JEE (Main) 2023 Mathematics"
    assert payload["variant"]["label"] == "JEE (Main) 2024 Mathematics"
    assert payload["question_delta"] == 0
    assert payload["marks_delta"] == 7.0
    assert "Probability" in payload["added_topics"]
    statuses = {row["status"] for row in payload["topics"]}
    assert {"new", "dropped", "flat", "down"} & statuses


def test_compare_requires_a_variant(examples_dir):
    code, _, err = run("compare", str(examples_dir))
    assert code == 2
    assert "against" in err


def test_trend_command(examples_dir):
    payload = run_json(
        "trend",
        str(examples_dir / "jee_main_2023.xml"),
        str(examples_dir / "jee_main_2024.xml"),
    )
    assert payload["years"] == [2023, 2024]
    assert [row["questions"] for row in payload["per_year"]] == [12, 12]
    changes = {row["topic"]: row for row in payload["changes"]}
    assert changes["Probability"]["series"] == [0, 1]
    assert changes["Probability"]["delta"] == 1
    pairs = {(row["year"], row["topic"]) for row in payload["series"]}
    assert len(pairs) == len(payload["series"])  # exactly one row per (year, topic)


def test_trend_needs_two_years(examples_dir):
    code, _, err = run("trend", str(examples_dir / "jee_main_2023.xml"))
    assert code == 4
    assert "at least two distinct years" in err


def test_validate_command(examples_dir):
    code, out, _ = run("validate", str(examples_dir), "--no-color")
    assert code == 0
    assert "all files parsed" in out
    assert "warning" in out


def test_validate_strict_mode(examples_dir):
    code, _, _ = run("validate", str(examples_dir / "schema_cookbook.xml"), "--strict")
    assert code == 3
    code, _, _ = run("validate", str(examples_dir / "jee_main_2023.xml"), "--strict")
    assert code == 0


def test_validate_reports_broken_files(tmp_path):
    broken = tmp_path / "broken.xml"
    broken.write_text("<pyqs><oops>", encoding="utf-8")
    code, out, _ = run("validate", str(broken), "--no-color")
    assert code == 3
    assert "failed" in out
    code, out, _ = run("validate", str(broken), "--format", "json", "--no-color")
    assert code == 3
    payload = json.loads(out)
    assert payload["failures"] == 1
    assert "line 1" in payload["files"][0]["error"]


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #


def test_export_json(example_file):
    payload = run_json("export", str(example_file))
    assert payload["generator"] == f"pyqs {__version__}"
    assert len(payload["questions"]) == 8
    first = payload["questions"][0]
    assert first["type"] == "mcq"
    assert first["options"][0] == {"label": "A", "text": "$\\cos(x)-\\sin(x)$"}
    assert first["effective_marks"] == 1.0
    assert payload["papers"][0]["total_marks"] == 16.0
    assert payload["summary"]["questions"] == 8


def test_export_csv_and_markdown(example_file):
    code, out, _ = run("export", str(example_file), "--format", "csv")
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == 8
    assert rows[0]["id"] == "Q1"

    code, out, _ = run("export", str(example_file), "--format", "md")
    assert code == 0
    assert out.startswith("# pyqs questions")
    assert "| id |" in out


def test_export_defaults_to_json_for_table(example_file):
    code, out, _ = run("export", str(example_file))
    assert code == 0
    assert json.loads(out)["questions"]


def test_export_to_file(tmp_path, example_file):
    target = tmp_path / "out.json"
    code, out, err = run("export", str(example_file), "-o", str(target))
    assert code == 0
    assert out == ""
    assert f"wrote {target}" in err
    assert len(json.loads(target.read_text(encoding="utf-8"))["questions"]) == 8


# --------------------------------------------------------------------------- #
# filters across commands
# --------------------------------------------------------------------------- #


def test_topic_filter(example_file):
    payload = run_json("topics", str(example_file), "--topic", "calculus")
    assert [row["topic"] for row in payload["topics"]] == ["Calculus"]
    assert payload["filters"] == "topic in calculus"


def test_type_filter_is_normalised(example_file):
    payload = run_json("types", str(example_file), "--type", "MCQ")
    assert [row["type"] for row in payload["types"]] == ["mcq"]
    assert run_json("types", str(example_file), "--type", "subjective")["types"][0]["type"] == (
        "long_answer"
    )


def test_marks_and_year_and_id_filters(examples_dir):
    payload = run_json("marks", str(examples_dir), "--min-marks", "4")
    assert all(bucket["marks"] >= 4 for bucket in payload["histogram"])
    selected = run_json("list", str(examples_dir), "--min-marks", "4")
    assert payload["total_questions"] == len(selected["questions"])
    assert payload["total_questions"] < run_json("list", str(examples_dir))["total_questions"]
    years = run_json("list", str(examples_dir), "--year", "2024")
    assert {row["year"] for row in years["questions"]} == {2024}
    ids = run_json("list", str(examples_dir), "--id", "Q1")
    assert {row["id"] for row in ids["questions"]} == {"Q1"}


def test_grep_filter(example_file):
    payload = run_json("list", str(example_file), "--grep", "derivative")
    assert len(payload["questions"]) == 2


def test_no_match_exits_with_code_four(example_file):
    code, _, err = run("topics", str(example_file), "--topic", "nope")
    assert code == 4
    assert "error" in err


def test_missing_file_exits_with_code_three(tmp_path):
    code, _, err = run("summary", str(tmp_path / "nope.xml"))
    assert code == 3
    assert "cannot read" in err


def test_broken_xml_exits_with_code_three(tmp_path):
    broken = tmp_path / "broken.xml"
    broken.write_text("<pyqs><oops>", encoding="utf-8")
    code, _, err = run("summary", str(broken))
    assert code == 3
    assert "line 1" in err


# --------------------------------------------------------------------------- #
# output plumbing
# --------------------------------------------------------------------------- #


def test_warnings_are_noted_on_stderr(examples_dir):
    code, out, err = run("summary", str(examples_dir / "schema_cookbook.xml"), "--no-color")
    assert code == 0
    assert "parse warning" in err
    assert "parse warning" not in out


def test_formats_csv_and_markdown_for_reports(examples_dir):
    code, out, _ = run("topics", str(examples_dir), "--format", "csv", "--no-color")
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows and "topic" in rows[0]
    code, out, _ = run("types", str(examples_dir), "--format", "md", "--no-color")
    assert code == 0
    assert out.startswith("# pyqs types")


def test_theme_falls_back_to_ascii_for_legacy_code_pages():
    from argparse import Namespace

    from pyqs import cli, render

    args = Namespace(no_color=True)

    class LegacyStream(io.StringIO):
        encoding = "cp1252"

    class ModernStream(io.StringIO):
        encoding = "utf-8"

    assert cli._theme(args, LegacyStream()).ascii_only is True
    assert cli._theme(args, ModernStream()).ascii_only is False
    assert render.can_encode("\u2500", ModernStream()) is True


def test_width_option_is_honoured(example_file):
    _, narrow, _ = run("topics", str(example_file), "--no-color", "--width", "60")
    _, wide, _ = run("topics", str(example_file), "--no-color", "--width", "200")
    assert max(len(line) for line in narrow.splitlines()) < max(
        len(line) for line in wide.splitlines()
    )


def test_module_entry_point_is_importable():
    import pyqs.__main__ as entry

    assert callable(entry.main)
