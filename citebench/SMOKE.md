# Smoke runs (real data, 2026-11-22)

Not part of the benchmark: checks that the pipeline works on real LaTeX and live free APIs. Inputs and outputs live in `.smoke/` (git-ignored, never committed).

## Extractor on arXiv 2303.18223 (A Survey of Large Language Models)

`python -m citebench.extract .smoke/src --survey-id 2303.18223 --out .smoke/units.jsonl`

| Stat | Value |
|---|---|
| files read | 21 |
| sentences with citations | 946 |
| units | 2150 |
| distinct keys | 1003 |
| keys missing from bibliography | 3 |
| unresolved includes | 0 |
| cites in skipped regions (tables, figures, captions, headings) | 320 |
| unterminated environments | 0 |
| unmatched cite tokens | 0 |
| duplicate bib keys | 3 |

Observation: 320 citations sit in skipped regions, mostly large comparison tables. They are excluded by design (DESIGN 4.2 units are prose sentences); worth stating in the paper.

## Fetcher

1. First 15 references in file order (the survey's historical citations, 1987 to 2007): full_text 1, abstract 13, none 1 (missing_bib_entry). Failures were publisher 403s and HTTP 202 challenge pages. Not representative of the corpus.
2. Random 30 references (seed 20261122): full_text 29 (arXiv 27, OpenAlex 2), abstract 1, none 0. Minimum title match score 94. Six cached texts checked by hand against their .bib titles: all correct papers.

Implication for RQ4: full-text coverage for recent ML references is high via arXiv; older or publisher-only references fall back to abstracts. Report coverage by publication year.

## Judge harness on a local dev survey (2026-11-22)

The dev survey is unpublished and stays in git-ignored `.work/dev/`; nothing from it is committed. It is not part of the benchmark and is never used for test numbers.

- 30 dev units (evidence 12, method 9, context 9; 28 with full text, 2 abstract only).
- 20 smoke calls (5 units x 4 conditions) through the `file` backend, answered by a Claude Code Haiku subagent: 0 parse errors. Every `no_source` and `wrong_related` call returned `cannot_check` (10 of 10). `correct`: 2 supported, 1 partially supported, 2 cannot_check. `abstract_only`: 4 cannot_check, 1 partially supported.
- The smoke run exposed multiple `[CITE]` markers in sentences with several citation commands; fixed by marking non-target commands `[OTHER]` (D35).
- `shuffled` cannot run on a single survey (no donor from another survey): the harness warns, as designed.
- A synthetic gold file ran end to end through `citebench.evaluate`. Those numbers check the code path only and mean nothing.
- Not run: `claude_cli` (the headless CLI login has expired) and `ollama` (no model installed).

## Corpus run (2026-11-22)

10 surveys drawn per D7/D7a (`data/corpus/selected.json`), e-prints fetched into `.work/eprints/`, units extracted into `.work/units/` (4094 units in total).

| Survey | files | sentences with citations | units | distinct keys | missing keys | cites in skipped regions |
|---|---|---|---|---|---|---|
| 2203.15935 | 1 | 234 | 539 | 315 | 0 | 170 |
| 2204.08570 | 7 | 409 | 659 | 282 | 1 | 251 |
| 2209.00796 | 11 | 290 | 644 | 386 | 0 | 203 |
| 2212.09597 | 10 | 119 | 240 | 166 | 0 | 301 |
| 2302.10637 | 1 | 215 | 403 | 256 | 0 | 119 |
| 2306.13549 | 17 | 192 | 452 | 206 | 0 | 29 |
| 2401.00625 | 12 | 269 | 366 | 295 | 0 | 10 |
| 2502.05151 | 14 | 221 | 408 | 300 | 0 | 73 |
| 2506.17518 | 1 | 151 | 197 | 157 | 0 | 1 |
| 2605.17131 | 23 | 76 | 186 | 132 | 0 | 57 |

No unresolved includes, unterminated environments or unmatched cite tokens in any survey. 2605.17131 needed an extractor fix (main file whose `\documentclass` sits in an `\input`ed header).

Candidates: 400 (evidence 160, method 120, context 120; 40 per survey), citing 371 distinct references.

Fetch of the 371 references: first pass full_text 289, abstract 42, none 40; a second pass over the 17 references that hit HTTP 429 recovered 1 full text and 1 abstract (PROTOCOL deviation log). Final: full_text 290, abstract 43, none 38. Sources: arXiv 273, Semantic Scholar 55, OpenAlex 24, arXiv title search 3, Europe PMC 2 (first pass). Coverage by year is in `STATUS_2026-11-22.md`.

Final sample (D10): 200 units, evidence 80, method 60, context 60; full text 173, abstract 27; no unmet quota. Manifest: `data/sample/manifest_v1.json` (offsets and keys only, no sentence text).
