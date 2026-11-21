"""Planted-set bookkeeping (D13 to D15). The author edits sentences by hand; these scripts only manage copies.

No LLM is ever called here (D15). Hints are advisory and never decide eligibility.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from citebench.units import Unit, read_jsonl, write_jsonl

TYPES = ("wrong_paper", "number_changed", "hedge_dropped", "scope_widened", "negation",
         "causal_from_correlational")
HEDGE_RE = re.compile(r"\b(may|might|suggest\w*|could|preliminary|can|possibly|likely|appears?)\b", re.I)
ASSOC_RE = re.compile(r"correlat\w*|associat\w*", re.I)
WIDE_RE = re.compile(r"\b(all|every|always|general\w*)\b", re.I)
TEMPLATE_COLS = ["planted_id", "unit_id", "type", "original_sentence_text", "edited_sentence_text",
                 "wrong_paper_key", "notes"]

# D26 detection expectations, stored as data so the evaluator does not re-encode them.
GOLD = {
    "overstated_or_unsupported": {"detected_if": "support != supported or strength == overstated"},
    "unsupported_or_contradicted": {"detected_if": "support in (not_supported, contradicted)"},
}
RULE_OF = {t: "overstated_or_unsupported" for t in
           ("hedge_dropped", "scope_widened", "causal_from_correlational", "number_changed")}
RULE_OF.update(wrong_paper="unsupported_or_contradicted", negation="unsupported_or_contradicted")


def planted_unit_id(planted_id: str) -> str:
    return hashlib.sha1(planted_id.encode("utf-8")).hexdigest()[:16]  # same width as make_unit_id


def _labels(path) -> dict[str, dict]:
    with open(path, encoding="utf-8") as f:
        return {d["unit_id"]: d for d in map(json.loads, filter(str.strip, f))}


def eligible(labels_path, units_path) -> list[dict]:
    """D13 filter: supported, matches, confidence >= 2. Returns one dict per unit with advisory hints."""
    labels = _labels(labels_path)
    units = list(read_jsonl(units_path, Unit))
    keys_by_survey: dict[str, set[str]] = {}
    for u in units:
        keys_by_survey.setdefault(u.survey_id, set()).add(u.cite_key)
    out = []
    for u in units:
        lab = labels.get(u.unit_id)
        if not lab or lab["support"] != "supported" or lab["strength"] != "matches" or lab["confidence"] < 2:
            continue
        span = " ".join(lab.get("evidence_spans", []))
        others = keys_by_survey[u.survey_id] - {u.cite_key} - set(u.cocited_keys)
        out.append({
            "unit_id": u.unit_id, "survey_id": u.survey_id, "sentence_text": u.sentence_text,
            "hints": {
                "wrong_paper": bool(others),
                "number_changed": bool(re.search(r"\d", u.sentence_text)),
                "hedge_dropped": bool(HEDGE_RE.search(span)),
                "scope_widened": not WIDE_RE.search(u.sentence_text),
                "negation": True,
                "causal_from_correlational": bool(ASSOC_RE.search(span)),
            },
        })
    return out


def _suggest_key(u: Unit, units: list[Unit]) -> str:
    others = sorted({v.cite_key for v in units if v.survey_id == u.survey_id} - {u.cite_key} - set(u.cocited_keys))
    return others[0] if others else ""


def template(labels_path, units_path, out, selections=None, all_eligible=False) -> int:
    if bool(selections) == bool(all_eligible):
        raise ValueError("give exactly one of selections or all_eligible")
    units = list(read_jsonl(units_path, Unit))
    by_id = {u.unit_id: u for u in units}
    ok = {e["unit_id"]: e for e in eligible(labels_path, units_path)}
    if all_eligible:
        pairs = [(uid, t) for uid, e in ok.items() for t in TYPES if e["hints"][t]]
    else:
        with open(selections, encoding="utf-8-sig", newline="") as f:
            pairs = [(r["unit_id"].strip(), r["type"].strip()) for r in csv.DictReader(f)]
        for uid, t in pairs:
            if t not in TYPES:
                raise ValueError(f"unknown type {t!r}")
            if uid not in ok:
                raise ValueError(f"unit {uid} is not eligible (D13)")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TEMPLATE_COLS)
        w.writeheader()
        for uid, t in pairs:
            u = by_id[uid]
            w.writerow({"planted_id": f"{uid}:{t}", "unit_id": uid, "type": t,
                        "original_sentence_text": u.sentence_text, "edited_sentence_text": "",
                        "wrong_paper_key": _suggest_key(u, units) if t == "wrong_paper" else "", "notes": ""})
    return len(pairs)


def build(template_path, units_path, out_dir) -> dict:
    units = list(read_jsonl(units_path, Unit))
    by_id = {u.unit_id: u for u in units}
    with open(template_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    errors, planted, meta, bases = [], [], [], {}
    seen = set()
    for r in rows:
        pid, uid, t = r["planted_id"].strip(), r["unit_id"].strip(), r["type"].strip()
        edited, key = r["edited_sentence_text"].strip(), r.get("wrong_paper_key", "").strip()
        u = by_id.get(uid)
        if u is None:
            errors.append(f"{pid}: unit_id not in units")
            continue
        if t not in TYPES:
            errors.append(f"{pid}: unknown type {t!r}")
            continue
        if pid in seen:
            errors.append(f"{pid}: duplicate planted_id")
            continue
        seen.add(pid)
        new = replace(u, unit_id=planted_unit_id(pid), cocited_keys=list(u.cocited_keys))
        if t == "wrong_paper":
            donor = next((v for v in units if v.survey_id == u.survey_id and v.cite_key == key), None)
            if not key or donor is None:
                errors.append(f"{pid}: wrong_paper_key {key!r} not a cited key of survey {u.survey_id}")
                continue
            if key == u.cite_key:
                errors.append(f"{pid}: wrong_paper_key equals the original key")
                continue
            if edited and edited != u.sentence_text:
                errors.append(f"{pid}: wrong_paper changes the source only; leave edited text empty or unchanged")
                continue
            new.cite_key = key
            new.reference = copy.deepcopy(donor.reference)
            new.cocited_keys = [k for k in u.cocited_keys if k != key]
            edited = u.sentence_text
        else:
            if not edited:
                errors.append(f"{pid}: edited_sentence_text is empty")
                continue
            if edited == u.sentence_text:
                errors.append(f"{pid}: edited text is identical to the original")
                continue
            new.sentence_text = edited
            new.sentence_latex = edited  # the original LaTeX no longer matches the edited text
        planted.append(new)
        bases[uid] = u
        meta.append({"planted_id": pid, "unit_id": uid, "planted_unit_id": new.unit_id, "type": t,
                     "original_sentence_text": u.sentence_text, "edited_sentence_text": edited,
                     "wrong_paper_key": key if t == "wrong_paper" else None, "notes": r.get("notes", "").strip(),
                     "gold": {"rule": RULE_OF[t], **GOLD[RULE_OF[t]], "expected_detected": True}})
    if errors:
        raise ValueError("\n".join(errors))
    for uid, u in bases.items():  # D26 unperturbed controls, one per base unit
        pid = f"{uid}:none"
        c = replace(u, unit_id=planted_unit_id(pid), cocited_keys=list(u.cocited_keys))
        planted.append(c)
        meta.append({"planted_id": pid, "unit_id": uid, "planted_unit_id": c.unit_id, "type": "none",
                     "original_sentence_text": u.sentence_text, "edited_sentence_text": u.sentence_text,
                     "wrong_paper_key": None, "notes": "",
                     "gold": {"rule": "none", "detected_if": "false positive if support != supported "
                              "or strength == overstated", "expected_detected": False}})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "planted_units.jsonl", planted)
    with open(out / "planted_meta.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return {"planted": len(meta) - len(bases), "controls": len(bases)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="citebench.planted")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eligible")
    e.add_argument("--labels", required=True)
    e.add_argument("--units", required=True)
    t = sub.add_parser("template")
    t.add_argument("--labels", required=True)
    t.add_argument("--units", required=True)
    t.add_argument("--out", required=True)
    g = t.add_mutually_exclusive_group(required=True)
    g.add_argument("--selections")
    g.add_argument("--all-eligible", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--template", required=True)
    b.add_argument("--units", required=True)
    b.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "eligible":
            for r in eligible(a.labels, a.units):
                print(json.dumps(r, ensure_ascii=False))
        elif a.cmd == "template":
            print(f"wrote {template(a.labels, a.units, a.out, a.selections, a.all_eligible)} rows to {a.out}")
        else:
            print(json.dumps(build(a.template, a.units, a.out)))
    except ValueError as ex:
        print(ex, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
