"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:  # allows running the suite without installing the package
    sys.path.insert(0, str(SRC))

from pyqs.models import Paper  # noqa: E402
from pyqs.parser import parse_paper_string  # noqa: E402

EXAMPLES = REPO_ROOT / "examples"

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<pyqs version="1.0" exam="Mock" year="2024" subject="Mathematics">
  <question_body id="Q1" type="mcq" marks="1" topic="Limits">
    <question>Evaluate $\\lim_{x\\to0}\\frac{\\sin x}{x}$.</question>
    <option name="A">0</option>
    <option name="B">1</option>
    <answer>B</answer>
  </question_body>
  <question_body id="Q2" type="numerical" marks="3" topic="Integration">
    <question>Evaluate $\\int_0^1 x\\,dx$.</question>
    <answer>1/2</answer>
  </question_body>
</pyqs>
"""


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def example_file() -> Path:
    return EXAMPLES / "example1.xml"


def paper_from(text: str, source: str = "<test>") -> Paper:
    """Parse ``text`` and return its single paper."""

    papers = parse_paper_string(text, source)
    assert len(papers) == 1, f"expected one paper, got {len(papers)}"
    return papers[0]


@pytest.fixture
def paper() -> Paper:
    return paper_from(MINIMAL)


@pytest.fixture
def papers(paper: Paper) -> list[Paper]:
    return [paper]


TWO_YEAR_BANK = """<pyqs exam="Mock" subject="Maths">
  <paper year="2023">
    <question_body id="Q1" type="mcq" marks="1" topic="Limits">
      <question>Limit question A.</question>
    </question_body>
    <question_body id="Q2" type="mcq" marks="1" topic="Limits">
      <question>Limit question B.</question>
    </question_body>
    <question_body id="Q3" type="short_answer" marks="2" topic="Algebra">
      <question>Algebra question C.</question>
    </question_body>
  </paper>
  <paper year="2024">
    <question_body id="Q1" type="mcq" marks="1" topic="Limits">
      <question>Limit question D.</question>
    </question_body>
    <question_body id="Q2" type="numerical" marks="4" topic="Algebra">
      <question>Algebra question E.</question>
    </question_body>
    <question_body id="Q3" type="numerical" marks="4" topic="Integration">
      <question>Integration question F.</question>
    </question_body>
    <question_body id="Q4" type="long_answer" marks="4" topic="Integration">
      <question>Integration question G.</question>
    </question_body>
  </paper>
</pyqs>"""


@pytest.fixture
def two_year_bank() -> list[Paper]:
    """A two-year, two-section bank: 3 questions in 2023, 4 in 2024."""

    return parse_paper_string(TWO_YEAR_BANK, "bank.xml")

