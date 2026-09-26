"""Concept extraction from tags, keywords and LaTeX."""

from __future__ import annotations

import pytest

from pyqs.concepts import (
    SOURCES,
    concepts_from_keywords,
    concepts_from_latex,
    concepts_from_tags,
    extract_concepts,
    normalise_concept,
)
from pyqs.models import Question

from .conftest import paper_from


def question(**kwargs) -> Question:
    defaults = {"id": "Q1", "type": "short_answer", "marks": 1.0, "text": ""}
    defaults.update(kwargs)
    return Question(**defaults)


def names(hits) -> list:
    return [hit.name for hit in hits]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Matrices ", "Matrices"),
        ("case-based", "case based"),
        ("`Quaternions`", "Quaternions"),
        ('"Probability"', "Probability"),
        ("Limits & Continuity", "Limits & Continuity"),
        ("3-D Geometry", "3 D Geometry"),
        ("", ""),
    ],
)
def test_normalise_concept(raw, expected):
    assert normalise_concept(raw) == expected


def test_tags_are_split_and_normalised():
    q = question(concepts=["Matrices, Determinants", "case-based"])
    assert names(concepts_from_tags(q)) == ["Matrices", "Determinants", "case based"]
    assert all(hit.source == "tag" for hit in concepts_from_tags(q))


def test_keyword_lexicon_matches_stems():
    q = question(text="Differentiate y with respect to x and integrate the result.")
    found = set(names(concepts_from_keywords(q)))
    assert {"Differentiation", "Integration"} <= found


def test_keyword_lexicon_ignores_substrings():
    assert concepts_from_keywords(question(text="using the outside world")) == []
    assert concepts_from_keywords(question(text="")) == []


def test_latex_wins_over_ambiguous_keyword():
    # "\lim" contains the letters "lim" but is not the English word "limit".
    q = question(text=r"Find $\lim_{x\to0}\frac{\sin x}{x}$.")
    hits = {hit.name: hit.source for hit in extract_concepts(q)}
    assert hits["Limits & Continuity"] == "latex"
    assert hits["Trigonometry"] == "latex"


def test_latex_lexicon():
    q = question(text=r"Evaluate $\int_0^1 \sin x\,dx$.")
    assert set(names(concepts_from_latex(q))) == {"Integration", "Trigonometry"}


def test_determinant_in_prose_is_a_keyword_hit():
    q = question(text="Find the determinant of the given matrix.")
    assert "Matrices & Determinants" in names(concepts_from_keywords(q))


def test_matrix_environment_counts_as_matrix():
    q = question(text=r"Given $A=\begin{bmatrix}1&0\end{bmatrix}$, find $|A|$.")
    assert "Matrices & Determinants" in names(concepts_from_latex(q))


def test_latex_case_sensitivity_is_handled():
    q = question(text=r"$\INT_0^1 x\,dx$")
    assert "Integration" in names(concepts_from_latex(q))


def test_answer_text_contributes_concepts():
    q = question(text="State the result.", assertion="", reason="")
    q.answer = "By differentiating, the slope at the point is found."
    assert "Differentiation" in names(concepts_from_keywords(q))


def test_extract_concepts_dedupes_keeping_best_source():
    q = question(text=r"Compute $\int x\,dx$ by integration.", concepts=["Integration"])
    hits = extract_concepts(q)
    integration = [hit for hit in hits if hit.name == "Integration"]
    assert len(integration) == 1
    assert integration[0].source == "tag"


def test_source_selection():
    q = question(text=r"Compute $\int x\,dx$.", concepts=["Calculus"])
    assert {hit.source for hit in extract_concepts(q, ["tag"])} == {"tag"}
    assert {hit.source for hit in extract_concepts(q, ["latex"])} == {"latex"}
    assert set(SOURCES) == {"tag", "keyword", "latex"}


def test_no_concepts_for_empty_question():
    assert extract_concepts(question()) == []


def test_concepts_from_real_paper(example_file):
    from pyqs.parser import parse_paper

    paper = parse_paper(example_file)[0]
    found = {hit.name for q in paper.questions for hit in extract_concepts(q)}
    assert "Trigonometry" in found
    assert "Limits & Continuity" in found


def test_concepts_are_case_insensitive_when_grouped():
    q = question(text="Solve the quadratic equation.", concepts=["QUADRATIC"])
    hits = extract_concepts(q)
    quadratic = [hit for hit in hits if hit.name.casefold() == "quadratic"]
    assert len(quadratic) == 1


def test_part_text_is_searched():
    paper = paper_from(
        """<pyqs year="2024">
          <question_body id="Q1" type="long_answer" marks="2" topic="Calculus">
            <question>Consider the function.</question>
            <parts><part id="a" marks="2">Find the maximum value.</part></parts>
          </question_body>
        </pyqs>"""
    )
    assert "Optimisation" in names(extract_concepts(paper.questions[0]))
