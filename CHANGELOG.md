# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-09-26

First working release: a dependency-free command line tool for analysing
XML/LaTeX previous-year question banks.

### Added

- `pyqs` command line interface with `summary`, `topics`, `types`, `marks`,
  `concepts`, `list`, `compare`, `trend`, `export` and `validate` sub-commands.
- Shared filter vocabulary: `--topic`, `--type`, `--year`, `--min-marks`,
  `--max-marks`, `--grep`, `--id`, repeatable and intersected.
- Output formats `table`, `json`, `csv` and `md`, with automatic ASCII fallback on
  consoles that cannot encode box-drawing characters, and stable exit codes
  (`0` ok, `2` usage, `3` bad input, `4` nothing matched).
- Forgiving XML parser: namespaced elements and attributes, multiple `<paper>`
  sections per file, inherited paper metadata, metadata attribute aliases, nested
  `<parts>` with summed marks, `<options>` wrappers, and per-question warnings
  instead of hard failures.
- Analysis layer: per-topic and per-type distributions, marks histograms with
  inferred/undeclared buckets, concept frequency with tag/LaTeX/keyword sources
  and paper-spread counts, paper-vs-paper topic comparison, and year-on-year
  topic trends.
- `pyqs validate`, including `--strict`, for use as a CI gate.
- Public API: `pyqs.parse_paper`, `pyqs.parse_paper_string`, `pyqs.load_paper`,
  `pyqs.load_papers`.
- Seven example banks in `examples/`, documented in `examples/README.md`, plus a
  161-test suite covering the parser, concepts, analysis, rendering and CLI.
