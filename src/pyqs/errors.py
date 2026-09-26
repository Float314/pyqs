"""Exception hierarchy used across pyqs.

Every error the CLI raises on purpose derives from :class:`PyqsError` so the
command line front-end can turn it into a short message and a documented exit
code instead of a traceback.
"""

from __future__ import annotations


class PyqsError(Exception):
    """Base class for all expected pyqs failures."""

    exit_code = 1


class InputError(PyqsError):
    """A path could not be found, read, or expanded to question banks."""

    exit_code = 3


class ParseError(PyqsError):
    """An XML question bank could not be understood."""

    exit_code = 3

    def __init__(self, message: str, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


class SchemaError(ParseError):
    """The XML parsed cleanly but does not describe a question bank."""


class NoDataError(PyqsError):
    """The inputs parsed but produced nothing to report on."""

    exit_code = 4
