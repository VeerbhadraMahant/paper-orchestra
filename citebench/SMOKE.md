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
