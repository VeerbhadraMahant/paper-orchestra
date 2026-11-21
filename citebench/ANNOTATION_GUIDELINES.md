# CiteBench annotation guidelines

Version 0.1 (draft), 2026-11-22. Status: not yet piloted. Reading time: about 15 minutes.

You are judging two things per unit: does the cited source back up the sentence that cites it, and does the sentence say more than the source does. You are not judging whether the claim is true in the world, whether the paper is good, or whether the citation is the best one available. Only the source text counts.

## 1. What you see per unit

Each unit is one (sentence, one cited reference) pair. A sentence citing three papers gives three units, labeled separately.

| Field | Meaning |
|---|---|
| `unit_id` | Identifier. Copy it into your label record. |
| `sentence_text` | The citing sentence as plain text. Every citation command is replaced by `[CITE]`. |
| `sentence_latex` | The same sentence in the original LaTeX. Use it to see which `[CITE]` is which key, and for math or numbers the plain text lost. |
| `section` | Nearest section or subsection title of the survey. Context only. |
| `cite_key` | The reference you are judging. |
| `cocited_keys` | Other keys cited in the same sentence. They are not your target. |
| `reference` | Metadata from the survey's .bib: title, authors, year, venue, DOI, arXiv id. Can be empty if the key is missing from the .bib. |
| source text | The cached text of the cited work. |
| access level | `full_text`, `abstract` or `none`. This decides which labels are available (section 8). |

Check that the source text is really the cited work (title and authors match `reference`). If it is a different paper, record `cannot_check` and say so in `notes`.

## 2. Workflow

1. Read `sentence_text`, then `sentence_latex` to see where your `cite_key` sits.
2. Write down, in one line, the specific claim this sentence attributes to this cited work. If the sentence has several claims, split them and note which attach to your key.
3. Search the source for passages about that claim. Use search, but also read the nearby text: a result in a table or a limitation in a later paragraph can change the answer.
4. Choose the support label (section 3).
5. If the source is checkable and the claim is supported at least in part, choose the strength label (section 4).
6. Copy the evidence span(s) (section 5).
7. Choose the citation role (section 6), confidence and notes. Record the time spent (`time_spent_sec`).

Choose the role from the sentence alone, so that the support label does not influence it.

## 3. Support label (exactly one)

Judge the claim attributed to this cited work against the source text.

- **supported**: the source states the claim, or it follows from the source's text, tables or figures without outside knowledge or an extra inference step. Differences of wording do not matter.
- **partially_supported**: the source supports some of what the claim attributes to it, and another distinct part is absent from the source or differs from it. Typical cases: two claims in one sentence and the source backs one; the source backs the claim only in a narrower setting and the narrowing is a separate piece of content, not just a scope or hedge difference (see the rule of thumb below).
- **not_supported**: the source was readable in full, you searched for the claim and neighbouring wording, and the source neither states it nor implies it. The source does not say the opposite.
- **contradicted**: the source states something that conflicts with the claim (opposite direction, a number that cannot be reconciled, the source says the method fails where the sentence says it works).
- **cannot_check**: you cannot decide from the material provided: no source text (`none`), wrong paper, unreadable source text, abstract-only and the abstract is silent on the claim (section 8), or the claim may sit in a table or figure that was not extracted.

### Decision procedure (ask in order, stop at the first yes)

1. Is the source text missing, the wrong paper, or unreadable? Then `cannot_check`.
2. Is the access level `abstract` and the abstract does not address the claim? Then `cannot_check` (section 8).
3. Does the source state something that conflicts with the claim? Then `contradicted`. If the conflict touches only a minor part and another main part is supported, use `partially_supported`. Explain in `notes`.
4. Does the source support the whole claim attributed to this key? Then `supported`.
5. Does it support one or more distinct parts but not all? Then `partially_supported`.
6. Otherwise `not_supported`.

Rule of thumb for 5 versus 6: if you can name the part that is supported and quote it, it is `partially_supported`. If you cannot quote anything relevant, it is `not_supported`.

Key numbers (G5). If a number that is central to the sentence differs from the source beyond rounding (section 7), the label is at most `partially_supported`, with strength `overstated` and type `number_changed` when the sentence is stronger. Do not use `supported` in this case, even when the direction of the claim is right. Use `contradicted` only when the source's number reverses the direction of the claim or makes its qualitative conclusion false (the sentence says a method improves accuracy, the source reports a drop). A number in the right direction but with a different size is never `contradicted`: it is `partially_supported` as above.

Rule of thumb for 4 versus 5 when the source says less than the sentence: if the only difference is a hedge, a scope limit, or the strength of wording (the source finds the same effect but more cautiously), label `supported` and record the difference in the strength label. Use `partially_supported` only when a separate piece of content is missing.

## 4. Strength label

Fill this only when the support label is `supported` or `partially_supported`. For `not_supported`, `contradicted` and `cannot_check`, set `strength` to `null` and `overstatement_types` to `[]`. Strength is not recorded for `contradicted` units (G1).

Compare how strongly the sentence puts the claim with how strongly the source puts it.

- **matches**: same strength, scope, certainty and numbers (allowing rounding, section 7).
- **overstated**: the sentence is stronger, broader, more certain or more exact than the source.
- **understated**: the sentence is weaker or narrower than the source, for example it says "may help" where the source reports a clear result. Use this only when the difference is clear, not for ordinary caution.

If `overstated`, pick one or more types:

- **hedge_dropped**: the source qualifies the claim ("can", "in some cases", "suggests", "we hypothesise") and the sentence states it flatly.
- **scope_widened**: the source's result holds for a narrower set (one dataset, one model family, one language, one task, small models, a subset of cases) and the sentence states it for a wider set ("all", "in general", "models", "medical imaging" for one dataset).
- **causal_from_correlational**: the source reports an association, correlation or observational result, and the sentence says one thing causes, drives, or leads to the other.
- **number_changed**: a figure in the sentence differs from the source in a way rounding does not explain (different value, unit or baseline; "doubles" for a 30% gain) and the change makes the claim stronger. Write the two numbers in `notes`. A changed number that makes the claim weaker is not overstatement: record `understated` (still at most `partially_supported`, per section 3), or `contradicted` only under the direction rule in section 3.
- **certainty_inflated**: the sentence adds confidence or proof the source does not claim ("proves", "conclusively shows", "it is well established") where the source offers limited or preliminary evidence. When a specific hedge in the source was removed, also mark `hedge_dropped`.
- **other**: any other way the sentence is stronger than the source. Describe it in `notes`. Prefer a named type when one fits.

Mark every type that applies, not only the main one.

## 5. Evidence span

Copy the smallest passage or passages from the source text that decide your label, character for character. Do not paraphrase. Keep each span understandable on its own: include the full sentence, and a neighbouring sentence only if needed.

- `supported`, `partially_supported`: the passage(s) that support the claim. For `partially_supported`, also include a passage showing what is missing or different, if one exists.
- `contradicted`: the passage that conflicts with the claim.
- `overstated`: also include the passage with the hedge, scope limit, correlation wording or number you compared against.
- Several passages: list each as a separate string, in the order you rely on them. Use at most 4. If more are needed, keep the 4 most decisive and say so in `notes`.
- Table or figure: copy the caption and the relevant row or cell text as extracted, and write "table" or "figure" in `notes`.
- `not_supported`: there is no passage. Use `[]`. In `notes`, write what you searched for (terms, sections).
- `cannot_check`: use `[]` and put the reason in `notes`.

If the text is garbled and you cannot copy a span cleanly, copy it as it appears and add "garbled" to `notes`.

## 6. Citation role

What the sentence uses the citation for. Choose the one that best describes the role of this key in this sentence. These roles support the stratified sampling in DESIGN section 4.2.

- **evidence**: the cited work is offered as support for a factual or empirical claim ("Method A improves accuracy on X [CITE]").
- **method**: the sentence says that a method, model, algorithm or technique from the cited work is used, adopted, or described ("we follow the training recipe of [CITE]").
- **dataset_or_tool**: the cited work is the source of a dataset, benchmark, library, metric or software that is used or named.
- **context_or_background**: general background or common framing with no specific finding attached ("Diffusion models have attracted attention [CITE]").
- **attribution_of_idea**: the cited work is credited as the origin of a concept, term, or proposal ("The idea of X was introduced in [CITE]"; "X proposed Y").
- **contrast**: the cited work is mentioned to differ from, criticise, or be set against something ("Unlike [CITE], this approach does not need labels").

If two roles seem to fit, choose the one a reader would use the citation for, and note the other in `notes`.

## 7. Edge cases

**Multi-cite sentences.** Judge only the part of the sentence attributable to your key. Use `sentence_latex` to see the order of keys and how they are grouped.
- If each key supports a separate item ("A [CITE1], B [CITE2], and C [CITE3]"), judge only your item.
- If the claim is joint ("Several works show that X [CITE1, CITE2, CITE3]"), judge whether this source on its own supports X. Do not require one paper to support what the group supports together. If it supports X in its own right, `supported`. If it supports only a piece of X, `partially_supported`. If X is a trend that only makes sense across several papers, judge what this source adds to it and write "joint claim" in `notes`.
- Never use the co-cited sources to settle your key's label.

**The cited work is itself a survey.** A survey supports a claim if it states the claim, whether or not it cites its own sources for it. Write "cited work is a survey" in `notes`. If the sentence attributes a new result to the survey, check whether the survey presents it as original or as reviewed work.

**"e.g." lists and examples.** For "such as A [CITE1] and B [CITE2]", the claim for each key is that the paper is an example of the category. Judge whether the source belongs in that category, not whether it is the best example.

**Pointer citations.** "See [CITE] for details", "for a review, see [CITE]": the claim is that the source covers the topic. `supported` if the source substantially covers it, `not_supported` if the topic is not in it. Role is usually `context_or_background`. Write "pointer" in `notes`.

**Existence or proposal claims.** "X proposed Y", "[CITE] introduced Z": the claim is that the source proposes or introduces Y. `supported` if the source presents Y as its own contribution, even if Y was later renamed. If the source credits Y to earlier work, `not_supported`; if the source introduces a variant of Y, `partially_supported`. Role: `attribution_of_idea`.

**Rounded numbers.** A number matches if rounding the source's value to the sentence's precision gives the sentence's value (82.4 reported; "about 82" or "over 80%" in the sentence both match). A number that differs after rounding is `number_changed`. If the sentence gives a size without a number ("a large gain") and the source reports a small one, mark `other` and explain in `notes`.

**Paraphrase versus near-quote.** Both are fine for support. If the sentence copies the source's wording closely, label as usual and add "near-quote" in `notes`. This is for a later check, not a different label.

**Abstract-only sources.** See section 8.

**Garbled or partial extraction.** If the text has broken words, missing equations or lost tables, search for the claim in several wordings. If you find the passage, label as usual and note "garbled". If the claim could sit in a table or figure that was lost, use `cannot_check` with a note, not `not_supported`.

**Claim supported by a different version of the paper.** Judge the text you were given. If you know that another version says something different (for example the arXiv version differs from the published one), do not use that knowledge in the label. Put it in `notes`. If the `reference` metadata and the source text appear to be different versions and the difference changes the answer, use `cannot_check` and explain.

**Source restates other work.** If the source states the claim only as background attributed to other papers, it still counts as the source stating it. Add "restates other work" to `notes`.

**Unsure.** Choose your best label and set `confidence` to 1 or 2. `cannot_check` is for missing or unusable source material, not for hard cases.

**No outside knowledge.** If you know the cited work says something that is not in the provided text, the label follows the text. Note the mismatch in `notes`.

## 8. Access levels

- `full_text`: all labels are available. Read the whole source, not only the first match.
- `abstract`: the abstract may support a claim. Rules:
  - If the abstract states the claim: `supported`. The strength label applies to what the abstract says.
  - If the abstract conflicts with the claim: `contradicted`.
  - If the abstract does not mention the claim: `cannot_check`. Absence from an abstract is not evidence that the paper lacks the claim, because abstracts omit most details.
  - `not_supported` is not available at this access level.
  - `partially_supported` is available only when the abstract itself shows that the claim holds in part.
  - Write "abstract only" in `notes`.
- `none`: `cannot_check`, `strength` null. Such units are logged and counted separately and are not annotated in the main set (PROTOCOL section 3, D10).

Abstract-only units labeled `supported` stay in the main set, flagged by access level. The RQ4 comparison (E3) uses only units with full text (G2).

## 9. Record format

One JSON object per unit, one per line (JSONL).

```json
{
  "unit_id": "string",
  "annotator_id": "A1",
  "support": "supported",
  "strength": "overstated",
  "overstatement_types": ["hedge_dropped"],
  "citation_role": "evidence",
  "evidence_spans": ["string"],
  "confidence": 2,
  "time_spent_sec": 240,
  "notes": "string",
  "labeled_at": "2026-11-22T10:15:00Z"
}
```

| Field | Type and allowed values |
|---|---|
| `unit_id` | String, copied from the unit. |
| `annotator_id` | Short stable code for the annotator (for example `A1`, `A2`). For re-labeling by the same person, keep the code and write the round in `notes`. |
| `support` | `supported`, `partially_supported`, `not_supported`, `contradicted`, `cannot_check`. |
| `strength` | `matches`, `overstated`, `understated`, or `null` (section 4). |
| `overstatement_types` | List. Empty unless `strength` is `overstated`. Values: `hedge_dropped`, `scope_widened`, `causal_from_correlational`, `number_changed`, `certainty_inflated`, `other`. If `other` is used, `notes` must say what. |
| `citation_role` | `evidence`, `method`, `dataset_or_tool`, `context_or_background`, `attribution_of_idea`, `contrast`. |
| `evidence_spans` | List of strings copied from the source text, at most 4. Empty list when there is no passage. |
| `confidence` | Integer. 1 = guess, 2 = fairly sure, 3 = certain. |
| `time_spent_sec` | Integer seconds from opening the unit to saving the label. |
| `notes` | Free text. Required for `other`, `cannot_check`, `not_supported`, and any case flagged in section 7. Otherwise optional; use an empty string if there is nothing to add. |
| `labeled_at` | ISO 8601 UTC timestamp, written when the label is saved. |

Span offsets for the release (DESIGN section 4.6) are computed by script from the copied span text. Do not count characters by hand. The script tries an exact match first; otherwise a fuzzy match (partial ratio at least 90); if neither succeeds, the offset is null and the unit is flagged for review (G3).

## 10. Illustrative examples

All examples below are invented for teaching. The methods, papers and numbers do not exist and are not taken from any real work. The cited "papers" are fictional.

**Ex. 1: supported.**
Sentence: "Method A reduces memory use by about 30% [CITE]." Source passage (invented): "Method A lowers peak memory by 31% on our benchmark." Label: `supported`, strength `matches` (31 rounds to "about 30"). Span: the passage. Role: `evidence`.

**Ex. 2: partially_supported.**
Sentence: "The FooNet paper shows that FooNet is both faster and more accurate than the baseline [CITE]." Source (invented): "FooNet runs 2x faster than the baseline. Accuracy is comparable." Label: `partially_supported` (speed supported, "more accurate" not). Strength: `overstated`, type `other`, note "accuracy claim exceeds 'comparable'". Spans: both sentences.

**Ex. 3: not_supported.**
Sentence: "Method B has been shown to work on audio data [CITE]." The full text of the invented source discusses only image experiments and never mentions audio. Label: `not_supported`, strength `null`, spans `[]`, note "searched: audio, speech, waveform, spectrogram; sections 1 to 6".

**Ex. 4: contradicted.**
Sentence: "Method C improves robustness [CITE]." Source (invented): "Method C reduces robustness under distribution shift." Label: `contradicted`, strength `null`. Span: that passage.

**Ex. 5: cannot_check (abstract only).**
Sentence: "Method D needs no labeled data [CITE]." Access level `abstract`. The invented abstract says: "We propose Method D, a new training procedure for image models." It does not mention labels. Label: `cannot_check`. Note: "abstract only; abstract is silent". Do not use `not_supported`.

**Ex. 6: hedge_dropped.**
Sentence: "Method E improves accuracy on small datasets [CITE]." Source (invented): "In some of our small-data experiments, Method E may improve accuracy." Label: `supported`, `overstated`, `[hedge_dropped]`. Span: the quoted sentence.

**Ex. 7: scope_widened and causal_from_correlational.**
Sentence: "Larger models cause better reasoning in language models [CITE]." Source (invented): "Across the five small models we trained, reasoning score correlates with parameter count." Label: `supported` (the core relation between size and reasoning is in the source), strength `overstated`, types `[scope_widened, causal_from_correlational]`. Span: the source sentence. Note: "five small models; correlation only".

**Ex. 8: number_changed.**
Sentence: "Method F cuts error by 40% [CITE]." Source (invented): "Method F reduces error from 10.0% to 8.0%, a 20% relative reduction." Label: `partially_supported` (the direction of the effect is supported, the key number is not), strength `overstated`, `[number_changed]`. Note: "40% vs 20%". The key number differs beyond rounding, so the label is capped at `partially_supported` (section 3, G5). If the sentence had said "10%", the same cap would apply and the strength would be `understated`.

**Ex. 9: certainty_inflated with hedge_dropped.**
Sentence: "The GammaSet paper proves that data augmentation prevents overfitting [CITE]." Source (invented): "Our preliminary results suggest that augmentation reduces overfitting in this setup." Label: `supported`, `overstated`, `[certainty_inflated, hedge_dropped, scope_widened]`. Span: the source sentence.

**Ex. 10: attribution_of_idea.**
Sentence: "Method G was proposed in [CITE]." The invented source presents Method G as its main contribution. Label: `supported`, `matches`, role `attribution_of_idea`. If the source instead said "Method G was introduced by earlier work and we extend it", the label would be `not_supported` for the proposal claim, with note "source credits earlier work".

**Ex. 11: multi-cite, separate items.**
Sentence: "Pruning [CITE1], quantization [CITE2] and distillation [CITE3] reduce model size." You judge CITE2. The invented source is about quantization and states that it reduces model size by 4x. Label: `supported`, `matches`. The pruning and distillation papers do not matter for this unit.

**Ex. 12: pointer.**
Sentence: "For a full treatment of calibration, see [CITE]." The invented source is a long chapter on calibration. Label: `supported`, `matches`, role `context_or_background`, note "pointer".

## 11. Pilot round

1. Label 30 dev units from the author's own survey (never test units) using this version.
2. Record time per unit. Note every unit where you hesitated and which rule was missing or unclear.
3. Revise this document. Keep the first-pass labels. If you relabel under the revised rules, store those as a separate round, not an overwrite.
4. Log each change in the table below: version, date, reason.
5. Freeze the guidelines (version 1.0) before the first test unit is labeled. After that, changes are deviations and go in the PROTOCOL.md deviation log.

If a second annotator joins the pilot, they read these guidelines and label the same 30 dev units independently; compare, discuss disagreements, and revise. The author labels the 30 dev units; the second annotator labels the same 30 independently only if available (G4).

| Version | Date | Change | Reason |
|---|---|---|---|
| 0.1 | 2026-11-22 | First draft | Initial version, before any pilot |
