import csv
import json

import pytest

from citebench import planted as P
from citebench.units import Reference, Unit, make_unit_id, read_jsonl, write_jsonl


def mk(i, key, text, survey="s1", cocited=()):
    return Unit(unit_id=make_unit_id(survey, "m.tex", i, key), survey_id=survey, source_file="m.tex", char_start=i,
                char_end=i + 5, section="S", sentence_latex=text, sentence_text=text, cite_key=key,
                cocited_keys=list(cocited), reference=Reference(key=key, title="Title " + key))


def lab(u, sup="supported", stre="matches", conf=2, spans=("x",)):
    return {"unit_id": u.unit_id, "support": sup, "strength": stre, "confidence": conf,
            "evidence_spans": list(spans)}


@pytest.fixture
def env(tmp_path):
    u1 = mk(1, "a", "Method A cuts error by 30% [CITE].")
    u2 = mk(2, "b", "Method B helps in general [CITE].")
    u3 = mk(3, "c", "Method C is good [CITE].")
    u4 = mk(4, "d", "Method D is fine [CITE].")
    u5 = mk(5, "e", "Method E is fine [CITE].")
    units = [u1, u2, u3, u4, u5]
    labels = [lab(u1, spans=("Error may fall by 30%, correlated with size.",)), lab(u2, conf=1),
              lab(u3, sup="partially_supported"), lab(u4, stre="overstated"), lab(u5, spans=("plain",))]
    write_jsonl(tmp_path / "U.jsonl", units)
    (tmp_path / "L.jsonl").write_text("\n".join(json.dumps(x) for x in labels), encoding="utf-8")
    return tmp_path, units


def test_eligible_filter_and_hints(env):
    tmp, units = env
    el = P.eligible(tmp / "L.jsonl", tmp / "U.jsonl")
    assert [e["unit_id"] for e in el] == [units[0].unit_id, units[4].unit_id]
    h = el[0]["hints"]
    assert h["number_changed"] and h["hedge_dropped"] and h["causal_from_correlational"] and h["wrong_paper"]
    h2 = el[1]["hints"]
    assert not h2["number_changed"] and not h2["hedge_dropped"] and not h2["causal_from_correlational"]


def test_template_all_and_selections(env):
    tmp, units = env
    n = P.template(tmp / "L.jsonl", tmp / "U.jsonl", tmp / "t.csv", all_eligible=True)
    rows = list(csv.DictReader(open(tmp / "t.csv", encoding="utf-8-sig")))
    assert n == len(rows) and {r["type"] for r in rows} <= set(P.TYPES)
    wp = next(r for r in rows if r["type"] == "wrong_paper" and r["unit_id"] == units[0].unit_id)
    assert wp["wrong_paper_key"] in {"b", "c", "d", "e"} and wp["edited_sentence_text"] == ""
    sel = tmp / "sel.csv"
    sel.write_text(f"unit_id,type\n{units[0].unit_id},negation\n", encoding="utf-8")
    assert P.template(tmp / "L.jsonl", tmp / "U.jsonl", tmp / "t2.csv", selections=sel) == 1
    sel.write_text(f"unit_id,type\n{units[2].unit_id},negation\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not eligible"):
        P.template(tmp / "L.jsonl", tmp / "U.jsonl", tmp / "t3.csv", selections=sel)


def write_tpl(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=P.TEMPLATE_COLS)
        w.writeheader()
        w.writerows(rows)


def trow(u, t, edited="", key="", pid=None):
    return {"planted_id": pid or f"{u.unit_id}:{t}", "unit_id": u.unit_id, "type": t,
            "original_sentence_text": u.sentence_text, "edited_sentence_text": edited, "wrong_paper_key": key,
            "notes": ""}


def test_build_round_trip(env):
    tmp, units = env
    u = units[0]
    write_tpl(tmp / "t.csv", [trow(u, "number_changed", "Method A cuts error by 60% [CITE]."),
                              trow(u, "wrong_paper", key="b"),
                              trow(u, "negation", "Method A does not cut error [CITE].")])
    res = P.build(tmp / "t.csv", tmp / "U.jsonl", tmp / "out")
    assert res == {"planted": 3, "controls": 1}
    pu = list(read_jsonl(tmp / "out" / "planted_units.jsonl", Unit))
    meta = [json.loads(x) for x in open(tmp / "out" / "planted_meta.jsonl", encoding="utf-8")]
    assert len(pu) == 4 and len({p.unit_id for p in pu}) == 4
    by_type = {m["type"]: m for m in meta}
    assert set(by_type) == {"number_changed", "wrong_paper", "negation", "none"}
    nc = next(p for p in pu if p.unit_id == by_type["number_changed"]["planted_unit_id"])
    assert nc.sentence_text.endswith("60% [CITE].") and nc.cite_key == "a"
    wp = next(p for p in pu if p.unit_id == by_type["wrong_paper"]["planted_unit_id"])
    assert wp.cite_key == "b" and wp.reference.title == "Title b" and wp.sentence_text == u.sentence_text
    ctl = next(p for p in pu if p.unit_id == by_type["none"]["planted_unit_id"])
    assert ctl.sentence_text == u.sentence_text and ctl.cite_key == "a"
    assert by_type["none"]["gold"]["expected_detected"] is False
    assert by_type["wrong_paper"]["gold"]["rule"] == "unsupported_or_contradicted"
    assert by_type["number_changed"]["gold"]["rule"] == "overstated_or_unsupported"
    assert all(m["unit_id"] == u.unit_id for m in meta)


def test_build_rejections(env):
    tmp, units = env
    u = units[0]
    for rows, frag in [
        ([trow(u, "negation", "")], "empty"),
        ([trow(u, "negation", u.sentence_text)], "identical"),
        ([trow(u, "wrong_paper", key="nope")], "not a cited key"),
        ([trow(u, "wrong_paper", key="a")], "equals the original"),
        ([trow(u, "wrong_paper", edited="changed", key="b")], "source only"),
        ([trow(u, "negation", "x", pid="p"), trow(u, "hedge_dropped", "y", pid="p")], "duplicate"),
    ]:
        write_tpl(tmp / "t.csv", rows)
        with pytest.raises(ValueError, match=frag):
            P.build(tmp / "t.csv", tmp / "U.jsonl", tmp / "out")
        assert not (tmp / "out" / "planted_units.jsonl").exists()
