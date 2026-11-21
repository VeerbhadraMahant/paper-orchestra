# CiteBench protocol

Version 0.1 (draft), 2026-11-22. Written before any test unit has been sampled, labeled or judged. Source of truth for design intent: `DESIGN.md`. Where this file and `DESIGN.md` differ, the difference is flagged, not silently resolved. Reading time: about 10 minutes.

The open items of the first draft are resolved in `DECISIONS.md` (decision ids D1 to D31 are cited below). Two items still need the author and are marked `[AUTHOR: ...]`. Any later change goes to the deviation log (section 11).

## 1. Scope and research questions

A human-labeled benchmark of citations from published ML literature surveys, used to measure how well existing citation checkers judge (a) whether a cited source supports its sentence and (b) whether the sentence overstates the source, and to test whether LLM judges use the source or answer from memory.

- RQ1 Accuracy. How accurate are existing claim-support checkers on real survey citations labeled by humans?
- RQ2 Memory reliance. Do LLM judges still say "supported" when given no source, or the wrong source? If yes, their verdicts partly come from memory, not evidence.
- RQ3 Overclaiming. Can checkers detect a sentence that is stronger or broader than its source (dropped hedge, widened scope, causal from correlational)?
- RQ4 Evidence access. How much accuracy is lost with abstract only vs full text?
- RQ5 (out of scope for v1, future work). Unsupported-citation rate in human-written surveys vs AI-written ones. No experiment in this protocol tests it; it would need its own addendum.

These are questions, not hypotheses. No expected direction is claimed.

## 2. Corpus selection

Target: 8 to 12 open-access literature surveys with arXiv LaTeX source, across the broader ML area and spread over subfields (for example LLMs, vision, RL, generative models, ML privacy). The rule is written here before any survey is sampled from.

Inclusion criteria (proposals):
- Self-described survey, review or systematic review of an ML topic, posted on arXiv with LaTeX source downloadable. (from DESIGN)
- Citation-dense with a .bib or .bbl that maps keys to bibliographic data. (from DESIGN)
- Year range: surveys first posted on arXiv from 2022-01-01 to 2026-06-30 (D1).
- Minimum number of references: at least 100, by Semantic Scholar `referenceCount` (D2).
- Venue requirement: none. arXiv-only surveys are allowed; venue is recorded as a covariate (D3).
- Licence: any arXiv licence is eligible for use. Citing-sentence text is released only for surveys under CC BY, CC BY-SA or CC0; for the others the release contains unit IDs, offsets and a script that regenerates the sentences from the arXiv source (D4).

Exclusion criteria (proposals):
- Surveys without usable LaTeX (PDF only, or source that cannot be compiled or parsed into sentences).
- The author's own survey (dev set only, section 3).
- Surveys written mainly by an AI system: there is no reliable way to detect this, so this criterion is dropped and stated as a limitation (D5).
- Surveys whose subfield is already covered by two selected surveys, to keep the spread: at most 2 surveys per subfield (D6).

Selection procedure: the pool is `CORPUS_CANDIDATES.md` plus a top-up search for CV and RL using the same criteria. Ten surveys are drawn: within each subfield, eligible candidates are ordered at random with seed 20261122 and taken in order until the subfield cap or the total is reached. The draw script and its output are committed (D7). The procedure is fixed before extraction and the candidate list is stored with the repository.

## 3. Sampling plan

| Set | Size | Rule |
|---|---|---|
| Dev set | 30 units for the pilot (DESIGN 4.3) | From the author's own survey. Used to pilot and revise the guidelines. Never used in the test set or in any reported test result. |
| Natural test set | 200 units | Stratified by citation role (below), drawn from the selected surveys, counted among units with access level `full_text` or `abstract` (D10). |
| Reliability subset | 50 units | Drawn from the 200 natural units, by a fixed seed, stratified by role. |
| Planted set | 40 per perturbation type | Built from human-confirmed supported units (section 5). |

Stratification. The guidelines use six roles (evidence, method, dataset_or_tool, context_or_background, attribution_of_idea, contrast). For sampling they are merged into three strata: evidence (evidence, contrast), method (method, dataset_or_tool) and context (context_or_background, attribution_of_idea). Quotas: evidence 80, method 60, context 60. Strata are assigned by a provisional role classifier that sees the sentence only and is never shown to the annotator; the annotator's own `citation_role` is the one analysed (D8). Both are reported when they differ.

Other sampling rules:
- Each unit is one (sentence, one reference) pair; multi-cite sentences are split (DESIGN 4.2). At most 25 units per survey and 1 unit per sentence (D9).
- The 200 are counted after fetching, among units with access level `full_text` or `abstract`. Units with access level `none` are logged and counted separately but are not annotated in the main set (D10). The access level distribution is reported.
- Seed for all random draws is recorded in the repository before sampling.
- No unit is looked at by a system run, and no test label is inspected, before the guidelines are frozen at version 1.0.

## 4. Annotation and reliability

Annotation follows `ANNOTATION_GUIDELINES.md`. The author labels all 200 natural units. Label record fields are defined in the guidelines (section 9).

Reliability, in order of preference (DESIGN 4.4):
1. A second annotator (classmate with ML background) independently labels the 50-unit reliability subset. Report Cohen's kappa on the support label, on the strength label, and on the citation role, with the disagreement counts. Disagreements are discussed and adjudicated. Both the original labels and the adjudicated labels are kept. Adjudication is by discussion to consensus; if none is reached, the author's label stands with a note. The main analysis uses adjudicated labels on the 50 overlap units and the author's labels elsewhere (D11). `[AUTHOR: A1, who the second annotator is, or confirmation of the intra-rater fallback below]`
2. If nobody is available: the author re-labels the same 50 units at least two weeks after finishing the first pass, without access to the first labels, and reports intra-rater kappa. This is weaker evidence of reliability and is reported as such.

Kappa reporting. Cohen's kappa is computed on the 50 units; because some classes will be rare, per-class agreement counts are also shown. Kappa is the unweighted Cohen's kappa, because the labels are nominal, with a bootstrap 95% CI (1,000 resamples) (D12). No threshold for "acceptable" agreement is pre-set; the value is reported with its interval and interpreted in the text.

No LLM is used as an annotator, as an adjudicator, or to pre-fill labels. The benchmark evaluates LLM judges; using one to produce or fix the gold labels would make the evaluation circular. LLM output is also not shown to annotators.

Time per unit is logged (`time_spent_sec`) and reported.

## 5. Planted set

Purpose: controlled test of overclaim and mismatch detection (RQ3, RQ2 partly). Ground truth is known by construction.

Rule: perturbations are applied only to units that the human annotator labeled `supported` (strength `matches`) with confidence at least 2, in the natural test set. If fewer than 40 units are eligible for a type, extra units are drawn from the same surveys and labeled under the same guidelines, and flagged `supplementary` (D13). They are never applied to a unit that is `not_supported`, `contradicted`, `partially_supported`, `cannot_check` or overstated. Each perturbation is applied to a copy; the original unit stays in the natural set.

Perturbation types (six, D14), target 40 each. A unit may be used for several perturbation types; each planted copy is a separate unit (D13).

| Type | How it is applied | Expected checker verdict |
|---|---|---|
| wrong_paper | Replace the cited source text with the text of another paper from the same survey that the author has confirmed does not support the claim. | not supported |
| number_changed | Change a figure in the sentence to a different value, stronger than the source. | overstated or contradicted |
| hedge_dropped | Delete or flatten a hedge ("may", "in some cases") that the source also hedges. | overstated |
| scope_widened | Widen the subject or the setting ("on dataset X" to "on all datasets"). | overstated |
| negation | Negate the claim. | contradicted |
| causal_from_correlational | Turn an association reported by the source into a causal statement. Applicable only to units whose source reports an association. | overstated |

The sixth type, causal_from_correlational, follows RQ3 and the strength labels (D14).

Construction rules:
- Applicability filter first: only units where the type can be applied (a number to change, a hedge to remove, a scope to widen) are eligible. Units may be reused across types, and extra `supplementary` units are labeled when fewer than 40 are eligible for a type (D13).
- Edits are made by the author, by hand, following a written recipe per type. No LLM writes perturbations, because LLM-written edits could carry style cues that LLM judges detect for the wrong reason (D15).
- Each perturbed sentence is checked to be grammatical and to carry exactly one change.
- For wrong_paper, the author confirms that the swapped source does not support the claim. Otherwise it is discarded.
- Each planted unit stores the unit_id of its parent, the type, the original and the perturbed sentence, and the edit made.
- Unperturbed copies of the same units are used for the false-positive measure (E4).

## 6. Systems and conditions

Systems (DESIGN 5):
1. Existence-only check (refchecker or a Semantic Scholar match). Baseline that ignores content.
2. Single-prompt LLM judge at three sizes (Haiku, Sonnet, Opus), run as Claude Code subagents.
3. Local open-weights judge on the RTX 4060 (8 GB), candidate Qwen3-8B at 4-bit (Q4_K_M GGUF) through llama.cpp or Ollama; fallback a 4B model if throughput is too low. The exact file is pinned by SHA-256 before the first test run. Temperature 0 (D16).
4. sciwrite-lint (optional). Reduced configuration; if it cannot run on the 8 GB GPU, it is dropped and the paper says so.
5. Academic Research Skills claim audit (`ARS_CLAIM_AUDIT=1`).
6. A minimal harness, used to run the conditions consistently, not as a competing system.

Output mapping. All LLM judges use the same output schema (support label, strength, overstatement types, confidence 1 to 3, evidence quote). Existence-only baseline: a reference resolved by title match gives `supported` / `matches`, an unresolved one gives `not_supported`. For sciwrite-lint and the ARS audit, native verdicts are mapped by a table written after inspecting their outputs on the dev set only, and committed before the test run (D17). Systems that cannot output a label are scored on the subset of metrics that apply, and this is stated.

Memory-reliance conditions (E2, DESIGN 6). Each judge is run under four conditions on the same units:
1. correct source: the unit's own source text.
2. no source: the sentence and reference metadata only.
3. related-but-wrong source: another reference from the same survey (same section preferred), excluding the unit's cocited keys, chosen as the highest TF-IDF cosine similarity between its abstract and the citing sentence. A random 20 of these pairs are checked by the author to confirm that the wrong source does not in fact support the claim (D18).
4. shuffled source: the source text of a unit from a different survey, assigned by a derangement with seed 20261122 (D19).

Source-access conditions (E3, RQ4): abstract only versus full text, on the same units that have full text. Units without full text are excluded from this comparison, and the number excluded is reported.

Prompts. One prompt per judge, fixed and committed before the first test run. Zero-shot only in v1; few-shot is out of scope (D20).

## 7. Metrics and analysis plan

All analyses below are fixed now. Anything added later is labeled exploratory.

- **E1 (RQ1).** On the natural test set: per-class precision, recall and F1 for the five support labels; macro-F1; calibration for systems that return a confidence (1 to 3): expected calibration error with one bin per confidence level, plus the Brier score on the binary outcome supported vs not (D21). 95% bootstrap CIs by resampling units, 10,000 resamples; a survey-level cluster bootstrap is reported as a sensitivity check (D22). Systems are compared pairwise with McNemar's test on per-unit correctness, where correct means the predicted support label equals the gold label (5-way), with Holm correction across pairwise system comparisons (D23).
- **E2 (RQ2).** Memory-reliance score for a judge: among units where the given source cannot justify "supported" (conditions no source, related-but-wrong source, shuffled source), the fraction on which the judge outputs `supported` (or the equivalent). Proposal: also report the fraction `supported` under the correct-source condition for comparison. Compare well-known and obscure cited papers, using the Semantic Scholar `citationCount` of the cited paper at fetch time (with the retrieval date) as a proxy, split at the median of the analysed units (D24). The related-but-wrong source can still occasionally support a claim, so the author's check in section 6 applies.
- **E3 (RQ4).** Accuracy and macro-F1 with abstract only versus full text, with a paired bootstrap difference and a McNemar test. Because abstract-only gold labels follow the abstract-only rule in the guidelines, the comparison is made against the gold label from full text, on units with full text. The gold label is the human label made with full text; units the annotator saw only as abstract are excluded from E3 (D25).
- **E4 (RQ3).** Detection rate per perturbation type on the planted set. False-positive rate on the unperturbed copies. CIs as in E1. Detection rule (D26): for hedge_dropped, scope_widened, causal_from_correlational and number_changed, a perturbation is detected if the support label is not `supported` or the strength is `overstated`. For wrong_paper and negation, it is detected if the support label is `not_supported` or `contradicted`.
- **E5.** Cost and time per claim for each system: wall-clock time, number of calls, tokens where available. Plan usage is reported in calls and tokens, not money, because the budget is zero.
- **Reliability.** Cohen's kappa (section 4).

Note on numbering: DESIGN lists E3 as RQ4 and E4 as RQ3. This protocol keeps DESIGN's numbering.

Missing outputs (a system fails to answer, a call times out) are counted as errors in the primary analysis, with the count reported; a second analysis excluding them is reported next to it (D27).

## 8. Reproducibility and zero-budget constraints

- Budget is zero. Claude judges run as Claude Code subagents on the author's existing plan; local judges run on the RTX 4060. No paid APIs.
- Fetching uses only free sources: arXiv, Semantic Scholar without a key, OpenAlex, Unpaywall, PubMed Central. Source text is cached by hash; the access level and the matched title are recorded per reference.
- For every judge call, log: system, model ID as reported by the runtime, date and time, condition, prompt hash, the unit_id and the raw output. Calls are cached so that a rerun does not change recorded results. Runs are batched and resumable.
- Subagent outputs are not bit-reproducible and the model version behind an alias can change. Therefore each result is tied to the logged model ID and date, and the write-up states this as a limitation. Each judge is run once per unit and condition; on a 50-unit subset, 3 runs per judge are made to estimate run-to-run variation (D28).
- Limits of Claude Code subagents: no control over sampling parameters (subagents do not expose temperature, so settings are observed and logged, not set; the local judge runs at temperature 0, D29), shared plan usage limits that may stop a run midway, hidden system prompts and tool use that differ from a bare API call, and possible changes in the underlying model during the study. Judge subagents are run without access to the web or to the repository's labels. Claude judges run as a dedicated subagent type with no tools (no web, no file access) that receives only the unit and the source text, so verdicts cannot come from browsing (D30).
- Local judge: weights file hash, quantization, runtime version and decoding settings are recorded.
- Code, prompts, seeds, candidate list and logs are committed to the repository.

## 9. Limitations known in advance

- One main annotator; reliability is measured on a 50-unit subset only.
- 200 natural units give wide intervals for rare classes.
- Paywalled sources lower full-text coverage; the coverage rate is reported.
- Memory reliance is inferred from behavior under altered sources, not observed directly.
- The corpus covers 8 to 12 surveys and may not represent ML surveys in general.
- Prior work in this area is moving fast; the prior-work scan (DESIGN section 3) is re-run before writing up.

## 10. Data release and copyright

Release: citing sentences (with the survey's arXiv id and licence), reference identifiers (DOI or arXiv id), labels, evidence-span offsets and a fetch script that retrieves source texts from their original open sources. Do not redistribute full source texts or the cached text of cited works. Evidence spans are released as offsets only, plus the fetch script; span text from cited papers is not redistributed (D31). Citing-sentence text is released only where the survey's licence allows it (section 2, D4). The released data has no personal data other than the annotator codes. `[AUTHOR: A2, written consent from the second annotator to release their anonymised labels]`

## 11. Deviation log

Any change to this protocol after a test unit has been sampled or any system has been run on the test set is recorded here, with whether it was decided before or after seeing results.

| Date | Deviation | Reason | Decided before or after seeing results |
|---|---|---|---|
| 2026-11-22 | Version 0.1 created | Initial draft | Before |
| 2026-11-22 | Open items resolved per `DECISIONS.md` (D1 to D31, G1 to G5) | Settle the `[TO CONFIRM]` items | Before |
