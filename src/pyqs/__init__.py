"""pyqs - statistics and analysis for previous-year question (PYQ) banks."""

from __future__ import annotations

from pyqs.models import Option, Paper, Part, Question
from pyqs.parser import load_paper, load_papers, parse_paper_string
from pyqs.version import __version__

__all__ = [
    "Option",
    "Paper",
    "Part",
    "Question",
    "__version__",
    "load_paper",
    "load_papers",
    "parse_paper_string",
]
