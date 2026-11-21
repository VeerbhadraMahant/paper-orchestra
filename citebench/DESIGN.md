# CiteBench-Survey: design plan (draft for approval)

Working name only. Status: proposal, nothing built. Date: 2026-11-21.

## 1. One-sentence pitch

A human-labeled benchmark of citations from published literature surveys, used to measure how well existing citation checkers judge (a) whether a cited source supports its sentence and (b) whether the sentence overstates the source, and to test whether LLM judges actually read the source or answer from memory.

## 2. Research questions

- **RQ1 Accuracy.** How accurate are existing claim-support checkers on real survey citations labeled by humans?
- **RQ2 Memory reliance.** Do LLM judges still say "supported" when given no source, or the wrong source? If yes, their verdicts partly come from memory, not evidence.
- **RQ3 Overclaiming.** Can checkers detect a sentence that is stronger or broader than its source (dropped hedge, widened scope, causal from correlational)?
- **RQ4 Evidence access.** How much accuracy is lost with abstract only vs full text?
- **RQ5 (optional, later).** Unsupported-citation rate in human-written surveys vs AI-written ones.

## 3. Why this is new (prior work checked 2026-11-21, abstracts/READMEs only)

| Work | What it covers | What it leaves open |
|---|---|---|
| sciwrite-lint, arXiv 2604.08501 (MIT, github.com/authentic-research-partners/sciwrite-lint) | Local claim-support + retraction + consistency linting; eval on 30 papers with injected errors, false positives adjudicated by an LLM | No human gold labels; flags unhedged causal language but not strength drift against the cited source |
| Skepthical benchmark, arXiv 2611.17052 (github.com/inigozubeldia/skepthical-benchmark) | 357 injected errors (incl. citations) in 30 astro/ML papers; 12 reviewer systems | Injected errors only; notes ML models "appear to know the literature", which is our RQ2, but does not test it directly |
| Academic Research Skills plugin v3.8 | Opt-in claim audit; 25-tuple synthetic gold set | README states no live-judge calibration yet |
| CiteCheck 2605.27700, CiteAnchor 2610.30355, refchecker | Existence and metadata of references | Not claim support |
| SciFact (allenai/scifact) | Claims vs abstracts, SUPPORT/REFUTE | Not citing sentences in papers; abstracts only |

Our gap: human-labeled survey citations, an explicit memory-reliance test, and source-relative overclaiming. Before submission, re-run the prior-work scan and read these papers in full.

## 4. Dataset

### 4.1 Corpus
- 8 to 12 open-access literature surveys with arXiv LaTeX source (easy, exact sentence extraction), across the broader ML area (decided 2026-11-21). Spread across subfields (e.g. LLMs, vision, RL, generative models, ML privacy) so results are not one niche.
- Selection rule written down before sampling (venue, year range, citation-dense, LaTeX available).
- Note: Skepthical found models "know" ML literature well, so ML is the domain where memory reliance (RQ2) is most likely to show up. That makes RQ2 more interesting here, not less.
- The author's own survey is used only as a dev/pilot set, never in the test set.

### 4.2 Units
- One unit = (citing sentence, one cited reference, retrieved source text, source access level).
- Multi-cite sentences are split per reference.
- Stratified sample by citation role (evidence, method, context) so that "context" cites do not dominate.

### 4.3 Labels
- **Support:** supported / partially supported / not supported / contradicted / cannot check (source unavailable).
- **Strength:** matches source / overstated / understated, with the type (hedge dropped, scope widened, causal claim, number changed).
- **Evidence span:** the passage in the source that decides the label.
- Written annotation guidelines, piloted on 30 dev units.

### 4.4 Annotation
- Target 200 natural units, all labeled by the author.
- Reliability, in order of preference:
  1. A second person (classmate with ML background) independently labels a 50-unit overlap subset. Report Cohen's kappa on it; adjudicate disagreements.
  2. If nobody is available: the author re-labels the same 50 units after at least two weeks without looking at the first labels (intra-rater agreement). Weaker; report it as such.
  - Do not use an LLM as the second annotator: the benchmark tests LLM judges, so that would be circular.
- Rough effort (estimate, to be measured in the pilot): several minutes per unit, since each needs the source read.

### 4.5 Planted set
- Take human-confirmed "supported" units and perturb them in controlled ways: wrong paper swapped in, number changed, hedge removed, scope widened, negation. About 40 to 50 per type.
- Ground truth is known by construction, so this set is cheap and large.

### 4.6 Release and copyright
- Release sentences, reference IDs (DOI/arXiv), labels, evidence-span offsets and a fetch script. Do not redistribute full source texts.

## 5. Systems compared

1. Existence-only check (refchecker or the PaperOrchestra-style Semantic Scholar match): baseline that ignores content.
2. Single-prompt LLM judge, at three model sizes (Haiku, Sonnet, Opus), run as Claude Code subagents.
3. Free local open-weights judge on the RTX 4060 (8 GB), e.g. a 7B to 8B model at 4-bit via Ollama or llama.cpp. Adds a second model family at zero cost and is fully reproducible (pinned weights).
4. sciwrite-lint (optional). Its README assumes 16+ GB VRAM and WSL2; the RTX 4060 is the right generation (Ada, FP8) but has 8 GB. Try a reduced config; if it cannot run, drop it and say so in the paper.
5. Academic Research Skills claim audit (`ARS_CLAIM_AUDIT=1`).
6. Our minimal harness (below), used mainly to run conditions consistently, not as a competing product.

## 6. Experiments

- **E1 (RQ1):** per-class precision/recall, macro-F1, and calibration error on the 200 human-labeled units. Bootstrap 95% CIs; McNemar tests between systems.
- **E2 (RQ2):** each judge under four conditions: correct source, no source, related-but-wrong source, shuffled source. Memory-reliance score = rate of "supported" when the source cannot justify it. Compare well-known vs obscure cited papers (proxy: citation count).
- **E3 (RQ4):** abstract-only vs full text, same units.
- **E4 (RQ3):** detection rate per perturbation type on the planted set; false-positive rate on unperturbed copies.
- **E5:** cost and time per claim for each system.
- Protocol and analysis plan fixed in a PROTOCOL.md before running the test set, with any deviation logged (same practice as the pilot experiment).

## 7. Harness (small Claude Code plugin + Python package)

- `extract`: .tex + .bib to units (deterministic Python, with tests).
- `fetch`: open-access full text and abstract per reference; records access level; cached by hash.
- `judge`: runs a judge under a named condition; logs prompt, model ID, output.
- `eval`: metrics, CIs, tables.
- Skills/commands wrap these for Claude Code use.
- Budget is zero (decided 2026-11-21): Claude judges run as Claude Code subagents on the author's existing plan; local judges run on the RTX 4060. No paid APIs.
- Consequences to handle: (a) plan usage limits, so judge runs are batched and resumable from a cache; (b) subagent outputs are not bit-reproducible, so every call logs model ID, date, prompt hash and output, and the paper reports this as a limitation; (c) fetching uses only free sources (arXiv, Semantic Scholar without a key, OpenAlex, Unpaywall, PubMed Central).

## 8. Milestones (rough estimates, to be revised after the pilot)

1. Guidelines + extractor + fetcher; pilot 30 dev units with two annotators.
2. Full 200-unit annotation + planted set.
3. Run E1 to E5.
4. Write-up (workshop paper or tech report) and release.

## 9. Risks

- Annotation time is the main cost; the pilot will measure it.
- Paywalled sources reduce full-text coverage; report it, do not hide it.
- Model versions change; pin and log model IDs.
- Prior work in this area is moving fast (several 2026 papers); re-scan before writing up.
- Competes for time with the honors paper.

## 10. Decisions (answered 2026-11-21)

1. Domain: broader ML area.
2. Second annotator: open. Try to recruit one person for the 50-unit overlap; fallback is intra-rater re-labeling (section 4.4).
3. Repository: author will fork a GitHub repo and build there (assumed: a fork of google-research/paper-orchestra, with this project in its own top-level folder; to confirm).
4. Judges: Claude Code subagents plus free local models; zero budget.
5. No advisor yet. Treat it as an independent project aimed at a workshop paper or technical report; revisit once an advisor is found.

Still open: who the second annotator is; confirmation of which repo is forked; GitHub username for the fork (author does the fork themselves).
