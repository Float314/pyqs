"""Statistics: summaries, topics, types, marks, concepts, compare and trend."""

from __future__ import annotations

import pytest

from pyqs import analysis
from pyqs.analysis import Filters
from pyqs.errors import NoDataError
from pyqs.parser import parse_paper, parse_paper_string


def bank(year: int, questions: str) -> str:
    return f'<pyqs exam="Mock" year="{year}" subject="Maths">{questions}</pyqs>'


def question_xml(qid: str, qtype: str, marks: str, topic: str, body: str = "") -> str:
    return (
        f'<question_body id="{qid}" type="{qtype}" marks="{marks}" topic="{topic}">'
        f"{body}</question_body>"
    )


@pytest.fixture
def two_year_papers(two_year_bank):
    """Convenience alias: the two-year fixture split into its two papers."""

    baseline, variant = two_year_bank
    return baseline, variant


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #


def test_summary_numbers(papers):
    report = analysis.summarise(papers)
    assert report.papers == 1
    assert report.questions == 2
    assert report.marks == 4.0
    assert report.topics == 2
    assert report.years == [2024]
    assert report.mean_marks == 2.0
    assert report.median_marks == 2.0
    assert report.to_dict()["questions"] == 2


def test_summary_uses_filters(papers):
    report = analysis.summarise(papers, analysis.select_questions(papers, Filters(types=("mcq",))))
    assert report.questions == 1
    assert report.marks == 1.0


def test_summary_disambiguates_duplicate_names(two_year_bank):
    duplicate = parse_paper_string(
        f"""<pyqs exam="Mock" subject="Maths">
          <paper year="2024">{question_xml("Q1", "mcq", 1, "Limits", "<question>A</question>")}</paper>
          <paper year="2024">{question_xml("Q1", "mcq", 1, "Limits", "<question>B</question>")}</paper>
        </pyqs>""",
        "dupes.xml",
    )
    report = analysis.summarise(duplicate)
    assert [row["name"] for row in report.paper_rows] == [
        "Mock 2024 Maths (dupes.xml)",
        "Mock 2024 Maths (dupes.xml)",
    ]
    assert [row["name"] for row in analysis.summarise(two_year_bank).paper_rows] == [
        "Mock 2023 Maths",
        "Mock 2024 Maths",
    ]


# --------------------------------------------------------------------------- #
# topics
# --------------------------------------------------------------------------- #


def test_topic_stats(two_year_bank):
    report = analysis.topic_stats(two_year_bank)
    assert report.total_questions == 7
    assert report.total_marks == 17.0
    by_topic = {row.topic: row for row in report.rows}
    assert by_topic["Limits"].questions == 3
    assert by_topic["Limits"].marks == 3.0
    assert by_topic["Algebra"].questions == 2
    assert by_topic["Algebra"].marks == 6.0
    assert by_topic["Limits"].share == pytest.approx(3 / 7)
    assert by_topic["Limits"].papers == 2
    assert by_topic["Limits"].types == {"mcq": 3}
    assert by_topic["Integration"].avg_marks == 4.0
    assert report.rows[0].topic == "Limits"


def test_topic_sorting_and_limit(two_year_bank):
    by_marks = analysis.topic_stats(two_year_bank, sort="marks")
    assert by_marks.rows[0].topic == "Integration"
    by_name = analysis.topic_stats(two_year_bank, sort="name")
    assert [row.topic for row in by_name.rows] == ["Algebra", "Integration", "Limits"]
    assert len(analysis.topic_stats(two_year_bank, limit=2).rows) == 2
    filtered = analysis.topic_stats(two_year_bank, min_questions=2)
    assert [row.topic for row in filtered.rows] == ["Limits", "Integration", "Algebra"]


def test_unclassified_topic_bucket():
    papers = parse_paper_string(
        bank(2024, '<question_body id="Q1" type="mcq" marks="1"><question>x</question></question_body>')
    )
    report = analysis.topic_stats(papers)
    assert report.rows[0].topic == "Unclassified"


def test_topic_min_and_max_marks(two_year_bank):
    report = analysis.topic_stats(two_year_bank)
    algebra = next(row for row in report.rows if row.topic == "Algebra")
    assert (algebra.min_marks, algebra.max_marks) == (2.0, 4.0)


# --------------------------------------------------------------------------- #
# types
# --------------------------------------------------------------------------- #


def test_type_stats(two_year_bank):
    report = analysis.type_stats(two_year_bank)
    rows = {row.type: row for row in report.rows}
    assert rows["mcq"].questions == 3
    assert rows["numerical"].questions == 2
    assert rows["long_answer"].questions == 1
    assert rows["mcq"].label == "MCQ"
    assert rows["mcq"].share == pytest.approx(3 / 7)
    assert rows["long_answer"].topics == 1
    assert next(row.type for row in report.rows) == "mcq"


# --------------------------------------------------------------------------- #
# marks
# --------------------------------------------------------------------------- #


def test_marks_distribution(two_year_bank):
    report = analysis.marks_distribution(two_year_bank)
    assert report.total_questions == 7
    assert report.total_marks == 17.0
    assert report.min_marks == 1.0
    assert report.max_marks == 4.0
    assert report.median_marks == 2.0
    assert [(bucket.marks, bucket.questions) for bucket in report.buckets] == [
        (1.0, 3),
        (2.0, 1),
        (4.0, 3),
    ]
    assert report.buckets[0].share == pytest.approx(3 / 7)
    assert report.buckets[-1].cumulative_share == 1.0
    assert report.inferred_marks == 0.0
    assert report.missing_marks == 0


def test_marks_inferred_from_parts():
    papers = parse_paper_string(
        """<pyqs exam="Mock" year="2024" subject="Maths">
          <question_body id="Q1" type="long_answer" topic="Calculus">
            <question>x</question>
            <parts><part id="a" marks="2">a</part><part id="b" marks="2">b</part></parts>
          </question_body>
          <question_body id="Q2" type="viva" topic="Misc"><question>y</question></question_body>
        </pyqs>"""
    )
    report = analysis.marks_distribution(papers)
    assert report.total_marks == 4.0
    assert report.inferred_marks == 4.0
    assert report.missing_marks == 1


# --------------------------------------------------------------------------- #
# concepts
# --------------------------------------------------------------------------- #


def test_concept_stats(two_year_bank):
    first = question_xml("Q1", "mcq", 1, "Limits", r"<question>Find $\lim_{x\to0}\sin x/x$.</question>")
    second = question_xml("Q2", "short_answer", 2, "Limits", r"<question>Evaluate $\lim_{x\to0}x^2$.</question>")
    text = parse_paper_string(
        f'<pyqs exam="Mock" year="2023" subject="Maths">\n  {first}\n  {second}\n</pyqs>'
    )
    report = analysis.concept_stats(text)
    row = next(row for row in report.rows if row.concept == "Limits & Continuity")
    assert row.questions == 2
    assert row.share == 1.0
    assert row.sources == {"latex": 2}  # \lim is trusted over the keyword lexicon
    assert report.sources == ["tag", "latex", "keyword"]


def test_concept_min_papers_and_limit(example_file):
    loaded = parse_paper(example_file)
    every = analysis.concept_stats(loaded, min_papers=1)
    only_spread = analysis.concept_stats(loaded, min_papers=5)
    assert len(only_spread.rows) == 0
    assert len(every.rows) > 0
    assert len(analysis.concept_stats(loaded, limit=1).rows) == 1


# --------------------------------------------------------------------------- #
# filters
# --------------------------------------------------------------------------- #


def test_filters(two_year_bank):
    assert len(analysis.select_questions(two_year_bank, Filters(years=(2023,)))) == 3
    assert len(analysis.select_questions(two_year_bank, Filters(min_marks=4))) == 3
    assert len(analysis.select_questions(two_year_bank, Filters(max_marks=1))) == 3
    assert len(analysis.select_questions(two_year_bank, Filters(types=("numerical",)))) == 2
    assert len(analysis.select_questions(two_year_bank, Filters(topics=("algebra",)))) == 2
    assert len(analysis.select_questions(two_year_bank, Filters(grep="F"))) == 1
    assert len(analysis.select_questions(two_year_bank, Filters(ids=("q1",)))) == 2
    assert Filters().active is False
    assert "marks >= 4" in Filters(min_marks=4).describe()


def test_no_data_error(two_year_bank):
    with pytest.raises(NoDataError):
        analysis.topic_stats(two_year_bank, filters=Filters(topics=("nonexistent",)))
    single_year = parse_paper_string(bank(2024, question_xml("Q1", "mcq", 1, "Limits")))
    with pytest.raises(NoDataError):
        analysis.trend(single_year)
    with pytest.raises(NoDataError):
        analysis.concept_stats(single_year, sources=["tag"])


# --------------------------------------------------------------------------- #
# compare
# --------------------------------------------------------------------------- #


def test_compare_two_year_bank(two_year_bank):
    baseline, variant = two_year_bank
    report = analysis.compare([baseline], [variant])
    assert report.baseline_label == "Mock 2023 Maths"
    assert report.variant_label == "Mock 2024 Maths"
    assert report.question_delta == 1
    assert report.marks_delta == 9.0
    rows = {row.topic: row for row in report.rows}
    assert rows["Integration"].status == "new"
    assert rows["Limits"].status == "down"
    assert rows["Algebra"].status == "flat"
    assert report.added_topics == ["Integration"]
    assert report.removed_topics == []
    assert rows["Limits"].question_delta == -1


def test_compare_reports_dropped_topics():
    baseline = parse_paper_string(bank(2023, question_xml("Q1", "mcq", 1, "Algebra")))
    variant = parse_paper_string(bank(2024, question_xml("Q1", "mcq", 1, "Limits")))
    report = analysis.compare(baseline, variant)
    assert report.removed_topics == ["Algebra"]
    assert report.added_topics == ["Limits"]
    assert {row.status for row in report.rows} == {"new", "dropped"}


def test_compare_labels_multiple_papers(two_year_bank):
    report = analysis.compare(two_year_bank, two_year_bank)
    assert report.baseline_label == "2 papers"


# --------------------------------------------------------------------------- #
# trend
# --------------------------------------------------------------------------- #


def test_trend(two_year_bank):
    report = analysis.trend(two_year_bank)
    assert report.years == [2023, 2024]
    assert [row["questions"] for row in report.per_year] == [3, 4]
    changes = {change["topic"]: change for change in report.changes}
    assert changes["Limits"]["series"] == [2, 1]
    assert changes["Limits"]["delta"] == -1
    assert changes["Integration"]["series"] == [0, 2]
    assert changes["Integration"]["delta"] == 2
    assert report.to_rows()[0]["year"] == 2023


def test_trend_needs_two_years():
    papers = parse_paper_string(bank(2024, question_xml("Q1", "mcq", 1, "Limits")))
    with pytest.raises(NoDataError) as excinfo:
        analysis.trend(papers)
    assert "at least two distinct years" in str(excinfo.value)


def test_trend_limit(two_year_bank):
    assert len(analysis.trend(two_year_bank, limit=1).changes) == 1


# --------------------------------------------------------------------------- #
# listing and validation
# --------------------------------------------------------------------------- #


def test_question_rows(two_year_bank):
    report = analysis.question_rows(two_year_bank)
    assert [row.id for row in report.rows] == ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3", "Q4"]
    assert report.total_marks == 17.0
    by_marks = analysis.question_rows(two_year_bank, sort="marks")
    assert by_marks.rows[0].marks == 4.0
    assert len(analysis.question_rows(two_year_bank, limit=2).rows) == 2
    single = analysis.question_rows(two_year_bank, sort="id")
    assert [row.id for row in single.rows] == ["Q1", "Q1", "Q2", "Q2", "Q3", "Q3", "Q4"]


def test_validate_files(tmp_path, example_file):
    good = tmp_path / "good.xml"
    good.write_text(
        bank(
            2024,
            question_xml(
                "Q1",
                "mcq",
                1,
                "Limits",
                "<question>x</question><option name='A'>1</option><answer>A</answer>",
            ),
        ),
        encoding="utf-8",
    )
    bad = tmp_path / "bad.xml"
    bad.write_text("<pyqs><oops>", encoding="utf-8")

    report = analysis.validate_files([good, bad, example_file])
    assert [item.ok for item in report.files] == [True, False, True]
    assert len(report.failures) == 1
    assert report.warning_count == 0
    assert report.to_dict()["ok"] is False
    assert report.to_rows()[1]["error"]


def test_validate_files_reports_warnings(tmp_path):
    path = tmp_path / "warn.xml"
    path.write_text(
        bank(2024, '<question_body type="mcq" marks="1" topic="Limits"><question>x</question></question_body>'),
        encoding="utf-8",
    )
    report = analysis.validate_files([path])
    assert report.files[0].ok is True
    assert len(report.files[0].warnings) == 2
    assert any("without an id" in warning for warning in report.files[0].warnings)
    assert report.warning_count == 2
    assert report.failures == []


def test_reports_serialise_to_rows(two_year_bank):
    for report in (
        analysis.summarise(two_year_bank),
        analysis.topic_stats(two_year_bank),
        analysis.type_stats(two_year_bank),
        analysis.marks_distribution(two_year_bank),
        analysis.concept_stats(two_year_bank),
        analysis.question_rows(two_year_bank),
        analysis.compare([two_year_bank[0]], [two_year_bank[1]]),
        analysis.trend(two_year_bank),
    ):
        rows = report.to_rows()
        assert isinstance(rows, list)
        for row in rows:
            assert all(isinstance(key, str) for key in row)
        assert isinstance(report.to_dict(), dict)


def test_bank_helper_is_used():
    assert "Mock" in bank(2030, "")
