import csv
import json

import pytest

from citebench import checks
from citebench.judge import build_calls
from citebench.units import write_jsonl
from test_judge import make_world


def _setup(tmp_path):
    ctx, units = make_world(tmp_path)
    calls, _ = build_calls(ctx, units, ["wrong_related", "correct"])
    cp, up, sp = tmp_path / "calls.jsonl", tmp_path / "units.jsonl", tmp_path / "sources.jsonl"
    cp.write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    write_jsonl(up, units)
    write_jsonl(sp, ctx.sources.values())
    return cp, up, sp, tmp_path / "cache", calls


def _rewrite(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=checks.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_export_is_seeded_sorted_wrong_related_only(tmp_path):
    cp, up, sp, cache, calls = _setup(tmp_path)
    wrong = {c["call_id"]: c for c in calls if c["condition"] == "wrong_related"}
    assert all("key" in c["evidence"] for c in wrong.values())  # donor already recorded in the call
    out = tmp_path / "s.csv"
    assert checks.export(cp, up, sp, cache, 3, 1, out) == 3
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig", newline="")))
    ids = [r["call_id"] for r in rows]
    assert ids == sorted(ids) and set(ids) <= set(wrong)
    r = rows[0]
    assert r["donor_key"] == wrong[r["call_id"]]["evidence"]["key"] and r["evidence"] and "[CITE]" in r["sentence"]
    assert r["wrong_source_supports"] == "" and r["note"] == ""
    checks.export(cp, up, sp, cache, 3, 1, tmp_path / "t.csv")
    assert (tmp_path / "t.csv").read_bytes() == out.read_bytes()


def test_summarize(tmp_path):
    cp, up, sp, cache, _ = _setup(tmp_path)
    out = tmp_path / "s.csv"
    checks.export(cp, up, sp, cache, 3, 1, out)
    with pytest.raises(ValueError):
        checks.summarize(out)  # unanswered
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig", newline="")))
    for r, a in zip(rows, ["no", "Yes", "unsure"]):
        r["wrong_source_supports"] = a
    _rewrite(out, rows)
    counts, flagged = checks.summarize(out)
    assert counts == {"no": 1, "yes": 1, "unsure": 1} and flagged == [rows[1]["call_id"], rows[2]["call_id"]]
    rows[0]["wrong_source_supports"] = "maybe"
    _rewrite(out, rows)
    with pytest.raises(ValueError):
        checks.summarize(out)
    assert checks.main(["wrong-pairs", "summarize", "--sheet", str(out)]) == 1
