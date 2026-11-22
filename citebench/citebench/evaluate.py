"""CiteBench metrics (PROTOCOL section 7; DECISIONS D12, D21 to D27).

Pure functions, deterministic given a seed.

Missing predictions (D27): a prediction of None means the system gave no
answer. Every function that takes predictions accepts None and has a
`missing` argument:
  "wrong"   (primary, default): the item stays in and counts as an error. A
            missing prediction never equals any label, so it is a false
            negative for its gold class and a false positive for none.
  "exclude" (secondary): items with a missing prediction are dropped.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict

import numpy as np

SUPPORT = ("supported", "partially_supported", "not_supported", "contradicted", "cannot_check")
# Convention (not a measured quantity): the probability a judge "means" at each
# confidence level 1 (guess), 2 (fairly sure), 3 (certain). Used by ECE and Brier.
DEFAULT_LEVEL_PROBS = {1: 0.5, 2: 0.75, 3: 0.95}
HEDGE_TYPES = ("hedge_dropped", "scope_widened", "causal_from_correlational", "number_changed")
WRONG_TARGET_TYPES = ("wrong_paper", "negation")


def _check_missing(missing):
    if missing not in ("wrong", "exclude"):
        raise ValueError("missing must be 'wrong' or 'exclude'")


def _pairs(gold, pred, missing):
    """Aligned (gold, pred) lists with the missing policy applied."""
    _check_missing(missing)
    if len(gold) != len(pred):
        raise ValueError("gold and pred must have the same length")
    pairs = list(zip(gold, pred))
    if missing == "exclude":
        pairs = [(g, p) for g, p in pairs if p is not None]
    return pairs


def n_missing(pred):
    return sum(p is None for p in pred)


# 1, 2. Classification metrics -------------------------------------------------

def per_class_prf(gold, pred, labels=SUPPORT, missing="wrong"):
    """{label: {"precision", "recall", "f1", "support", "predicted"}}.

    Undefined ratios (zero denominator) are 0.0; "support" is the gold count.
    """
    pairs = _pairs(gold, pred, missing)
    out = {}
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in pairs)
        ng = sum(g == lab for g, _ in pairs)
        npred = sum(p == lab for _, p in pairs)
        prec = tp / npred if npred else 0.0
        rec = tp / ng if ng else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[lab] = {"precision": prec, "recall": rec, "f1": f1, "support": ng, "predicted": npred}
    return out


def macro_f1(gold, pred, labels=SUPPORT, missing="wrong"):
    """Unweighted mean F1 over classes. Classes with no gold and no predicted
    items are excluded from the average (their F1 is undefined). Returns nan
    when no class remains."""
    prf = per_class_prf(gold, pred, labels, missing)
    f1s = [v["f1"] for v in prf.values() if v["support"] or v["predicted"]]
    return sum(f1s) / len(f1s) if f1s else float("nan")


def accuracy(gold, pred, missing="wrong"):
    pairs = _pairs(gold, pred, missing)
    return sum(g == p for g, p in pairs) / len(pairs) if pairs else float("nan")


def confusion_matrix(gold, pred, labels=SUPPORT, missing="wrong"):
    """Rows = gold, columns = predicted, in `labels` order, plus one final
    column for missing predictions (all zero under missing="exclude").
    Gold or predicted values outside `labels` raise ValueError."""
    idx = {lab: i for i, lab in enumerate(labels)}
    m = [[0] * (len(labels) + 1) for _ in labels]
    for g, p in _pairs(gold, pred, missing):
        if g not in idx or (p is not None and p not in idx):
            raise ValueError(f"label outside {labels}: {g!r}, {p!r}")
        m[idx[g]][len(labels) if p is None else idx[p]] += 1
    return m


def correct_flags(gold, pred):
    """Per-unit correctness (bool), None where the prediction is missing."""
    return [None if p is None else g == p for g, p in zip(gold, pred)]


# 3. Kappa and bootstrap ------------------------------------------------------

def cohen_kappa(a, b, missing="wrong"):
    """Unweighted Cohen's kappa (D12). None in either rater is a missing
    rating: under "wrong" it is its own category; under "exclude" the pair is
    dropped. If chance agreement is 1 the result is 1.0 when observed
    agreement is 1, else 0.0."""
    _check_missing(missing)
    pairs = list(zip(a, b))
    if missing == "exclude":
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in pairs) / n
    cats = {x for x, _ in pairs} | {y for _, y in pairs}
    pe = sum((sum(x == c for x, _ in pairs) / n) * (sum(y == c for _, y in pairs) / n) for c in cats)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1 - pe)


def _ci(stat_fn, arrays, idx_samples, alpha):
    point = stat_fn(*arrays)
    stats = np.array(
        [stat_fn(*[[arr[i] for i in idx] for arr in arrays]) for idx in idx_samples], dtype=float
    )
    stats = stats[~np.isnan(stats)]
    if stats.size == 0:
        return point, float("nan"), float("nan")
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    # The percentile interval can miss a skewed point estimate; widen to include it.
    return point, float(min(lo, point)), float(max(hi, point))


def bootstrap_ci(stat_fn, *arrays, n=10000, seed=0, alpha=0.05):
    """Paired percentile bootstrap: indices are resampled jointly across all
    arrays. Returns (point_estimate, lo, hi). Default n = 10000 (D22); use
    n = 1000 for kappa (D12)."""
    size = len(arrays[0])
    if any(len(a) != size for a in arrays):
        raise ValueError("arrays must have equal length")
    rng = np.random.default_rng(seed)
    samples = (rng.integers(0, size, size) for _ in range(n)) if size else iter(())
    return _ci(stat_fn, arrays, samples, alpha)


def cluster_bootstrap_ci(stat_fn, clusters, *arrays, n=10000, seed=0, alpha=0.05):
    """Like bootstrap_ci but resamples whole clusters (e.g. surveys) with
    replacement (D22 sensitivity check). `clusters` gives one id per item."""
    size = len(clusters)
    if any(len(a) != size for a in arrays):
        raise ValueError("arrays must match clusters in length")
    groups = defaultdict(list)
    for i, c in enumerate(clusters):
        groups[c].append(i)
    keys = sorted(groups, key=str)
    rng = np.random.default_rng(seed)

    def draw():
        picks = rng.integers(0, len(keys), len(keys))
        return [i for k in picks for i in groups[keys[k]]]

    return _ci(stat_fn, arrays, (draw() for _ in range(n if keys else 0)), alpha)


# 4. Calibration (D21) --------------------------------------------------------

def ece_by_level(confidences, correct, levels=(1, 2, 3), level_probs=DEFAULT_LEVEL_PROBS, missing="wrong"):
    """Expected calibration error with one bin per confidence level, weighted
    by bin size: sum_b (n_b / N) * |accuracy_b - level_probs[b]|. The nominal
    probability per level is a convention (see DEFAULT_LEVEL_PROBS). An item
    needs a confidence. Missing correctness (None, no prediction) counts as
    incorrect under missing="wrong" (default) and is skipped under "exclude".
    Items with confidence None are always skipped. Returns nan if nothing
    remains."""
    _check_missing(missing)
    items = [(c, bool(k)) for c, k in zip(confidences, correct)
             if c is not None and (k is not None or missing == "wrong")]
    if not items:
        return float("nan")
    total = 0.0
    for lv in levels:
        bin_ = [k for c, k in items if c == lv]
        if bin_:
            total += len(bin_) / len(items) * abs(sum(bin_) / len(bin_) - level_probs[lv])
    return total


def prob_supported(confidences, pred_labels, level_probs=DEFAULT_LEVEL_PROBS):
    """Probability that the unit is "supported", from the judge's confidence in
    its own label: level_probs[c] if it predicted "supported", else
    1 - level_probs[c]. A convention, not a measured probability. None where
    confidence or label is missing."""
    return [
        None if c is None or p is None else (level_probs[c] if p == "supported" else 1 - level_probs[c])
        for c, p in zip(confidences, pred_labels)
    ]


def brier(prob_supported_, is_supported):
    """Mean squared error between probability and the binary outcome
    (supported vs not). Items with a None probability or outcome are skipped."""
    items = [(p, float(y)) for p, y in zip(prob_supported_, is_supported) if p is not None and y is not None]
    return sum((p - y) ** 2 for p, y in items) / len(items) if items else float("nan")


# 5. McNemar and Holm (D23) ---------------------------------------------------

def discordant(correct_a, correct_b):
    """(b, c): b = A right and B wrong, c = A wrong and B right. None entries
    (missing) are treated as wrong."""
    b = sum(bool(x) and not bool(y) for x, y in zip(correct_a, correct_b))
    c = sum(bool(y) and not bool(x) for x, y in zip(correct_a, correct_b))
    return b, c


def mcnemar_exact(correct_a, correct_b, missing="wrong"):
    """Two-sided exact McNemar p-value: binomial(b + c, 0.5) on discordant
    pairs, p = min(1, 2 * P(X <= min(b, c))). 0 discordant pairs gives 1.0.
    None in a correctness list is a missing prediction: wrong by default, or
    the pair is dropped with missing="exclude"."""
    _check_missing(missing)
    if len(correct_a) != len(correct_b):
        raise ValueError("lists must have the same length")
    pairs = list(zip(correct_a, correct_b))
    if missing == "exclude":
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    b, c = discordant([x for x, _ in pairs], [y for _, y in pairs])
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(pvalues):
    """Holm step-down adjusted p-values, returned in input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adj[i] = running
    return adj


# 6. Memory reliance (E2) -----------------------------------------------------

def memory_reliance(pred_support, missing="wrong"):
    """Fraction of units predicted "supported", and (separately) fraction
    predicted "partially_supported". The caller passes only units under
    conditions where the source cannot justify support. Under "wrong" a
    missing prediction stays in the denominator and is not reliance; under
    "exclude" it leaves the denominator. Returns {"n", "supported",
    "partially_supported"} with nan rates when n = 0."""
    _check_missing(missing)
    preds = [p for p in pred_support if p is not None] if missing == "exclude" else list(pred_support)
    n = len(preds)

    def rate(lab):
        return sum(p == lab for p in preds) / n if n else float("nan")

    return {"n": n, "supported": rate("supported"), "partially_supported": rate("partially_supported")}


# 7. Planted detection (E4, D26) ----------------------------------------------

def flagged(support, strength):
    """Type-agnostic rule used for false positives on unperturbed copies."""
    return support != "supported" or strength == "overstated"


def detected(ptype, support, strength):
    """D26 detection rule. Raises ValueError for an unknown perturbation type.
    support None (missing) is not handled here; see detection_rates."""
    if ptype in HEDGE_TYPES:
        return flagged(support, strength)
    if ptype in WRONG_TARGET_TYPES:
        return support in ("not_supported", "contradicted")
    raise ValueError(f"unknown perturbation type: {ptype!r}")


def _rate_rows(rows, rule, missing):
    """rows: iterable of (support, strength). Returns {n, missing, hits, rate}."""
    _check_missing(missing)
    rows = list(rows)
    miss = sum(s is None for s, _ in rows)
    if missing == "exclude":
        rows = [(s, t) for s, t in rows if s is not None]
    hits = sum(s is not None and rule(s, t) for s, t in rows)
    return {"n": len(rows), "missing": miss, "hits": hits, "rate": hits / len(rows) if rows else float("nan")}


def detection_rates(records, missing="wrong"):
    """Per perturbation type: {n, missing, hits, rate}. records are dicts with
    ptype, support, strength. A record with support None is not detected
    (missing="wrong") or dropped (missing="exclude")."""
    by = defaultdict(list)
    for r in records:
        by[r["ptype"]].append((r.get("support"), r.get("strength")))
    return {t: _rate_rows(rows, lambda s, st, t=t: detected(t, s, st), missing) for t, rows in sorted(by.items())}


def false_positive_rate(records, missing="wrong"):
    """Rate at which unperturbed copies are flagged (type-agnostic rule:
    support != "supported" or strength == "overstated"). A missing prediction
    is not a flag under "wrong"; it is dropped under "exclude"."""
    return _rate_rows(((r.get("support"), r.get("strength")) for r in records), flagged, missing)


# 9. CLI ----------------------------------------------------------------------

def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _calibration(golds, preds, confs):
    """D21 block for one group, or None when no prediction carries a confidence."""
    if all(c is None for c in confs):
        return None
    for c in confs:
        if c is not None and c not in DEFAULT_LEVEL_PROBS:
            raise ValueError(f"confidence must be 1, 2 or 3, got {c!r}")
    ok = correct_flags(golds, preds)
    return {
        "n": sum(c is not None and p is not None for c, p in zip(confs, preds)),
        "ece": ece_by_level(confs, ok, missing="exclude"),
        "brier": brier(prob_supported(confs, preds), [g == "supported" for g in golds]),
    }


def _summarize(golds, preds, n_boot, seed, confs=None, clusters=None):
    row = {"n": len(golds), "missing": n_missing(preds)}
    for tag, mode in (("", "wrong"), ("_excl", "exclude")):
        row["acc" + tag] = accuracy(golds, preds, mode)
        row["f1" + tag] = bootstrap_ci(
            lambda g, p, m=mode: macro_f1(g, p, missing=m), golds, preds, n=n_boot, seed=seed
        )
    row["per_class"] = per_class_prf(golds, preds)
    row["calibration"] = _calibration(golds, preds, confs or [None] * len(golds))
    # D22 sensitivity: resample whole surveys. Needs survey_id on every gold row, else not available.
    if clusters and all(c is not None for c in clusters):
        row["acc_cluster"] = cluster_bootstrap_ci(accuracy, clusters, golds, preds, n=n_boot, seed=seed)
        row["f1_cluster"] = cluster_bootstrap_ci(macro_f1, clusters, golds, preds, n=n_boot, seed=seed)
    else:
        row["acc_cluster"] = row["f1_cluster"] = None
    return row


def _load(gold_path, pred_path):
    """(gold support, gold access_level, gold survey_id, latest support, latest
    confidence, unknown count). D27/D28 rules: last row per (judge, condition,
    unit_id) wins, only run_index 0 is scored, rows with unit_id not in gold
    are skipped."""
    gold, access, survey = {}, {}, {}
    for r in _read_jsonl(gold_path):
        if r["unit_id"] in gold:
            raise ValueError(f"duplicate gold unit_id {r['unit_id']}")
        gold[r["unit_id"]] = r["support"]
        access[r["unit_id"]] = r.get("access_level")
        survey[r["unit_id"]] = r.get("survey_id")
    latest, conf, unknown = {}, {}, 0
    for r in _read_jsonl(pred_path):
        if r["unit_id"] not in gold:
            unknown += 1
            continue
        if r.get("run_index", 0) != 0:
            continue
        k = (r.get("judge", "?"), r.get("condition"), r["unit_id"])
        latest[k] = r.get("support")
        conf[k] = r.get("confidence")
    return gold, access, survey, latest, conf, unknown


def evaluate_files(gold_path, pred_path, by=None, n_boot=10000, seed=0):
    """Returns ({(judge, condition-or-None): summary}, count of pred rows whose
    unit_id is not in gold). Predictions are joined to gold on unit_id. The judge
    output file is append-only, so the last row per (judge, condition, unit_id)
    wins, and only run_index 0 is scored (D28: repeats measure variation only).
    A gold unit with no row for a (judge, condition) that appears in the file is
    scored as a missing prediction (D27). With by=None, a judge whose rows span
    several conditions raises ValueError (pooling would duplicate gold units)."""
    gold, _, survey, latest, conf, unknown = _load(gold_path, pred_path)
    pairs = {(j, c) for j, c, _ in latest}
    if by is None:
        conds = defaultdict(set)
        for j, c in pairs:
            conds[j].add(c)
        if any(len(v) > 1 for v in conds.values()):
            raise ValueError("predictions span several conditions; use --by condition")
    groups = defaultdict(lambda: ([], [], [], []))
    for j, c in sorted(pairs, key=str):
        key = (j, c if by == "condition" else None)
        for uid in sorted(gold):
            groups[key][0].append(gold[uid])
            groups[key][1].append(latest.get((j, c, uid)))
            groups[key][2].append(conf.get((j, c, uid)))
            groups[key][3].append(survey[uid])
    ordered = sorted(groups.items(), key=lambda kv: str(kv[0]))
    return {k: _summarize(g, p, n_boot, seed, cf, cl) for k, (g, p, cf, cl) in ordered}, unknown


def _preds(latest, judge, cond):
    """{unit_id: predicted support or None} for this judge and condition."""
    return {u: s for (j, c, u), s in latest.items() if j == judge and c == cond}


def _correct(pred, gold, units):
    """Correctness per unit; None where the prediction is missing."""
    return [None if pred.get(u) is None else pred[u] == gold[u] for u in units]


def compare_judges(gold_path, pred_path):
    """D23, D27: per condition, every judge pair, exact McNemar on 5-way correctness.

    Primary: all gold units, a missing prediction counts as wrong. Secondary
    (row["excl"]): only units both judges answered. Both passes carry n and
    missing_a / missing_b (missing predictions over all gold units). Holm is
    applied across all returned comparisons, separately for each pass."""
    gold, _, _, latest, _, _ = _load(gold_path, pred_path)
    judges_by_cond = defaultdict(set)
    for j, c, _u in latest:
        judges_by_cond[c].add(j)
    rows = []
    for c in sorted(judges_by_cond, key=str):
        js = sorted(judges_by_cond[c])
        for i, ja in enumerate(js):
            for jb in js[i + 1:]:
                pa, pb = _preds(latest, ja, c), _preds(latest, jb, c)
                ma = sum(pa.get(u) is None for u in gold)
                mb = sum(pb.get(u) is None for u in gold)

                def stats(units):
                    ca, cb = _correct(pa, gold, units), _correct(pb, gold, units)
                    b, cc = discordant(ca, cb)
                    return {"n": len(units), "missing_a": ma, "missing_b": mb,
                            "a_only_correct": b, "b_only_correct": cc, "p": mcnemar_exact(ca, cb)}

                shared = [u for u in sorted(gold) if pa.get(u) is not None and pb.get(u) is not None]
                rows.append({"condition": c, "judge_a": ja, "judge_b": jb,
                             **stats(sorted(gold)), "excl": stats(shared)})
    for r, adj in zip(rows, holm([r["p"] for r in rows])):
        r["p_holm"] = adj
    for r, adj in zip(rows, holm([r["excl"]["p"] for r in rows])):
        r["excl"]["p_holm"] = adj
    return rows


def _e3_stats(units, gold, sa, sc, n_boot, seed):
    ca = [sa.get(u) == gold[u] for u in units]  # a missing prediction (None) is wrong
    cc = [sc.get(u) == gold[u] for u in units]
    diff = bootstrap_ci(lambda x, y: float(np.mean(x) - np.mean(y)) if len(x) else float("nan"),
                        ca, cc, n=n_boot, seed=seed)
    b, c = discordant(ca, cc)
    f1d = bootstrap_ci(lambda g, x, y: macro_f1(g, x) - macro_f1(g, y), [gold[u] for u in units],
                       [sa.get(u) for u in units], [sc.get(u) for u in units], n=n_boot, seed=seed)
    return {"n": len(units), "missing_abstract_only": sum(sa.get(u) is None for u in units),
            "missing_correct": sum(sc.get(u) is None for u in units),
            "acc_abstract_only": float(np.mean(ca)) if units else float("nan"),
            "acc_correct": float(np.mean(cc)) if units else float("nan"),
            "diff": diff, "f1_diff": f1d, "abstract_only_right": b, "correct_right": c,
            "p": mcnemar_exact(ca, cc)}


def e3_files(gold_path, pred_path, n_boot=10000, seed=0):
    """E3 (RQ4, D25, D27): per judge, accuracy and macro-F1 with abstract_only
    minus correct. Primary: every gold unit with full text, a missing prediction
    counts as wrong. Secondary (row["excl"]): only units with a prediction under
    both conditions. Once any gold record has an access_level (exclusion_applied),
    a gold unit is kept only if its access_level is full_text; the rest are
    excluded and tallied in "excluded_reasons" by access_level, or "missing_field"
    when the gold record has none. If no gold record has one, nothing can be
    excluded and "exclusion_applied" is False."""
    gold, access, _, latest, _, _ = _load(gold_path, pred_path)
    applied = any(a is not None for a in access.values())
    keep = [u for u in sorted(gold) if not applied or access[u] == "full_text"]
    reasons = defaultdict(int)
    for u in gold:
        if applied and access[u] != "full_text":
            reasons[access[u] or "missing_field"] += 1
    out = []
    for judge in sorted({j for j, _, _ in latest}):
        sa, sc = _preds(latest, judge, "abstract_only"), _preds(latest, judge, "correct")
        shared = [u for u in keep if sa.get(u) is not None and sc.get(u) is not None]
        out.append({"judge": judge, **_e3_stats(keep, gold, sa, sc, n_boot, seed),
                    "n_excluded": len(gold) - len(keep), "excluded_reasons": dict(sorted(reasons.items())),
                    "excl": _e3_stats(shared, gold, sa, sc, n_boot, seed), "exclusion_applied": applied})
    return out


def format_report(results, unknown=0):
    def ci(t):
        return f"{t[0]:.3f} [{t[1]:.3f}, {t[2]:.3f}]"

    lines = []
    for (judge, cond), s in results.items():
        lines.append(f"judge={judge}" + (f" condition={cond}" if cond is not None else ""))
        lines.append(f"  n={s['n']} missing={s['missing']}")
        lines.append(f"  accuracy={s['acc']:.3f} macro-F1={ci(s['f1'])}  (missing counted wrong)")
        lines.append(f"  accuracy={s['acc_excl']:.3f} macro-F1={ci(s['f1_excl'])}  (missing excluded)")
        if s.get("acc_cluster") is None:
            lines.append("  survey-cluster bootstrap: not available (gold has no survey_id)")
        else:
            lines.append(f"  survey-cluster bootstrap (missing counted wrong): accuracy={ci(s['acc_cluster'])} "
                         f"macro-F1={ci(s['f1_cluster'])}")
        lines.append("  per-class F1: " + " ".join(f"{k}={v['f1']:.3f}" for k, v in s["per_class"].items()))
        cal = s.get("calibration")
        lines.append("  calibration: not available (no confidence given)" if cal is None else
                     f"  calibration (n={cal['n']}): ECE={cal['ece']:.3f} Brier={cal['brier']:.3f}")
    if unknown:
        lines.append(f"note: {unknown} prediction rows had a unit_id not in gold and were skipped")
    return "\n".join(lines)


def format_compare(rows):
    lines = []
    for r in rows:
        cond = f" condition={r['condition']}" if r["condition"] is not None else ""
        a, b = r["judge_a"], r["judge_b"]
        for tag, s in (("missing counted wrong", r), ("missing excluded", r["excl"])):
            lines.append(f"compare {a} vs {b}{cond} ({tag}): n={s['n']} missing {a}={s['missing_a']} {b}={s['missing_b']} "
                         f"only-{a}-correct={s['a_only_correct']} only-{b}-correct={s['b_only_correct']} "
                         f"McNemar p={s['p']:.4f} Holm p={s['p_holm']:.4f}")
    return "\n".join(lines)


def format_e3(rows):
    def line(r, s, tag):
        d, f = s["diff"], s["f1_diff"]
        return (f"E3 judge={r['judge']} ({tag}): n={s['n']} missing abstract_only={s['missing_abstract_only']} "
                f"correct={s['missing_correct']} acc abstract_only={s['acc_abstract_only']:.3f} "
                f"correct={s['acc_correct']:.3f} diff={d[0]:.3f} [{d[1]:.3f}, {d[2]:.3f}] "
                f"macro-F1 diff={f[0]:.3f} [{f[1]:.3f}, {f[2]:.3f}] McNemar p={s['p']:.4f}")

    lines = []
    for r in rows:
        why = " ".join(f"{k}={v}" for k, v in r["excluded_reasons"].items())
        lines.append(line(r, r, "missing counted wrong") + f" excluded={r['n_excluded']}" + (f" ({why})" if why else ""))
        lines.append(line(r, r["excl"], "missing excluded"))
    if rows and not rows[0]["exclusion_applied"]:
        lines.append("note: gold has no access_level field, so D25 (exclude abstract-only gold units) "
                     "could not be applied; no units were excluded")
    return "\n".join(lines)


def _json_safe(x):
    """Recursively replace nan and inf by None so the output is strict JSON."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    return x


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m citebench.evaluate")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--by", choices=["condition"], default=None)
    ap.add_argument("--n-boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--compare", action="store_true", help="pairwise McNemar between judges (D23)")
    ap.add_argument("--e3", action="store_true", help="abstract_only vs correct per judge (E3, D25)")
    ap.add_argument("--json", metavar="OUT", help="write the full results dict as JSON")
    a = ap.parse_args(argv)
    by = a.by or ("condition" if a.compare or a.e3 else None)  # both analyses are per condition
    results, unknown = evaluate_files(a.gold, a.pred, by, a.n_boot, a.seed)
    print(format_report(results, unknown))
    full = {"results": [{"judge": j, "condition": c, **v} for (j, c), v in results.items()],
            "unknown_rows": unknown}
    if a.compare:
        full["compare"] = compare_judges(a.gold, a.pred)
        print(format_compare(full["compare"]))
    if a.e3:
        full["e3"] = e3_files(a.gold, a.pred, a.n_boot, a.seed)
        print(format_e3(full["e3"]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(_json_safe(full), f, indent=2, allow_nan=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
