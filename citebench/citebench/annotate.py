"""Offline annotation tooling: export a sheet and per-unit packets, validate, ingest, reliability pairs.

Never reads or writes any judge output. Source text is read from the fetch cache (SourceRecord.text_path
is relative to the cache root).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from thefuzz import fuzz

from citebench.units import SourceRecord, Unit, read_jsonl

SUPPORT = ("supported", "partially_supported", "not_supported", "contradicted", "cannot_check")
STRENGTH = ("matches", "overstated", "understated")
OVER_TYPES = ("hedge_dropped", "scope_widened", "causal_from_correlational", "number_changed",
              "certainty_inflated", "other")
ROLES = ("evidence", "method", "dataset_or_tool", "context_or_background", "attribution_of_idea", "contrast")
# One evidence span per line inside the CSV cell (Excel: Alt+Enter).
CONTEXT_COLS = ["unit_id", "survey_id", "section", "sentence_text", "cite_key", "cocited_keys",
                "reference_title", "reference_year", "access_level", "source_file"]
LABEL_COLS = ["annotator_id", "support", "strength", "overstatement_types", "citation_role",
              "evidence_spans", "confidence", "time_spent_sec", "notes", "labeled_at"]
COLUMNS = CONTEXT_COLS + LABEL_COLS

HEADER = """> Decision procedure (guidelines section 3, ask in order, stop at the first yes):
> 1. Source missing, wrong paper or unreadable: cannot_check.
> 2. Access level abstract and the abstract is silent on the claim: cannot_check.
> 3. Source conflicts with the claim: contradicted (minor conflict only: partially_supported).
> 4. Whole claim supported: supported.  5. Part supported: partially_supported.  6. Otherwise: not_supported.
> Key number differs beyond rounding (G5): at most partially_supported, overstated, number_changed.
> Strength is recorded only for supported and partially_supported (G1).
> Evidence spans: one span per line inside the cell (Excel: Alt+Enter), at most 4.
"""


def _read_sources(path) -> dict[tuple[str, str], SourceRecord]:
    return {(s.survey_id, s.cite_key): s for s in read_jsonl(path, SourceRecord)}


def source_text(src: SourceRecord | None, cache: Path) -> str | None:
    if src is None or not src.text_path:
        return None
    p = Path(cache) / src.text_path
    return p.read_text(encoding="utf-8") if p.exists() else None


def export(units_path, sources_path, cache, out, annotator="", shuffle_seed=0) -> list[str]:
    units = list(read_jsonl(units_path, Unit))
    sources = _read_sources(sources_path)
    order = sorted(units, key=lambda u: u.unit_id)  # stable base so the seed alone fixes the order
    random.Random(shuffle_seed).shuffle(order)
    out = Path(out)
    (out / "units").mkdir(parents=True, exist_ok=True)
    with open(out / "sheet.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for u in order:
            src = sources.get((u.survey_id, u.cite_key))
            ref = u.reference
            row = dict.fromkeys(COLUMNS, "")
            row.update(
                unit_id=u.unit_id, survey_id=u.survey_id, section=u.section or "", sentence_text=u.sentence_text,
                cite_key=u.cite_key, cocited_keys="; ".join(u.cocited_keys),
                reference_title=(ref.title or "") if ref else "", reference_year=(ref.year or "") if ref else "",
                access_level=src.access_level if src else "none",
                source_file=Path(src.text_path).name if src and src.text_path else "",
                annotator_id=annotator,
            )
            w.writerow(row)
            _write_packet(out / "units" / f"{u.unit_id}.md", u, src, source_text(src, Path(cache)))
    (out / "order.json").write_text(
        json.dumps({"shuffle_seed": shuffle_seed, "unit_ids": [u.unit_id for u in order]}, indent=1), encoding="utf-8")
    return [u.unit_id for u in order]


def _write_packet(path: Path, u: Unit, src: SourceRecord | None, text: str | None) -> None:
    ref = u.reference
    lines = [f"# Unit {u.unit_id}", "", HEADER,
             "## Sentence", "", u.sentence_text, "", "LaTeX:", "", "```latex", u.sentence_latex, "```", "",
             f"- Section: {u.section or ''}", f"- Judge this key: `{u.cite_key}`",
             f"- Co-cited keys (not your target): {', '.join(u.cocited_keys)}", "", "## Reference", ""]
    if ref:
        lines += [f"- Title: {ref.title or ''}", f"- Authors: {'; '.join(ref.authors)}", f"- Year: {ref.year or ''}",
                  f"- Venue: {ref.venue or ''}", f"- DOI: {ref.doi or ''}", f"- arXiv: {ref.arxiv_id or ''}"]
    else:
        lines.append("(key missing from the .bib)")
    lines += ["", f"Access level: **{src.access_level if src else 'none'}**", "", "## Full source text", "",
              text if text is not None else "(no source text available: cannot_check)", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _split(cell: str, sep: str) -> list[str]:
    return [p.strip() for p in cell.split(sep) if p.strip()]


def _spans(cell: str) -> list[str]:
    return [p.strip() for p in cell.splitlines() if p.strip()]


def read_sheet(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate_row(r: dict) -> list[str]:
    e: list[str] = []
    sup, stre = r.get("support", "").strip(), r.get("strength", "").strip()
    types = _split(r.get("overstatement_types", ""), ";")
    spans = _spans(r.get("evidence_spans", ""))
    notes = r.get("notes", "").strip()
    access = r.get("access_level", "").strip()
    if sup not in SUPPORT:
        return [f"support {sup!r} not in {SUPPORT}"]
    if stre and stre not in STRENGTH:
        e.append(f"strength {stre!r} not allowed")
    if sup in ("supported", "partially_supported"):
        if not stre:
            e.append(f"strength required when support is {sup}")
    elif stre:
        e.append(f"strength must be empty when support is {sup} (G1)")
    bad = [t for t in types if t not in OVER_TYPES]
    if bad:
        e.append(f"unknown overstatement_types {bad}")
    if types and stre != "overstated":
        e.append("overstatement_types only allowed when strength is overstated")
    if stre == "overstated" and not types:
        e.append("strength overstated needs at least one overstatement type")
    if "number_changed" in types and sup == "supported":
        e.append("number_changed with support supported is not allowed (G5)")
    if r.get("citation_role", "").strip() not in ROLES:
        e.append(f"citation_role {r.get('citation_role')!r} not allowed")
    if r.get("confidence", "").strip() not in ("1", "2", "3"):
        e.append("confidence must be 1, 2 or 3")
    ts = r.get("time_spent_sec", "").strip()
    if ts and not (ts.isascii() and ts.isdigit()):
        e.append("time_spent_sec must be an integer")
    if sup not in ("not_supported", "cannot_check") and not spans:
        e.append(f"evidence_spans required when support is {sup}")
    if len(spans) > 4:
        e.append("at most 4 evidence spans")
    if sup in ("not_supported", "cannot_check") and spans:
        e.append(f"evidence_spans should be empty when support is {sup}")
    if (sup in ("not_supported", "cannot_check") or "other" in types) and not notes:
        e.append("notes required (not_supported, cannot_check, other)")
    if access == "none" and sup != "cannot_check":
        e.append("access level none allows only cannot_check")
    if access == "abstract" and sup == "not_supported":
        e.append("not_supported is not available for abstract-only units")
    return e


def validate(sheet, units=None) -> tuple[dict[str, list[str]], dict]:
    rows = read_sheet(sheet)
    known = {u.unit_id for u in read_jsonl(units, Unit)} if units else None
    errors: dict[str, list[str]] = {}
    filled, seen = 0, set()
    for r in rows:
        uid = r["unit_id"]
        dup = uid in seen
        seen.add(uid)
        if not r.get("support", "").strip():
            if dup:
                errors.setdefault(uid, []).append("duplicate unit_id row")
            continue
        filled += 1
        errs = validate_row(r)
        if dup:
            errs.append("duplicate unit_id row")
        if known is not None and uid not in known:
            errs.append("unit_id not in units file")
        if errs:
            errors.setdefault(uid, []).extend(errs)
    return errors, {"rows": len(rows), "filled": filled, "unfilled": len(rows) - filled,
                    "rows_with_errors": len(errors), "errors": sum(len(v) for v in errors.values())}


def locate_span(span: str, text: str | None) -> tuple[int | None, int | None, str]:
    """G3: exact substring first, else best fuzzy window (partial_ratio >= 90), else not_found."""
    if not text or not span:
        return None, None, "not_found"
    i = text.find(span)
    if i >= 0:
        return i, i + len(span), "exact"
    n = len(span)
    step = max(1, n // 4)  # shortcut: coarse stride, offsets can be off by a few chars, fine for review flags
    best, best_i = -1, 0
    for s in range(0, max(1, len(text) - n + 1), step):
        sc = fuzz.partial_ratio(span, text[s:s + n])
        if sc > best:
            best, best_i = sc, s
    if best >= 90:
        return best_i, min(len(text), best_i + n), "fuzzy"
    return None, None, "not_found"


def ingest(sheet, units_path, sources_path, cache, out, annotator=None) -> dict:
    errors, _ = validate(sheet, units_path)
    if errors:
        raise ValueError(f"sheet has {len(errors)} invalid rows; run validate first")
    units = {u.unit_id: u for u in read_jsonl(units_path, Unit)}
    sources = _read_sources(sources_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    texts: dict[str, str | None] = {}
    n, not_found = 0, []
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in read_sheet(sheet):
            if not r.get("support", "").strip():
                continue
            u = units[r["unit_id"]]
            if u.unit_id not in texts:
                texts[u.unit_id] = source_text(sources.get((u.survey_id, u.cite_key)), Path(cache))
            spans = _spans(r["evidence_spans"])
            offs = []
            for s in spans:
                a, b, m = locate_span(s, texts[u.unit_id])
                offs.append({"start": a, "end": b, "span_match": m})
                if m == "not_found":
                    not_found.append(u.unit_id)
            rec = {
                "unit_id": u.unit_id,
                "annotator_id": annotator or r.get("annotator_id", "").strip(),
                "support": r["support"].strip(),
                "strength": r["strength"].strip() or None,
                "overstatement_types": _split(r["overstatement_types"], ";"),
                "citation_role": r["citation_role"].strip(),
                "evidence_spans": spans,
                "evidence_offsets": offs,
                "confidence": int(r["confidence"]),
                "time_spent_sec": int(r["time_spent_sec"]) if r.get("time_spent_sec", "").strip() else None,
                "notes": r.get("notes", "").strip(),
                "labeled_at": r.get("labeled_at", "").strip() or now,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    return {"labels": n, "span_not_found": sorted(set(not_found)), "span_not_found_count": len(not_found)}


def _load_labels(path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {d["unit_id"]: d for d in map(json.loads, filter(str.strip, f))}


def _count(xs: list[str]) -> dict[str, int]:
    d: dict[str, int] = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return d


def reliability(a_path, b_path, out=None) -> dict:
    a, b = _load_labels(a_path), _load_labels(b_path)
    ids = sorted(set(a) & set(b))
    pairs: dict = {"unit_ids": ids}
    agree: dict = {}
    counts: dict = {}
    for fld in ["support", "strength", "citation_role", "confidence"]:
        x = [str(a[i][fld]) for i in ids]
        y = [str(b[i][fld]) for i in ids]
        pairs[fld] = {"a": x, "b": y}
        agree[fld] = sum(p == q for p, q in zip(x, y)) / len(ids) if ids else None
        if fld != "confidence":
            counts[fld] = {"a": _count(x), "b": _count(y)}
    ta = [sorted(a[i]["overstatement_types"]) for i in ids]
    tb = [sorted(b[i]["overstatement_types"]) for i in ids]
    pairs["overstatement_types"] = {"a": ta, "b": tb}
    agree["overstatement_types"] = sum(p == q for p, q in zip(ta, tb)) / len(ids) if ids else None
    result = {"n_paired": len(ids), "only_in_a": len(set(a) - set(b)), "only_in_b": len(set(b) - set(a)),
              "agreement": agree, "counts": counts}
    if out:
        Path(out).write_text(json.dumps(pairs, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="citebench.annotate")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--units", required=True)
    e.add_argument("--sources", required=True)
    e.add_argument("--cache", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--annotator", default="")
    e.add_argument("--shuffle-seed", type=int, default=0)
    v = sub.add_parser("validate")
    v.add_argument("--sheet", required=True)
    v.add_argument("--units")
    i = sub.add_parser("ingest")
    i.add_argument("--sheet", required=True)
    i.add_argument("--units", required=True)
    i.add_argument("--sources", required=True)
    i.add_argument("--cache", required=True)
    i.add_argument("--out", required=True)
    i.add_argument("--annotator")
    r = sub.add_parser("reliability")
    r.add_argument("--a", required=True)
    r.add_argument("--b", required=True)
    r.add_argument("--out", required=True)
    a = p.parse_args(argv)
    if a.cmd == "export":
        ids = export(a.units, a.sources, a.cache, a.out, a.annotator, a.shuffle_seed)
        print(f"exported {len(ids)} units to {a.out}")
    elif a.cmd == "validate":
        errs, summ = validate(a.sheet, a.units)
        for uid, es in errs.items():
            for m in es:
                print(f"{uid}: {m}")
        print(json.dumps(summ))
        return 1 if errs else 0
    elif a.cmd == "ingest":
        try:
            print(json.dumps(ingest(a.sheet, a.units, a.sources, a.cache, a.out, a.annotator)))
        except ValueError as ex:
            print(ex, file=sys.stderr)
            return 1
    else:
        print(json.dumps(reliability(a.a, a.b, a.out), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
