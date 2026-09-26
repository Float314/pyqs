"""Parser behaviour: vocabulary, structure and error handling."""

from __future__ import annotations

import pytest

from pyqs.errors import InputError, ParseError, SchemaError
from pyqs.parser import (
    infer_year,
    normalise_type,
    parse_marks,
    parse_paper,
    parse_paper_string,
    parse_year,
)

from .conftest import MINIMAL, paper_from


def test_minimal_paper_metadata(paper):
    assert paper.exam == "Mock"
    assert paper.year == 2024
    assert paper.subject == "Mathematics"
    assert paper.total_questions == 2
    assert paper.total_marks == 4.0
    assert paper.name == "Mock 2024 Mathematics"


def test_question_fields(paper):
    first, second = paper.questions
    assert first.id == "Q1"
    assert first.type == "mcq"
    assert first.marks == 1.0
    assert first.topic == "Limits"
    assert [option.label for option in first.options] == ["A", "B"]
    assert first.answer == "B"
    assert first.answer_label == "B"
    assert "sin x" in first.all_text
    assert second.type == "numerical"
    assert second.effective_marks == 3.0
    assert second.answer_label is None  # a free-form answer is not an option label


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mcq", "mcq"),
        ("MCQ", "mcq"),
        ("  Multiple Choice (Single) ", "mcq"),
        ("multiple_correct", "mcq_multiple"),
        ("MCC", "mcq_multiple"),
        ("assertion reason", "assertion_reason"),
        ("AR", "assertion_reason"),
        ("NAT", "numerical"),
        ("short-answer", "short_answer"),
        ("Subjective", "long_answer"),
        ("case based", "case_based"),
        ("list match", "matching"),
        ("", "unknown"),
        (None, "unknown"),
        ("viva voce", "viva_voce"),
    ],
)
def test_normalise_type(raw, expected):
    assert normalise_type(raw) == expected


@pytest.mark.parametrize(
    ("raw", "value", "warning"),
    [
        (None, None, None),
        ("", None, None),
        ("4", 4.0, None),
        ("2.5", 2.5, None),
        (" 3 marks ", 3.0, None),
        ("two", None, "could not read marks 'two'"),
    ],
)
def test_parse_marks(raw, value, warning):
    parsed, message = parse_marks(raw)
    assert parsed == value
    assert (message is not None) == (warning is not None)


def test_parts_are_collected_and_summed():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="long_answer" topic="Calculus">
            <question>Study f.</question>
            <parts>
              <part id="a" marks="2">First</part>
              <part id="b" marks="1">Second</part>
            </parts>
          </question_body>
        </pyqs>"""
    )
    question = paper.questions[0]
    assert question.marks is None
    assert question.effective_marks == 3.0
    assert question.part_count == 2
    assert question.has_declared_marks


def test_nested_parts_are_walked():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="long_answer" topic="Calculus">
            <question>Study f.</question>
            <parts>
              <part id="a" marks="1">Outer</part>
              <part id="b" marks="1">
                Inner
                <part id="b1" marks="2">Deep</part>
              </part>
            </parts>
          </question_body>
        </pyqs>"""
    )
    question = paper.questions[0]
    assert question.part_count == 2
    assert [part.id for part in question.all_parts()] == ["a", "b", "b1"]
    assert question.effective_marks == 4.0
    assert question.parts[1].text == "Inner"
    assert question.parts[1].subparts[0].text == "Deep"
    assert "Deep" in question.all_text


def test_declared_marks_win_over_parts():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="long_answer" marks="10" topic="Calculus">
            <question>Study f.</question>
            <parts><part id="a" marks="2">First</part></parts>
          </question_body>
        </pyqs>"""
    )
    assert paper.questions[0].effective_marks == 10.0


def test_question_without_marks_counts_zero():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="viva" topic="Misc">
            <question>Talk.</question>
          </question_body>
        </pyqs>"""
    )
    question = paper.questions[0]
    assert question.effective_marks == 0.0
    assert question.has_declared_marks is False


def test_topic_from_child_element():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="short_answer" marks="1">
            <topic>Algebra</topic>
            <question>Solve.</question>
          </question_body>
        </pyqs>"""
    )
    assert paper.questions[0].topic == "Algebra"


def test_option_wrapper_element_and_generated_labels():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="matching" marks="2" topic="Algebra">
            <question>Match.</question>
            <options>
              <option>first</option>
              <option>second</option>
            </options>
          </question_body>
        </pyqs>"""
    )
    assert [option.label for option in paper.questions[0].options] == ["A", "B"]


def test_concepts_from_tags_and_concepts_elements():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="short_answer" marks="1" topic="Algebra">
            <concepts>Matrices, Determinants</concepts>
            <question>Find the determinant.</question>
          </question_body>
          <question_body id="Q2" type="short_answer" marks="1" topic="Algebra">
            <tags><tag>Mean</tag><tag>Median</tag></tags>
            <question>Find the mean.</question>
          </question_body>
        </pyqs>"""
    )
    assert paper.questions[0].concepts == ["Matrices", "Determinants"]
    assert paper.questions[1].concepts == ["Mean", "Median"]


def test_generated_id_and_unknown_type_produce_warnings():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body type="mcq" marks="1" topic="Algebra">
            <question>Pick.</question>
          </question_body>
        </pyqs>"""
    )
    question = paper.questions[0]
    assert question.id == "Q1"
    assert any("without an id" in warning for warning in paper.warnings)


def test_assertion_reason_needs_no_question_element():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="assertion_reason" marks="1" topic="Limits">
            <assertion>A</assertion>
            <reason>B</reason>
            <option name="A">both</option>
            <answer>A</answer>
          </question_body>
        </pyqs>"""
    )
    question = paper.questions[0]
    assert question.assertion == "A"
    assert question.reason == "B"
    assert question.text.startswith("A B")
    assert paper.warnings == []


def test_stem_falls_back_to_assertion_with_warning():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="short_answer" marks="1" topic="Limits">
            <assertion>A</assertion>
            <answer>ok</answer>
          </question_body>
        </pyqs>"""
    )
    assert paper.questions[0].text == "A"
    assert any("no <question> element" in warning for warning in paper.warnings)


def test_unknown_attributes_are_preserved():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="mcq" marks="1" topic="Limits" difficulty="hard">
            <question>Pick.</question>
          </question_body>
        </pyqs>"""
    )
    assert paper.questions[0].extra == {"difficulty": "hard"}


def test_namespaces_are_ignored():
    paper = paper_from(
        """<pyq:pyqs xmlns:pyq="urn:pyqs" year="2024">
          <pyq:question_body id="Q1" pyq:type="mcq" pyq:marks="1" pyq:topic="Limits">
            <pyq:question>Pick.</pyq:question>
          </pyq:question_body>
        </pyq:pyqs>"""
    )
    question = paper.questions[0]
    assert (question.id, question.type, question.marks, question.topic) == (
        "Q1",
        "mcq",
        1.0,
        "Limits",
    )


def test_bare_question_tag_is_treated_as_a_stem():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="short_answer" marks="1" topic="Limits">
            <question>Not a question body.</question>
            <answer>ok</answer>
          </question_body>
        </pyqs>"""
    )
    assert len(paper.questions) == 1
    assert paper.questions[0].text == "Not a question body."


def test_multiple_paper_sections(tmp_path):
    document = """<pyqs version="1.0">
      <paper exam="Main" year="2022" subject="Maths">
        <question_body id="A1" type="mcq" marks="1" topic="Limits">
          <question>One.</question>
        </question_body>
      </paper>
      <paper exam="Main" year="2023" subject="Maths">
        <question_body id="B1" type="mcq" marks="1" topic="Limits">
          <question>Two.</question>
        </question_body>
        <question_body id="B2" type="mcq" marks="1" topic="Algebra">
          <question>Three.</question>
        </question_body>
      </paper>
    </pyqs>"""
    path = tmp_path / "bank.xml"
    path.write_text(document, encoding="utf-8")
    papers = parse_paper(path)
    assert [paper.year for paper in papers] == [2022, 2023]
    assert [paper.total_questions for paper in papers] == [1, 2]
    assert papers[0].subject == "Maths"


def test_paper_sections_inherit_root_metadata():
    papers = parse_paper_string(
        """<pyqs year="2021" subject="Maths" exam="Main">
          <paper year="2022">
            <question_body id="A1" type="mcq" marks="1" topic="Limits">
              <question>One.</question>
            </question_body>
          </paper>
        </pyqs>"""
    )
    assert papers[0].year == 2022
    assert papers[0].subject == "Maths"
    assert papers[0].exam == "Main"


def test_malformed_xml_raises_parse_error():
    with pytest.raises(ParseError) as excinfo:
        parse_paper_string("<pyqs><question_body></pyqs>", "broken.xml")
    assert "broken.xml" in str(excinfo.value)


def test_document_without_questions_raises_schema_error():
    with pytest.raises(SchemaError):
        parse_paper_string("<pyqs year='2024'></pyqs>", "empty.xml")


def test_missing_file_raises_input_error(tmp_path):
    with pytest.raises(InputError):
        parse_paper(tmp_path / "nope.xml")


def test_non_utf8_file_raises_parse_error(tmp_path):
    path = tmp_path / "latin.xml"
    path.write_bytes(
        "<pyqs year='2024'><question_body id='Q1' marks='1'>caf\xe9</question_body></pyqs>".encode(
            "latin-1"
        )
    )
    with pytest.raises(ParseError):
        parse_paper(path)


@pytest.mark.parametrize(
    ("name", "year"),
    [
        ("jee_main_2024.xml", 2024),
        ("2019_paper.xml", 2019),
        ("paper.xml", None),
        (None, None),
    ],
)
def test_infer_year(name, year):
    assert infer_year(name) == year


def test_parse_year_from_loose_text():
    assert parse_year("session 2021-22") == 2021
    assert parse_year("none") is None


def test_latex_payloads_survive_whitespace_collapsing(paper):
    assert "\\lim_{x\\to0}" in paper.questions[0].text


def test_minimal_fixture_is_reused(paper):
    assert paper_from(MINIMAL).total_questions == 2
