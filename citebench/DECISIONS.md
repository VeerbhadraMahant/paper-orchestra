# Decisions log

Resolutions of the open `[TO CONFIRM]` items in PROTOCOL.md and ANNOTATION_GUIDELINES.md, made 2026-11-22 before any test data was seen. Decided by the orchestrating agent under the author's standing instruction to decide open choices and log them; the author can overturn any item, and a change made after test data is seen goes into the PROTOCOL deviation log instead.

Items marked **AUTHOR** still need the author.

## Corpus

- **D1 Year range:** surveys first posted on arXiv from 2022-01-01 to 2026-06-30 (recent enough to matter, old enough that cited works have settled metadata).
- **D2 Minimum references:** at least 100, by Semantic Scholar `referenceCount` (removes 2405.00314 from the current pool).
- **D3 Venue:** arXiv-only surveys are allowed; venue is recorded as a covariate.
- **D4 Licence:** any arXiv licence is eligible for use. Citing-sentence text is released only for surveys under CC BY, CC BY-SA or CC0; for the others the release contains unit IDs, offsets and a script that regenerates the sentences from the arXiv source.
- **D5 AI-written surveys:** no reliable way to detect this, so the criterion is dropped and stated as a limitation.
- **D6 Subfield spread:** at most 2 surveys per subfield.
- **D7 Draw:** pool = CORPUS_CANDIDATES.md plus a top-up search for CV and RL using the same criteria. Draw 10 surveys: within each subfield, eligible candidates are ordered at random with seed 20261122 and taken in order until the subfield cap or total is reached. The draw script and its output are committed.

## Sampling

- **D8 Strata:** the six citation roles are merged into three sampling strata: evidence (evidence, contrast), method (method, dataset_or_tool), context (context_or_background, attribution_of_idea). Quotas: evidence 80, method 60, context 60. Strata are assigned by a provisional role classifier (sentence only, never shown to the annotator); the annotator's own role label is the one analysed.
- **D9 Caps:** at most 25 units per survey and 1 unit per sentence.
- **D10 The 200:** counted after fetching, among units with access level `full_text` or `abstract`. Units with access `none` are logged and counted separately but not annotated in the main set.

## Reliability

- **D11 Adjudication:** discussion to consensus; if none, the author's label stands with a note. The main analysis uses adjudicated labels on the 50 overlap units and the author's labels elsewhere.
- **D12 Kappa:** unweighted Cohen's kappa (labels are nominal) with a bootstrap 95% CI (1,000 resamples); per-class agreement counts shown.
- **AUTHOR A1:** who the second annotator is (or confirm the intra-rater fallback).
- **AUTHOR A2:** written consent from the second annotator to release their anonymised labels.

## Planted set

- **D13 Eligible units:** human label `supported` with strength `matches` and confidence at least 2, from the natural set. A unit may be used for several perturbation types (each planted copy is separate). If fewer than 40 are eligible for a type, extra units are drawn from the same surveys and labeled under the same guidelines, flagged `supplementary`.
- **D14 Types:** six: wrong_paper, number_changed, hedge_dropped, scope_widened, negation, causal_from_correlational (the last only where the source reports an association). Target 40 per type.
- **D15 Who edits:** the author, by hand, following a written recipe per type. No LLM writes perturbations (LLM-written edits could carry style cues that LLM judges detect for the wrong reason).

## Systems and conditions

- **D16 Local judge:** candidate Qwen3-8B at 4-bit (Q4_K_M GGUF) through llama.cpp or Ollama on the RTX 4060; fallback a 4B model if throughput is too low. The exact file is pinned by SHA-256 before the first test run. Temperature 0.
- **D17 Output mapping:** all LLM judges use the same output schema (support label, strength, overstatement types, confidence 1 to 3, evidence quote). Existence-only baseline: reference resolved with title match gives `supported` / `matches`, unresolved gives `not_supported`. sciwrite-lint and the ARS audit: their native verdicts are mapped by a table written after inspecting their outputs on the dev set only, and committed before the test run.
- **D18 Related-but-wrong source:** another reference from the same survey (same section preferred), excluding the unit's cocited keys, chosen as the highest TF-IDF cosine similarity between its abstract and the citing sentence. A random 20 of these pairs are checked by the author to confirm the wrong source does not in fact support the claim.
- **D19 Shuffled source:** source text of another unit from a different survey, assigned by a derangement with seed 20261122.
- **D20 Prompts:** zero-shot only in v1. One prompt per judge, committed before the first test run. Few-shot is out of scope.

## Metrics

- **D21 Calibration:** for systems that return a confidence (1 to 3): ECE with one bin per confidence level, plus Brier score on the binary outcome supported vs not.
- **D22 Bootstrap:** 10,000 resamples at the unit level (primary); a survey-level cluster bootstrap is reported as a sensitivity check.
- **D23 McNemar:** "correct" means the predicted support label equals the gold label (5-way). Holm correction across pairwise system comparisons.
- **D24 Well-known vs obscure:** Semantic Scholar `citationCount` of the cited paper at fetch time, split at the median of the analysed units.
- **D25 E3 gold:** the human label made with full text; units the annotator saw only as abstract are excluded from E3.
- **D26 Detection rule (E4):** for hedge_dropped, scope_widened, causal_from_correlational and number_changed: detected if support is not `supported` or strength is `overstated`. For wrong_paper and negation: detected if support is `not_supported` or `contradicted`.
- **D27 Missing outputs:** counted as errors in the primary analysis, with the count reported; an analysis excluding them is shown beside it (as proposed).

## Reproducibility

- **D28 Runs:** one run per judge, unit and condition; on a 50-unit subset, 3 runs per judge to estimate run-to-run variation.
- **D29 Sampling settings:** Claude Code subagents do not expose temperature; settings are observed and logged, not set. Local judge at temperature 0.
- **D30 Isolation:** Claude judges run as a dedicated subagent type with no tools (no web, no file access) that receives only the unit and the source text, so verdicts cannot come from browsing.

## Release

- **D31 Evidence spans:** offsets only, plus the fetch script; span text from cited papers is not redistributed.

## Added 2026-11-22 (before any test data was seen)

- **D8a Provisional role classifier:** a deterministic keyword and pattern rule set on the citing sentence (`citebench/sample.py`). It is a sampling heuristic only, never a measurement and never shown to the annotator. Its agreement with the annotator's role label is reported as a descriptive check, not used to filter units.
- **D32 Judge evidence:** judges do not receive whole papers (cached full texts reach about 270,000 characters, beyond an 8B local model's context, and all judges must see identical evidence). Evidence = the first passage of the source (treated as abstract and front matter) plus the top 5 passages by TF-IDF cosine similarity to the citing sentence, from chunks of about 1,200 characters with 200 characters of overlap. For access level `abstract` the evidence is the abstract only. This is a confound to state in the paper: a judge can miss support that sits outside the retrieved passages. The rate at which the annotator's evidence span falls inside the retrieved passages is reported as a retrieval-recall check.
- **D33 Judge backends:** three interchangeable backends in `citebench/judge.py`: the Claude CLI in print mode with no tools (`--tools ""`, `--strict-mcp-config`, `--no-session-persistence`), a local model through Ollama's HTTP API at temperature 0, and a file backend that writes prompts and reads replies so an orchestrating session can run subagent judges. Every call logs backend, model, prompt version, prompt SHA-256 and timestamps.
- **D34 Tooling status at time of writing:** the headless Claude CLI login had expired and Ollama had no model installed, so no judge run on real units has happened yet. The harness was tested with fake backends and smoke-tested through the file backend only.

## Annotation guidelines

- **G1** Strength is not recorded for `contradicted` (stays null), as drafted.
- **G2** Abstract-only units labeled `supported` stay in the main set, flagged by access level; RQ4/E3 uses only units with full text.
- **G3** Span offsets: exact match first; otherwise fuzzy match (partial ratio at least 90); if neither, offset is null and the unit is flagged for review.
- **G4** Pilot: the author labels the 30 dev units; if the second annotator is available, they label the same 30 independently.
- **G5** A sentence whose key number differs from the source beyond rounding is at most `partially_supported` (with strength `overstated`, type `number_changed`). Example 8 is corrected accordingly.

## DESIGN.md alignment

- 4.2 strata updated to the three merged strata of D8.
- Milestone 1 pilot wording aligned with G4.
- RQ5 is out of scope for v1 (no experiment tests it); kept as future work.
- 4.5 updated with D13 and D14.
