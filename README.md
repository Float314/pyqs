# pyqs

Statistics and analysis for XML/LaTeX previous-year question banks (PYQs).

`pyqs` reads a folder of exam XML, answers the questions you actually care about
("which topics eat the most marks?", "what changed between 2023 and 2024?"), and
prints a readable table — or machine-readable JSON, CSV or Markdown when you are
piping the result somewhere else.

* **No runtime dependencies.** Standard library only, Python 3.9+.
* **Forgiving parser.** Namespaces, `<paper>` sections, nested `<parts>`, type
  aliases and inherited metadata all work; anything odd becomes a *warning*, not
  a crash.
* **Honest about the data.** Every report shows question counts, mark totals and
  shares, and `pyqs validate` tells you exactly what a bank is missing.
* **Scriptable.** Stable exit codes, `--format json`, and one filter vocabulary
  shared by every command.

## Install

```bash
python -m pip install .
# or, for a checkout you intend to hack on
python -m pip install -e ".[dev]"
```

That gives you the `pyqs` command. Without installing, `python -m pyqs` works
from a source checkout.

## Quick start

```bash
pyqs summary examples                      # counts, marks, papers, warnings
pyqs topics examples --sort marks -l 10    # topic weight by marks
pyqs types examples -f json                # machine-readable question mix
pyqs compare examples/jee_main_2023.xml -a examples/jee_main_2024.xml
pyqs trend "examples/jee_main_*.xml"
pyqs validate examples                     # CI-friendly sanity check
```

Every command accepts files, directories (searched one level deep for `*.xml`)
and globs, in any combination. Filters can be repeated and intersected:

```bash
pyqs topics examples -t calculus -t "coordinate geometry" --min-marks 2
pyqs list examples --type mcq --year 2024 --width 100
```

## Commands

| Command | What it answers |
| --- | --- |
| `summary` | How many papers, questions and marks am I looking at? |
| `topics` | Which topics dominate question count and marks? |
| `types` | What is the MCQ / numerical / short-answer mix? |
| `marks` | How are marks distributed, and what does the histogram look like? |
| `concepts` | Which concepts appear, how often, and how widely spread are they? |
| `list` | Row-per-question listing for eyeballing or export. |
| `compare` | What appeared, shrank or disappeared between two sets of papers? |
| `trend` | How did each topic move year over year? |
| `export` | Write the parsed questions out as JSON, CSV or Markdown. |
| `validate` | Do these banks parse, and what warnings do they raise? |

Shared options: `-f/--format {table,json,csv,md}`, `--no-color`, `--width`,
`-t/--topic`, `--type`, `--year`, `--min-marks`, `--max-marks`, `--grep`,
`--id`. Run `pyqs COMMAND --help` for the per-command extras (`--sort`,
`--limit`, `--min-questions`, `--min-papers`, `--source`, `--full`, `--strict`,
`-o/--output`).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 2 | Usage error (bad flag or missing argument) |
| 3 | Bad input: missing file, unreadable or unparsable XML |
| 4 | The input parsed but nothing matched the filters |

`pyqs validate` is the one to wire into CI: it exits `3` on a broken file, and
with `--strict` it also exits `3` when any warning is raised.

## Input format

The parser is deliberately liberal, but a minimal bank looks like this:

```xml
<pyqs exam="JEE (Main)" year="2024" subject="Mathematics">
  <question_body id="Q1" type="mcq" marks="2" topic="Limits">
    <question>Evaluate $\lim_{x \to 0} \frac{\sin x}{x}$.</question>
    <option name="A">0</option>
    <option name="B">1</option>
    <answer>B</answer>
  </question_body>
</pyqs>
```

Accepted out of the box:

* **Container** — `<pyqs>`, `<paper>`, `<paper_set>`, `<exam>`, `<section>`;
  several papers may live in one file, and paper-level metadata is inherited by
  its questions.
* **Question element** — `<question_body>`, `<question>`, `<problem>`, `<pyq>`,
  `<exam_question>`.
* **Attributes** — `id`/`number`/`qid`, `type`, `marks`, `topic`/`chapter`/
  `subject`/`unit`. Unrecognised attributes are kept in `Question.extra`.
* **Children** — `<question>`/`<text>` for the stem, `<options>` wrappers,
  `<option>`/`<choice>`, `<answer>`/`<solution>`/`<key>`, `<assertion>`,
  `<reason>`, and nested `<part>` elements with their own `marks`.
* **Types** — aliases are normalised, so `MCQ`, `Multiple Choice (Single)` and
  `multiple_choice` all become `mcq`; unknown types are kept as-is.
* **Namespaces** — element and attribute namespaces are stripped before matching.
* **Concepts** — declared via `<concept>`, `<topics_concept>`, `<tags>` or
  `<keywords>`, and additionally inferred from an English keyword lexicon and
  from LaTeX commands. Declared tags win over LaTeX, which wins over keywords.

Marks are read from the question's own `marks` attribute when present, otherwise
they are summed over the part tree. Nothing is ever invented: a question with no
declared marks anywhere counts as zero and is reported as such.

## Development

```bash
python -m pytest                      # 161 tests
python -m ruff check .
python -m build                       # sdist + wheel
```

See `examples/README.md` for what each bundled example demonstrates and
`CHANGELOG.md` for the release history.

## License

MIT — see `LICENSE`.
