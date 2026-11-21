"""Coverage report: access level by publication year, source and error breakdowns.

Usage: python -m citebench.report coverage --units U.jsonl --sources S.jsonl [--json out.json]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .fetch import latest_records
from .units import Unit, read_jsonl

BUCKETS = ["<2000", "2000-2009", "2010-2014", "2015-2019", "2020+", "unknown"]
LEVELS = ["full_text", "abstract", "none"]


def bucket(year) -> str:
    if not year:
        return "unknown"
    return ("<2000" if year < 2000 else "2000-2009" if year < 2010 else "2010-2014" if year < 2015
            else "2015-2019" if year < 2020 else "2020+")


def coverage(units_path, sources_path, top: int = 10) -> dict:
    years = {}
    for u in read_jsonl(units_path, Unit):
        k = (u.survey_id, u.cite_key)
        if years.get(k) is None:
            years[k] = u.reference.year if u.reference else None
    rows = {b: Counter() for b in BUCKETS}
    sources, errors = Counter(), Counter()
    for k, r in latest_records(sources_path).items():
        rows[bucket(years.get(k))][r.access_level] += 1
        if r.source_name:
            sources[r.source_name] += 1
        if r.error:
            errors.update(r.error.split("; "))
    table = {}
    for b, c in [*rows.items(), ("total", sum(rows.values(), Counter()))]:
        n = sum(c[lv] for lv in LEVELS)
        table[b] = {"n": n, **{lv: c[lv] for lv in LEVELS},
                    **{f"{lv}_pct": round(100 * c[lv] / n, 1) if n else 0.0 for lv in LEVELS}}
    return {"table": table, "source_name": dict(sources.most_common()), "errors": dict(errors.most_common(top))}


def render(rep: dict) -> str:
    lines = [f"{'year':<10}{'n':>6}" + "".join(f"{lv:>10}{'%':>7}" for lv in LEVELS)]
    for b, t in rep["table"].items():
        lines.append(f"{b:<10}{t['n']:>6}" + "".join(f"{t[lv]:>10}{t[lv + '_pct']:>7.1f}" for lv in LEVELS))
    lines += ["", "source_name:"] + [f"  {k}: {v}" for k, v in rep["source_name"].items()]
    lines += ["", "top errors:"] + [f"  {k}: {v}" for k, v in rep["errors"].items()]
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m citebench.report")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--units", required=True)
    c.add_argument("--sources", required=True)
    c.add_argument("--json", help="also write the table to this JSON file")
    a = ap.parse_args(argv)
    rep = coverage(a.units, a.sources)
    print(render(rep))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
