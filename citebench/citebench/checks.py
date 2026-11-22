"""Author checks on the benchmark itself. wrong-pairs: spot-check D18 (the wrong_related source must not support the claim).

export draws n wrong_related calls (seeded) into a CSV sheet; the author fills wrong_source_supports with
yes, no or unsure; summarize validates the sheet and lists the calls answered yes or unsure.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

from .fetch import latest_records
from .judge import Context, evidence_for, target_sentence
from .units import Unit, read_jsonl

COLUMNS = ["call_id", "unit_id", "sentence", "donor_key", "evidence", "wrong_source_supports", "note"]
ANSWERS = ("yes", "no", "unsure")


def export(calls_path, units_path, sources_path, cache, n, seed, out) -> int:
    rows = [json.loads(l) for l in Path(calls_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    calls = {c["call_id"]: c for c in rows}  # last row wins
    wrong = sorted((c for c in calls.values() if c["condition"] == "wrong_related"), key=lambda c: c["call_id"])
    if len(wrong) < n:
        raise ValueError(f"only {len(wrong)} wrong_related calls, fewer than --n {n}")
    pick = sorted(random.Random(seed).sample(wrong, n), key=lambda c: c["call_id"])
    ctx = Context(list(read_jsonl(units_path, Unit)), latest_records(sources_path), cache)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:  # same as annotate.py, opens in Excel
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for c in pick:
            u = ctx.units[c["unit_id"]]
            ev = evidence_for(ctx, u, "wrong_related", c["evidence"])
            w.writerow({"call_id": c["call_id"], "unit_id": u.unit_id, "sentence": target_sentence(u),
                        "donor_key": c["evidence"]["key"],
                        "evidence": "\n\n".join(f"[{lab}]\n{t}" for lab, t in ev.parts),
                        "wrong_source_supports": "", "note": ""})
    return len(pick)


def summarize(sheet) -> tuple[Counter, list[str]]:
    """Counts of answers and the call_ids answered yes or unsure. Raises ValueError on a blank or unknown answer."""
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        absent = [h for h in ("call_id", "wrong_source_supports") if h not in (reader.fieldnames or [])]
        if absent:
            raise ValueError(f"sheet is missing required columns: {absent}")
        rows = list(reader)
    ids = [r["call_id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate call_id rows: {dup[:5]}")
    bad = [f"row {i}: {r['wrong_source_supports']!r}" for i, r in enumerate(rows, 2)
           if (r["wrong_source_supports"] or "").strip().lower() not in ANSWERS]
    if bad:
        raise ValueError("answer must be yes, no or unsure: " + "; ".join(bad))
    ans = [(r["call_id"], r["wrong_source_supports"].strip().lower()) for r in rows]
    return Counter(a for _, a in ans), [c for c, a in ans if a != "no"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m citebench.checks")
    sub = ap.add_subparsers(dest="cmd", required=True).add_parser("wrong-pairs").add_subparsers(dest="act", required=True)
    e = sub.add_parser("export")
    e.add_argument("--calls", required=True)
    e.add_argument("--units", required=True)
    e.add_argument("--sources", required=True)
    e.add_argument("--cache", required=True)
    e.add_argument("--n", type=int, default=20)
    e.add_argument("--seed", type=int, default=20261122)
    e.add_argument("--out", required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--sheet", required=True)
    a = ap.parse_args(argv)
    if a.act == "export":
        try:
            print(f"{export(a.calls, a.units, a.sources, a.cache, a.n, a.seed, a.out)} pairs written")
        except ValueError as err:
            print(f"error: {err}", file=sys.stderr)
            return 1
        return 0
    try:
        counts, flagged = summarize(a.sheet)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(" ".join(f"{k}={counts.get(k, 0)}" for k in ANSWERS))
    print("yes or unsure: " + (", ".join(flagged) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
