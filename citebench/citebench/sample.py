"""Unit sampling for CiteBench (D8 to D10): provisional strata, capped stratified draw, finalisation after fetching."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

from .units import Unit, read_jsonl

SEED = 20261122
QUOTAS = {"evidence": 80, "method": 60, "context": 60}

_NUM = re.compile(r"\d+(?:\.\d+)?\s?%|\d+\.\d+|\b\d+(?:\.\d+)?x\b|\bpercent\b", re.I)
_EVID = re.compile(
    r"\b(outperform\w*|show(?:s|ed|n|ing)?|found|find(?:s|ings?)?|achiev\w+|demonstrat\w+|improv\w+|"
    r"reduc\w+|higher|lower|better than|state-of-the-art|significant\w*|observed?|reported?|evidence|results?)\b",
    re.I)
_METH = re.compile(
    r"\b(propos\w+|introduc\w+|we (?:use|adopt|follow|employ)|based on|datasets?|benchmarks?|toolkits?|"
    r"frameworks?|librar(?:y|ies)|implement\w+|algorithms?|architectures?)\b", re.I)


def classify_role(sentence_text: str) -> str:
    """Provisional stratum: "evidence", "method" or "context". A sampling heuristic, NOT a measurement of role.

    Rules (D8, sentence only, never shown to the annotator): count evidence cues (a quantitative pattern such as
    a percentage or decimal, counted double, or words like outperform/show/found/achieve/improve/results) and
    method cues (propose/introduce/we use/based on/dataset/benchmark/toolkit/framework/library/implement/
    algorithm/architecture). The larger count wins, ties go to evidence; no cue at all means context. The
    annotator's own role label is the one analysed.
    """
    e = len(_EVID.findall(sentence_text)) + 2 * len(_NUM.findall(sentence_text))
    m = len(_METH.findall(sentence_text))
    if e == 0 and m == 0:
        return "context"
    return "evidence" if e >= m else "method"


def _fetchable(u: Unit) -> bool:
    r = u.reference
    return r is not None and bool(r.title or r.arxiv_id or r.doi)


def sample(units_by_survey: dict[str, list[Unit]], quotas: dict[str, int] | None = None, per_survey_cap: int = 25,
           per_sentence_cap: int = 1, oversample: float = 2.0, seed: int = SEED) -> list[dict]:
    """Stratified seeded draw of oversample x quota candidates per stratum, round-robin over surveys (sorted).

    D9: one unit per sentence (key chosen by seeded choice; only per_sentence_cap=1 is supported). Units whose
    reference is missing or has no title/arXiv id/DOI are dropped (cannot be fetched). In this candidate pool the
    per-survey cap is scaled by oversample (per stratum pool = cap x oversample per survey); finalize enforces the
    real per-survey cap of D9 on the kept units.
    """
    quotas = quotas or QUOTAS
    if per_sentence_cap != 1:
        raise ValueError("only one unit per sentence is implemented (D9)")
    pools: dict[str, dict[str, list[Unit]]] = {s: {} for s in quotas}
    for sid in sorted(units_by_survey):
        by_sent: dict[tuple, list[Unit]] = {}
        for u in units_by_survey[sid]:
            if _fetchable(u):
                by_sent.setdefault((u.source_file, u.char_start), []).append(u)
        for key in sorted(by_sent):
            opts = sorted(by_sent[key], key=lambda u: u.cite_key)
            u = random.Random(f"{seed}|{sid}|{key}").choice(opts)
            st = classify_role(u.sentence_text)
            if st in pools:
                pools[st].setdefault(sid, []).append(u)
    out, cap = [], int(per_survey_cap * oversample)
    for st, q in quotas.items():
        want = int(round(q * oversample))
        lists = {}
        for sid, us in pools[st].items():
            us = sorted(us, key=lambda u: u.unit_id)
            random.Random(f"{seed}|{st}|{sid}").shuffle(us)
            lists[sid] = us[:cap]
        rank = 0
        while rank < want and any(lists.values()):
            for sid in sorted(lists):
                if rank >= want:
                    break
                if lists[sid]:
                    u = lists[sid].pop(0)
                    out.append({"unit_id": u.unit_id, "survey_id": u.survey_id, "source_file": u.source_file,
                                "char_start": u.char_start, "char_end": u.char_end, "cite_key": u.cite_key,
                                "sentence_text": u.sentence_text, "stratum": st, "draw_rank": rank})
                    rank += 1
    return out


def finalize(candidates: list[dict], sources_latest: dict, quotas: dict[str, int] | None = None,
             per_survey_cap: int = 25) -> tuple[list[dict], dict]:
    """D10: per stratum in draw-rank order keep units whose source is full_text/abstract until the quota is met.

    Strata are walked in quota order and the per-survey cap counts across strata (earlier strata claim first).
    A candidate with no source record counts as access none. Caps are never relaxed: a shortfall is reported
    under log["unmet"].
    """
    quotas = quotas or QUOTAS
    final, per_survey = [], {}
    log = {"skipped_access_none": {}, "skipped_survey_cap": {}, "unmet": {}}
    for st, q in quotas.items():
        kept = 0
        for c in sorted((c for c in candidates if c["stratum"] == st), key=lambda c: c["draw_rank"]):
            if kept >= q:
                break
            rec = sources_latest.get((c["survey_id"], c["cite_key"]))
            level = rec.access_level if rec else "none"
            if level not in ("full_text", "abstract"):
                log["skipped_access_none"][st] = log["skipped_access_none"].get(st, 0) + 1
                continue
            if per_survey.get(c["survey_id"], 0) >= per_survey_cap:
                log["skipped_survey_cap"][st] = log["skipped_survey_cap"].get(st, 0) + 1
                continue
            per_survey[c["survey_id"]] = per_survey.get(c["survey_id"], 0) + 1
            final.append({**c, "access_level": level})
            kept += 1
        if kept < q:
            log["unmet"][st] = {"quota": q, "kept": kept}
    return final, log


def reliability_subset(final: list[dict], n: int = 50, seed: int = SEED) -> set[str]:
    """unit_ids of an n-unit subset, allocated across strata proportionally (largest remainder), seeded."""
    total = len(final)
    n = min(n, total)
    groups = {s: sorted(u["unit_id"] for u in final if u["stratum"] == s) for s in sorted({u["stratum"] for u in final})}
    exact = {s: n * len(g) / total for s, g in groups.items()} if total else {}
    alloc = {s: int(v) for s, v in exact.items()}
    for s in sorted(exact, key=lambda s: (-(exact[s] - alloc[s]), s))[: n - sum(alloc.values())]:
        alloc[s] += 1
    rng, chosen = random.Random(seed), set()
    for s, g in groups.items():
        chosen.update(rng.sample(g, alloc[s]))
    return chosen


MANIFEST_FIELDS = ("unit_id", "survey_id", "source_file", "char_start", "char_end", "cite_key", "stratum",
                   "draw_rank", "access_level", "in_reliability_subset")


def manifest(final: list[dict], log: dict, quotas=QUOTAS, per_survey_cap=25, seed=SEED) -> dict:
    """Committed manifest: no sentence text, only offsets and ids."""
    return {"units": [{k: u[k] for k in MANIFEST_FIELDS} for u in final],
            "counts": {"total": len(final), "by_stratum": {s: sum(u["stratum"] == s for u in final) for s in quotas},
                       "by_access": {a: sum(u["access_level"] == a for u in final) for a in ("full_text", "abstract")},
                       "reliability": sum(u["in_reliability_subset"] for u in final)},
            "log": log, "seed": seed, "quotas": quotas, "per_survey_cap": per_survey_cap, "per_sentence_cap": 1,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def _write_jsonl(path, rows) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def materialize(manifest_path, units_dir, out) -> int:
    """Write the manifest's units (with sentence text) from per-survey unit files, in manifest order.

    Raises ValueError if a unit_id is missing or its survey_id/cite_key/offsets disagree with the manifest.
    """
    from .units import write_jsonl

    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    entries = data["units"]
    ids = [e["unit_id"] for e in entries]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate unit_id in manifest: {dup[:5]}")
    total = (data.get("counts") or {}).get("total")
    if total is not None and total != len(entries):
        raise ValueError(f"manifest counts.total is {total} but it lists {len(entries)} units")
    needed = set(ids)
    found: dict[str, dict[str, Unit]] = {}
    for sid in sorted({e["survey_id"] for e in entries}):
        p = Path(units_dir) / f"{sid}.jsonl"
        if not p.exists():
            raise ValueError(f"missing unit file {p}")
        found[sid] = {}
        for u in read_jsonl(p, Unit):
            if u.unit_id in needed and u.unit_id in found[sid]:
                raise ValueError(f"duplicate unit_id {u.unit_id} in {sid}.jsonl")
            found[sid][u.unit_id] = u
    rows = []
    for e in entries:
        u = found[e["survey_id"]].get(e["unit_id"])
        if u is None:
            raise ValueError(f"unit_id {e['unit_id']} not found in {e['survey_id']}.jsonl")
        if not u.sentence_text.strip():
            raise ValueError(f"unit {e['unit_id']}: empty sentence_text")
        for k in ("survey_id", "cite_key", "char_start", "char_end"):
            if getattr(u, k) != e[k]:
                raise ValueError(f"unit {e['unit_id']}: {k} is {getattr(u, k)!r}, manifest says {e[k]!r}")
        rows.append(u)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return write_jsonl(out, rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m citebench.sample")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("materialize")
    m.add_argument("--manifest", required=True)
    m.add_argument("--units-dir", required=True)
    m.add_argument("--out", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--units-dir", required=True)
    c.add_argument("--out", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--candidates", required=True)
    f.add_argument("--sources", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--manifest", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "materialize":
        try:
            n = materialize(a.manifest, a.units_dir, a.out)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"{n} units written")
        return 0
    if a.cmd == "candidates":
        ubs = {p.stem: list(read_jsonl(p, Unit)) for p in sorted(Path(a.units_dir).glob("*.jsonl"))}
        cands = sample(ubs)
        _write_jsonl(a.out, cands)
        print(f"{len(cands)} candidates from {len(ubs)} surveys")
        return 0
    from .fetch import latest_records

    cands = [json.loads(l) for l in Path(a.candidates).read_text(encoding="utf-8").splitlines() if l.strip()]
    final, log = finalize(cands, latest_records(a.sources))
    rel = reliability_subset(final)
    for u in final:
        u["in_reliability_subset"] = u["unit_id"] in rel
    _write_jsonl(a.out, final)
    Path(a.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(a.manifest).write_text(json.dumps(manifest(final, log), indent=1), encoding="utf-8")
    print(f"{len(final)} final units; unmet: {log['unmet'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
