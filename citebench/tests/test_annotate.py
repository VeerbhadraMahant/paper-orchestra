import csv
import json

import pytest

from citebench import annotate as A
from citebench.units import Reference, SourceRecord, Unit, make_unit_id, write_jsonl

TEXT = "Intro line.\nMethod E may improve accuracy on small datasets in some experiments.\nOther text here."


def mk_unit(i, survey="s1", key="k1", text="Method E improves accuracy [CITE]."):
    return Unit(unit_id=make_unit_id(survey, "m.tex", i, key), survey_id=survey, source_file="m.tex", char_start=i,
                char_end=i + 10, section="Intro", sentence_latex=f"Method E \\cite{{{key}}}", sentence_text=text,
                cite_key=key, cocited_keys=["z"], reference=Reference(key=key, title="T " + key, year=2020))


@pytest.fixture
def env(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "k1.txt").write_text(TEXT, encoding="utf-8")
    units = [mk_unit(i, survey=f"s{i % 3}", key="k1" if i < 8 else "k2") for i in range(12)]
    srcs = [SourceRecord(cite_key="k1", survey_id=f"s{j}", access_level="full_text", text_path="k1.txt")
            for j in range(3)]
    srcs += [SourceRecord(cite_key="k2", survey_id=f"s{j}", access_level="none") for j in range(3)]
    write_jsonl(tmp_path / "U.jsonl", units)
    write_jsonl(tmp_path / "S.jsonl", srcs)
    return tmp_path, units


def do_export(tmp, seed=0, out="out"):
    A.export(tmp / "U.jsonl", tmp / "S.jsonl", tmp / "cache", tmp / out, annotator="A1", shuffle_seed=seed)
    return tmp / out


def test_export_layout_bom_and_columns(env):
    tmp, units = env
    out = do_export(tmp)
    raw = (out / "sheet.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = A.read_sheet(out / "sheet.csv")
    assert len(rows) == 12
    assert list(rows[0]) == A.COLUMNS
    for c in ["support", "strength", "overstatement_types", "citation_role", "evidence_spans", "confidence",
              "time_spent_sec", "notes"]:
        assert c in rows[0] and rows[0][c] == ""
    assert all((out / "units" / f"{u.unit_id}.md").exists() for u in units)
    assert (out / "order.json").exists()


def test_shuffle_reproducible_and_seed_sensitive(env):
    tmp, _ = env

    def ids(o):
        return [r["unit_id"] for r in A.read_sheet(o / "sheet.csv")]

    a, b = ids(do_export(tmp, 5, "a")), ids(do_export(tmp, 5, "b"))
    assert a == b
    assert a != ids(do_export(tmp, 6, "c"))
    assert json.loads((tmp / "a" / "order.json").read_text())["unit_ids"] == a


def test_packet_full_source_no_judge_fields(env):
    tmp, units = env
    out = do_export(tmp)
    p = (out / "units" / f"{units[0].unit_id}.md").read_text(encoding="utf-8")
    assert TEXT in p and "Decision procedure" in p and units[0].sentence_text in p
    assert "judge" not in p.lower().replace("judge this key", "")
    none_unit = next(u for u in units if u.cite_key == "k2")
    assert "no source text" in (out / "units" / f"{none_unit.unit_id}.md").read_text(encoding="utf-8")


def row(**kw):
    r = dict(unit_id="u", access_level="full_text", support="supported", strength="matches",
             overstatement_types="", citation_role="evidence", evidence_spans="span", confidence="2",
             time_spent_sec="10", notes="")
    r.update(kw)
    return r


@pytest.mark.parametrize("kw,frag", [
    (dict(support="bogus"), "support"),
    (dict(support="not_supported", notes="x", evidence_spans=""), "G1"),
    (dict(support="contradicted", strength="matches"), "G1"),
    (dict(support="cannot_check", strength="matches", evidence_spans="", notes="x"), "G1"),
    (dict(strength=""), "strength required"),
    (dict(overstatement_types="hedge_dropped"), "only allowed when strength is overstated"),
    (dict(strength="overstated", overstatement_types=""), "at least one"),
    (dict(strength="overstated", overstatement_types="nope"), "unknown"),
    (dict(strength="overstated", overstatement_types="number_changed"), "G5"),
    (dict(strength="overstated", overstatement_types="other"), "notes required"),
    (dict(confidence="4"), "confidence"),
    (dict(citation_role="x"), "citation_role"),
    (dict(evidence_spans=""), "evidence_spans required"),
    (dict(support="not_supported", strength="", evidence_spans="", notes=""), "notes required"),
    (dict(access_level="abstract", support="not_supported", strength="", evidence_spans="", notes="n"), "abstract"),
    (dict(evidence_spans="a\nb\nc\nd\ne"), "at most 4"),
    (dict(time_spent_sec="١٢"), "integer"),
    (dict(time_spent_sec="x"), "integer"),
])
def test_validate_rules(kw, frag):
    assert any(frag in e for e in A.validate_row(row(**kw)))


def test_validate_ok_cases():
    assert A.validate_row(row()) == []
    assert A.validate_row(row(support="partially_supported", strength="overstated",
                              overstatement_types="number_changed; scope_widened")) == []
    assert A.validate_row(row(support="cannot_check", strength="", evidence_spans="", notes="n")) == []


def fill(path, uid, **kw):
    rows = A.read_sheet(path)
    for r in rows:
        if r["unit_id"] == uid:
            r.update(kw)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=A.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_validate_cli_exit_codes(env, capsys):
    tmp, units = env
    out = do_export(tmp)
    sheet = out / "sheet.csv"
    assert A.main(["validate", "--sheet", str(sheet), "--units", str(tmp / "U.jsonl")]) == 0
    fill(sheet, units[0].unit_id, support="supported", strength="", citation_role="evidence", confidence="2")
    assert A.main(["validate", "--sheet", str(sheet)]) == 1
    o = capsys.readouterr().out
    assert units[0].unit_id in o and "rows_with_errors" in o


def test_locate_span_exact_fuzzy_notfound():
    s, e, m = A.locate_span("Method E may improve accuracy", TEXT)
    assert m == "exact" and TEXT[s:e] == "Method E may improve accuracy"
    s, e, m = A.locate_span("Method E may improve accuracy on small datasetz in some experiments", TEXT)
    assert m == "fuzzy" and s is not None and 10 <= s <= 20
    assert A.locate_span("completely unrelated quantum chromodynamics", TEXT) == (None, None, "not_found")


def test_ingest_roundtrip(env):
    tmp, units = env
    out = do_export(tmp)
    sheet = out / "sheet.csv"
    u = units[0]
    fill(sheet, u.unit_id, support="supported", strength="overstated", overstatement_types="hedge_dropped",
         citation_role="evidence", confidence="3", time_spent_sec="60",
         evidence_spans="Method E may improve accuracy\nnot in the text at all zzz")
    res = A.ingest(sheet, tmp / "U.jsonl", tmp / "S.jsonl", tmp / "cache", tmp / "labels.jsonl")
    assert res["labels"] == 1 and res["span_not_found"] == [u.unit_id]
    rec = json.loads((tmp / "labels.jsonl").read_text())
    assert rec["annotator_id"] == "A1" and rec["overstatement_types"] == ["hedge_dropped"]
    assert rec["confidence"] == 3 and rec["time_spent_sec"] == 60 and rec["labeled_at"].endswith("Z")
    assert [o["span_match"] for o in rec["evidence_offsets"]] == ["exact", "not_found"]
    assert rec["evidence_offsets"][1]["start"] is None


def test_ingest_rejects_invalid(env):
    tmp, units = env
    out = do_export(tmp)
    fill(out / "sheet.csv", units[0].unit_id, support="supported")
    with pytest.raises(ValueError):
        A.ingest(out / "sheet.csv", tmp / "U.jsonl", tmp / "S.jsonl", tmp / "cache", tmp / "l.jsonl")


def test_reliability_pairing(tmp_path):
    def lab(uid, sup, stre, role="evidence", types=()):
        return {"unit_id": uid, "support": sup, "strength": stre, "citation_role": role, "confidence": 2,
                "overstatement_types": list(types)}
    a = [lab("1", "supported", "matches"), lab("2", "supported", "overstated", types=["other"]),
         lab("3", "not_supported", None), lab("4", "supported", "matches")]
    b = [lab("1", "supported", "matches"), lab("2", "supported", "matches"),
         lab("3", "not_supported", None), lab("5", "supported", "matches")]
    for n, d in (("a", a), ("b", b)):
        (tmp_path / f"{n}.jsonl").write_text("\n".join(json.dumps(x) for x in d), encoding="utf-8")
    res = A.reliability(tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "pairs.json")
    assert res["n_paired"] == 3 and res["only_in_a"] == 1 and res["only_in_b"] == 1
    assert res["agreement"]["support"] == 1.0
    assert res["agreement"]["strength"] == pytest.approx(2 / 3)
    assert res["counts"]["support"]["a"] == {"supported": 2, "not_supported": 1}
    pairs = json.loads((tmp_path / "pairs.json").read_text())
    assert pairs["unit_ids"] == ["1", "2", "3"] and pairs["strength"]["a"] == ["matches", "overstated", "None"]


def test_spans_newline_only():
    assert A.validate_row(row(evidence_spans="a || b")) == []  # one span now: " || " is not a separator
    assert A._spans("a\r\n b \n\nc") == ["a", "b", "c"]


def test_validate_rejects_duplicate_unit_ids(env):
    tmp, units = env
    sheet = do_export(tmp) / "sheet.csv"
    rows = A.read_sheet(sheet)
    rows.append(dict(rows[0]))
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=A.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    errs, _ = A.validate(sheet, tmp / "U.jsonl")
    assert any("duplicate" in m for m in errs[rows[0]["unit_id"]])
