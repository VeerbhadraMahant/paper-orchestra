You are checking one citation in a scientific literature survey. You will see a sentence from the survey, where [CITE] marks the position of one cited reference, and some evidence text taken from that cited reference. Decide whether the evidence supports what the sentence attributes to the cited reference.

## Rules

- Use ONLY the evidence text below. Do not use what you remember about the cited paper or the field. If you know the paper says something that is not in the evidence, the label follows the evidence.
- The evidence is a selection of passages, not the whole paper. Absence of a claim from an abstract or from the passages shown is not evidence that the paper does not support it: in that case answer cannot_check, not not_supported.
- Judge only the part of the sentence that is attributed to the reference marked [CITE]. Other references cited in the same sentence ("cocited" below) must not be used to settle your answer.
- Do not guess. If the evidence is missing or does not address the claim, say so with cannot_check.

## Support label (choose exactly one)

- supported: the evidence states the claim, or it follows directly from the evidence without outside knowledge or an extra inference step. Differences of wording do not matter.
- partially_supported: the evidence supports some distinct part of what the sentence attributes to the reference, and another distinct part is absent or differs. If you can name and quote the supported part, use this label.
- not_supported: the evidence is enough to judge, you looked for the claim and neighbouring wording, and the evidence neither states nor implies it. It does not say the opposite. Use this only when the evidence is a complete enough basis for judging.
- contradicted: the evidence states something that conflicts with the claim (opposite direction, a number that cannot be reconciled, the method fails where the sentence says it works).
- cannot_check: you cannot decide from the evidence provided: no source text, the text is about a different paper, it is unreadable, it is only an abstract or a few passages that are silent on the claim, or the claim may sit in a table or figure that is not shown.

A central number in the sentence that differs from the evidence beyond rounding means at most partially_supported (strength overstated, type number_changed, when the sentence is stronger). Use contradicted only when the evidence reverses the direction of the claim. If the only difference is a hedge, a scope limit or the strength of the wording, keep supported and record the difference in strength.

## Strength (only for supported or partially_supported)

For every other support label, set strength to null and overstatement_types to [].

- matches: same strength, scope, certainty and numbers as the evidence (rounding allowed).
- overstated: the sentence is stronger, broader, more certain or more exact than the evidence.
- understated: the sentence is clearly weaker or narrower than the evidence. Not for ordinary caution.

If overstated, list every type that applies:

- hedge_dropped: the evidence qualifies the claim ("can", "in some cases", "suggests") and the sentence states it flatly.
- scope_widened: the evidence holds for a narrower set (one dataset, one model family, one task, a subset of cases) and the sentence states it for a wider set.
- causal_from_correlational: the evidence reports an association or observational result and the sentence says one thing causes or drives the other.
- number_changed: a figure in the sentence differs from the evidence beyond rounding and makes the claim stronger.
- certainty_inflated: the sentence adds confidence or proof the evidence does not claim ("proves", "conclusively shows").
- other: any other way the sentence is stronger than the evidence.

## Input

Sentence: {{sentence}}

Cited reference title: {{title}}

Other references cited in the same sentence: {{cocited_count}}

Evidence from the cited reference:

{{evidence}}

## Output

Reply with a single JSON object and nothing else:

{"support": "supported" | "partially_supported" | "not_supported" | "contradicted" | "cannot_check", "strength": "matches" | "overstated" | "understated" | null, "overstatement_types": [], "confidence": 1 | 2 | 3, "evidence_quote": "<at most 300 characters copied exactly from the evidence, or an empty string>"}

confidence: 1 = unsure, 2 = fairly sure, 3 = very sure.
