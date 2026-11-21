# CiteBench protocol

Version 0.1 (draft), 2026-11-22. Written before any test unit has been sampled, labeled or judged. Source of truth for design intent: `DESIGN.md`. Where this file and `DESIGN.md` differ, the difference is flagged, not silently resolved. Reading time: about 10 minutes.

Items marked `[TO CONFIRM: ...]` are proposals or open decisions. They must be settled and logged before the step they affect.

## 1. Scope and research questions

A human-labeled benchmark of citations from published ML literature surveys, used to measure how well existing citation checkers judge (a) whether a cited source supports its sentence and (b) whether the sentence overstates the source, and to test whether LLM judges use the source or answer from memory.

- RQ1 Accuracy. How accurate are existing claim-support checkers on real survey citations labeled by humans?
- RQ2 Memory reliance. Do LLM judges still say "supported" when given no source, or the wrong source? If yes, their verdicts partly come from memory, not evidence.
- RQ3 Overclaiming. Can checkers detect a sentence that is stronger or broader than its source (dropped hedge, widened scope, causal from correlational)?
- RQ4 Evidence access. How much accuracy is lost with abstract only vs full text?
- RQ5 (optional, later). Unsupported-citation rate in human-written surveys vs AI-written ones. Not covered by this protocol; it would need its own addendum.

These are questions, not hypotheses. No expected direction is claimed.

## 2. Corpus selection

Target: 8 to 12 open-access literature surveys with arXiv LaTeX source, across the broader ML area and spread over subfields (for example LLMs, vision, RL, generative models, ML privacy). The rule is written here before any survey is sampled from.

Inclusion criteria (proposals):
- Self-described survey, review or systematic review of an ML topic, posted on arXiv with LaTeX source downloadable. (from DESIGN)
- Citation-dense with a .bib or .bbl that maps keys to bibliographic data. (from DESIGN)
- Year range: `[TO CONFIRM: for example surveys first posted 2023 to 2026]`.
- Minimum number of references: `[TO CONFIRM: for example at least 100]`.
- Venue requirement: `[TO CONFIRM: arXiv-only is allowed, or require a peer-reviewed venue]`.
- A redistribution licence on the arXiv record that permits quoting sentences with attribution: `[TO CONFIRM: which arXiv licences qualify; check each survey's licence before inclusion]`.

Exclusion criteria (proposals):
- Surveys without usable LaTeX (PDF only, or source that cannot be compiled or parsed into sentences).
- The author's own survey (dev set only, section 3).
- Surveys written mainly by an AI system, if this can be determined from the paper. `[TO CONFIRM: how this is determined]`
- Surveys whose subfield is already covered by two selected surveys, to keep the spread. `[TO CONFIRM]`

Selection procedure: `[TO CONFIRM: how candidates are listed (for example an arXiv search for "survey" in cs.LG, cs.CL, cs.CV, cs.AI by date) and how the final 8 to 12 are drawn from them (random with a fixed seed within each subfield, or by hand with reasons logged)]`. Whatever is chosen is fixed before extraction and the candidate list is stored with the repository.

## 3. Sampling plan

| Set | Size | Rule |
|---|---|---|
| Dev set | 30 units for the pilot (DESIGN 4.3) | From the author's own survey. Used to pilot and revise the guidelines. Never used in the test set or in any reported test result. |
| Natural test set | 200 units | Stratified by citation role (below), drawn from the selected surveys. |
| Reliability subset | 50 units | Drawn from the 200 natural units, by a fixed seed, stratified by role. |
| Planted set | about 40 to 50 per perturbation type | Built from human-confirmed supported units (section 5). |

Stratification. DESIGN 4.2 names three strata (evidence, method, context). The guidelines use six roles (evidence, method, dataset_or_tool, context_or_background, attribution_of_idea, contrast). `[TO CONFIRM: whether the six roles are sampled as six strata, or merged into three for sampling; the per-stratum quota; how roles are assigned before labeling, since the author's label is the first source of the role]`. Proposal: assign provisional roles by a keyword rule or by hand for sampling, and use the annotator's recorded `citation_role` for analysis, reporting both when they differ.

Other sampling rules:
- Each unit is one (sentence, one reference) pair; multi-cite sentences are split (DESIGN 4.2). `[TO CONFIRM: cap on units per survey and per sentence, so that one survey or one long multi-cite sentence does not dominate]`
- Units whose source cannot be retrieved are kept in the natural set with access level `none` and labeled `cannot_check`. `[TO CONFIRM: whether the 200 target counts units before or after fetching, and whether `none` units count towards 200]`. The access level distribution is reported either way.
- Seed for all random draws is recorded in the repository before sampling.
- No unit is looked at by a system run, and no test label is inspected, before the guidelines are frozen at version 1.0.

## 4. Annotation and reliability

Annotation follows `ANNOTATION_GUIDELINES.md`. The author labels all 200 natural units. Label record fields are defined in the guidelines (section 9).

Reliability, in order of preference (DESIGN 4.4):
1. A second annotator (classmate with ML background) independently labels the 50-unit reliability subset. Report Cohen's kappa on the support label, on the strength label, and on the citation role, with the disagreement counts. Disagreements are discussed and adjudicated. Both the original labels and the adjudicated labels are kept. `[TO CONFIRM: who the second annotator is; adjudication rule when they do not agree; whether the adjudicated label or the author's first label is used in the main analysis]`
2. If nobody is available: the author re-labels the same 50 units at least two weeks after finishing the first pass, without access to the first labels, and reports intra-rater kappa. This is weaker evidence of reliability and is reported as such.

Kappa reporting. Cohen's kappa is computed on the 50 units; because some classes will be rare, per-class agreement counts are also shown. `[TO CONFIRM: whether to also report weighted kappa for ordered labels, and a bootstrap CI for kappa]`. No threshold for "acceptable" agreement is pre-set; the value is reported with its interval and interpreted in the text.

No LLM is used as an annotator, as an adjudicator, or to pre-fill labels. The benchmark evaluates LLM judges; using one to produce or fix the gold labels would make the evaluation circular. LLM output is also not shown to annotators.

Time per unit is logged (`time_spent_sec`) and reported.

## 5. Planted set

Purpose: controlled test of overclaim and mismatch detection (RQ3, RQ2 partly). Ground truth is known by construction.

Rule: perturbations are applied only to units that the human annotator labeled `supported` (strength `matches`) with confidence at least `[TO CONFIRM: 2]`, in the natural test set or `[TO CONFIRM: in additional human-confirmed units from the selected surveys]`. They are never applied to a unit that is `not_supported`, `contradicted`, `partially_supported`, `cannot_check` or overstated. Each perturbation is applied to a copy; the original unit stays in the natural set.

Perturbation types (from DESIGN 4.5), about 40 to 50 each:

| Type | How it is applied | Expected checker verdict |
|---|---|---|
| wrong_paper | Replace the cited source text with the text of another paper from the same survey that the author has confirmed does not support the claim. | not supported |
| number_changed | Change a figure in the sentence to a different value, stronger than the source. | overstated or contradicted |
| hedge_removed | Delete or flatten a hedge ("may", "in some cases") that the source also hedges. | overstated |
| scope_widened | Widen the subject or the setting ("on dataset X" to "on all datasets"). | overstated |
| negation | Negate the claim. | contradicted |

DESIGN lists these five. RQ3 and the strength labels also mention causal from correlational; `[TO CONFIRM: add causal_from_correlational as a sixth planted type, applicable only to units whose source reports an association]`.

Construction rules:
- Applicability filter first: only units where the type can be applied (a number to change, a hedge to remove, a scope to widen) are eligible. `[TO CONFIRM: how many eligible units are expected; DESIGN does not say whether the 40 to 50 per type must be distinct units, and the 200 natural units may yield fewer than 50 eligible supported units for some types, in which case the plan is either to reuse a unit across types or to label extra units]`.
- Edits are made by hand by the author, or by a fixed script, and each edit is reviewed by the author. Not by an LLM. `[TO CONFIRM]`
- Each perturbed sentence is checked to be grammatical and to carry exactly one change.
- For wrong_paper, the author confirms that the swapped source does not support the claim. Otherwise it is discarded.
- Each planted unit stores the unit_id of its parent, the type, the original and the perturbed sentence, and the edit made.
- Unperturbed copies of the same units are used for the false-positive measure (E4).

## 6. Systems and conditions

Systems (DESIGN 5):
1. Existence-only check (refchecker or a Semantic Scholar match). Baseline that ignores content.
2. Single-prompt LLM judge at three sizes (Haiku, Sonnet, Opus), run as Claude Code subagents.
3. Local open-weights judge on the RTX 4060 (8 GB), for example a 7B to 8B model at 4-bit via Ollama or llama.cpp. `[TO CONFIRM: the exact model and weights file, pinned by hash]`
4. sciwrite-lint (optional). Reduced configuration; if it cannot run on the 8 GB GPU, it is dropped and the paper says so.
5. Academic Research Skills claim audit (`ARS_CLAIM_AUDIT=1`).
6. A minimal harness, used to run the conditions consistently, not as a competing system.

Output mapping. Each system's output is mapped to the label set before scoring. `[TO CONFIRM: the mapping from each system's native output (for example the existence check returns only a match) to the five support labels and the strength label, written down before the first test run; systems that cannot output a label are scored on the subset of metrics that apply and this is stated]`.

Memory-reliance conditions (E2, DESIGN 6). Each judge is run under four conditions on the same units:
1. correct source: the unit's own source text.
2. no source: the sentence and reference metadata only.
3. related-but-wrong source: a paper related to the claim's topic but not the cited one. `[TO CONFIRM: how it is chosen, for example the nearest other cited paper in the same survey by embedding similarity or by the author's choice, and a check that it does not support the claim]`
4. shuffled source: the source text of another, randomly chosen unit. `[TO CONFIRM: the seed, and whether the pairing excludes sources from the same survey]`

Source-access conditions (E3, RQ4): abstract only versus full text, on the same units that have full text. Units without full text are excluded from this comparison, and the number excluded is reported.

Prompts. One prompt per judge role, fixed and committed before the first test run. `[TO CONFIRM: prompt wording; whether few-shot examples are used, and if so that they come only from the dev set]`

## 7. Metrics and analysis plan

All analyses below are fixed now. Anything added later is labeled exploratory.

- **E1 (RQ1).** On the natural test set: per-class precision, recall and F1 for the five support labels; macro-F1; calibration error for systems that give a confidence (`[TO CONFIRM: expected calibration error with how many bins, or Brier score; how confidences are extracted from systems that give none]`). 95% bootstrap CIs by resampling units (and, where units cluster by survey, `[TO CONFIRM: resampling surveys instead of units, or both]`). Number of resamples (proposal): `[TO CONFIRM: 10,000]`. Systems are compared pairwise with McNemar's test on per-unit correctness `[TO CONFIRM: correctness defined as exact support-label match; a second version on the collapsed label supported/partially_supported vs the rest]`. `[TO CONFIRM: multiple-comparison correction across system pairs]`.
- **E2 (RQ2).** Memory-reliance score for a judge: among units where the given source cannot justify "supported" (conditions no source, related-but-wrong source, shuffled source), the fraction on which the judge outputs `supported` (or the equivalent). Proposal: also report the fraction `supported` under the correct-source condition for comparison. Compare well-known and obscure cited papers, using citation count as a proxy. `[TO CONFIRM: the citation count source (for example Semantic Scholar or OpenAlex, with the retrieval date) and the split point between well-known and obscure]`. The related-but-wrong source can still occasionally support a claim, so the author's check in section 6 applies.
- **E3 (RQ4).** Accuracy and macro-F1 with abstract only versus full text, with a paired bootstrap difference and a McNemar test. Because abstract-only gold labels follow the abstract-only rule in the guidelines, the comparison is made against the gold label from full text, on units with full text. `[TO CONFIRM]`
- **E4 (RQ3).** Detection rate per perturbation type on the planted set. False-positive rate on the unperturbed copies. CIs as in E1. Detection means the system outputs a verdict different from `supported` / `matches`. `[TO CONFIRM: the exact detection rule per type]`
- **E5.** Cost and time per claim for each system: wall-clock time, number of calls, tokens where available. Plan usage is reported in calls and tokens, not money, because the budget is zero.
- **Reliability.** Cohen's kappa (section 4).

Note on numbering: DESIGN lists E3 as RQ4 and E4 as RQ3. This protocol keeps DESIGN's numbering.

Missing outputs (a system fails to answer, a call times out) are counted as errors in the primary analysis, with the count reported; a second analysis excluding them is reported next to it. `[TO CONFIRM]`

## 8. Reproducibility and zero-budget constraints

- Budget is zero. Claude judges run as Claude Code subagents on the author's existing plan; local judges run on the RTX 4060. No paid APIs.
- Fetching uses only free sources: arXiv, Semantic Scholar without a key, OpenAlex, Unpaywall, PubMed Central. Source text is cached by hash; the access level and the matched title are recorded per reference.
- For every judge call, log: system, model ID as reported by the runtime, date and time, condition, prompt hash, the unit_id and the raw output. Calls are cached so that a rerun does not change recorded results. Runs are batched and resumable.
- Subagent outputs are not bit-reproducible and the model version behind an alias can change. Therefore each result is tied to the logged model ID and date, and the write-up states this as a limitation. `[TO CONFIRM: whether each judge is run once or several times per unit; DESIGN does not say. If several, state the count and how votes are combined]`
- Limits of Claude Code subagents: no control over sampling parameters (`[TO CONFIRM: whether temperature and other settings can be set or only observed]`), shared plan usage limits that may stop a run midway, hidden system prompts and tool use that differ from a bare API call, and possible changes in the underlying model during the study. Judge subagents are run without access to the web or to the repository's labels. `[TO CONFIRM: how this isolation is enforced and checked]`
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

Release: citing sentences (with the survey's arXiv id and licence), reference identifiers (DOI or arXiv id), labels, evidence-span offsets and a fetch script that retrieves source texts from their original open sources. Do not redistribute full source texts or the cached text of cited works. `[TO CONFIRM: whether evidence span text is released or only offsets; whether quoting the cited sentences is within each survey's licence (section 2)]`. The released data has no personal data other than the annotator codes. `[TO CONFIRM: whether the second annotator consents to being listed or coded]`

## 11. Deviation log

Any change to this protocol after a test unit has been sampled or any system has been run on the test set is recorded here, with whether it was decided before or after seeing results.

| Date | Deviation | Reason | Decided before or after seeing results |
|---|---|---|---|
| 2026-11-22 | Version 0.1 created | Initial draft | Before |
