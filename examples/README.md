# Example question banks

Seven small, hand-written banks. They are deliberately varied so that every
command, parser branch and concept source has something real to chew on — and
they are used by the test suite, so a change that breaks them breaks the build.

Every file carries a comment header explaining what it demonstrates and which
command to run against it.

| File | Papers | Questions | Marks | Demonstrates |
| --- | --- | --- | --- | --- |
| `example1.xml` | 1 | 8 | 16 | The original mixed bank: MCQs, numericals, a long answer with `<parts>`, and inline LaTeX. |
| `jee_main_2023.xml` | 1 | 12 | 24 | A full paper, `pyq`-style question elements, sections, and year-on-year comparison with 2024. |
| `jee_main_2024.xml` | 1 | 12 | 31 | The counterpart to 2023 — several new topics appear and some disappear. |
| `jee_advanced_2023.xml` | 1 | 10 | 34 | Heavy LaTeX, assertion/reason question types, and declared `<concepts>`. |
| `jee_advanced_2024.xml` | 1 | 9 | 28 | Nested `<parts>` with per-part marks and a question with no declared marks at all. |
| `multi_paper.xml` | 2 | 7 | 17 | Two `<paper>` sections in one file, each with its own year — the case for `pyqs trend`. |
| `schema_cookbook.xml` | 1 | 6 | 13 | Every parser edge: namespaced attributes, `<options>` wrappers, unknown types, and two deliberate warnings. |

## Things to try

```bash
# Overall shape, and the warnings the cookbook asks for
pyqs summary examples
pyqs validate examples

# Weight by marks rather than by question count
pyqs topics examples --sort marks

# Concepts: declared tags, then LaTeX, then the keyword lexicon
pyqs concepts examples
pyqs concepts examples --source tag -l 5
pyqs concepts examples --source latex

# What changed between two years
pyqs compare examples/jee_main_2023.xml -a examples/jee_main_2024.xml
pyqs trend "examples/jee_main_*.xml"

# Two papers in one file are two papers
pyqs summary examples/multi_paper.xml
pyqs trend examples/multi_paper.xml

# Machine-readable output for scripts
pyqs list examples --type mcq --year 2024 -f json
pyqs export examples -f md -o papers.md
```

## Totals

`pyqs validate examples` reports 8 papers, 64 questions and 163 marks across all
seven files, with 2 warnings, both from `schema_cookbook.xml`:

* a question with no `id`, so `Q4` is generated;
* a question with no options, answer or parts.

That is intentional: `pyqs validate --strict examples` exits `3` on those
warnings, which is exactly what a CI hook should do.
