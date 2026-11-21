import json

import pytest

from citebench.sample import QUOTAS, classify_role, finalize, manifest, reliability_subset, sample
from citebench.units import Reference, SourceRecord, Unit, make_unit_id


@pytest.mark.parametrize("text,stratum", [
    ("The model outperforms prior work by 12.5% on GLUE [CITE].", "evidence"),
    ("Results show that scaling helps [CITE].", "evidence"),
    ("We use the toolkit of [CITE] for training.", "method"),
    ("[CITE] introduce a framework based on retrieval.", "method"),
    ("Large language models have attracted much attention [CITE].", "context"),
])
def test_classifier(text, stratum):
    assert classify_role(text) == stratum


EV = "Method A outperforms B by 5% [CITE]."
ME = "We adopt the framework of [CITE]."
CO = "Language models are popular [CITE]."


def unit(survey, n, text, key="k", ref=True, start=None):
    start = n if start is None else start
    r = Reference(key=key, title="T") if ref is True else ref
    return Unit(unit_id=make_unit_id(survey, "m.tex", start, key), survey_id=survey, source_file="m.tex",
                char_start=start, char_end=start + 5, section=None, sentence_latex=text, sentence_text=text,
                cite_key=key, reference=r)


def corpus(per=60):
    out = {}
    for s in ("s1", "s2", "s3", "s4"):
        out[s] = [unit(s, n, (EV, ME, CO)[n % 3], key=f"k{n}") for n in range(per)]
    return out


def test_sample_caps_quotas_determinism():
    u = corpus()
    c1 = sample(u, per_survey_cap=10, oversample=2.0)
    assert c1 == sample(u, per_survey_cap=10, oversample=2.0)
    assert c1 != sample(u, per_survey_cap=10, oversample=2.0, seed=1)
    for st in QUOTAS:
        rows = [c for c in c1 if c["stratum"] == st]
        assert len(rows) <= 2 * QUOTAS[st]
        assert [r["draw_rank"] for r in rows] == list(range(len(rows)))
        for s in u:  # cap: 10 x 2 oversample per survey per stratum
            assert sum(r["survey_id"] == s for r in rows) <= 20
    # round-robin: first four ranks of a stratum come from four different surveys in sorted order
    ev = [c for c in c1 if c["stratum"] == "evidence"]
    assert [c["survey_id"] for c in ev[:4]] == ["s1", "s2", "s3", "s4"]
    assert len(ev) == 80  # survey pool cap 4 x 20 binds before oversample x quota (160)


def test_one_unit_per_sentence_and_unfetchable_excluded():
    us = [unit("s1", 0, EV, key=k, start=7) for k in ("a", "b", "c")]  # same sentence, three keys
    us += [unit("s1", 1, EV, ref=None, start=8), unit("s1", 2, EV, ref=Reference(key="x"), start=9)]
    got = sample({"s1": us})
    assert len(got) == 1 and got[0]["char_start"] == 7
    assert got == sample({"s1": list(reversed(us))})  # choice independent of input order


def rec(s, k, level):
    return SourceRecord(cite_key=k, survey_id=s, access_level=level)


def test_finalize_skips_none_and_reports_unmet():
    cands = [{"unit_id": f"u{i}", "survey_id": "s1", "source_file": "m.tex", "char_start": i, "char_end": i + 1,
              "cite_key": f"k{i}", "stratum": "evidence", "draw_rank": i} for i in range(6)]
    src = {("s1", "k0"): rec("s1", "k0", "none"), ("s1", "k1"): rec("s1", "k1", "abstract"),
           ("s1", "k2"): rec("s1", "k2", "full_text"), ("s1", "k3"): rec("s1", "k3", "full_text")}  # k4, k5 no record
    final, log = finalize(cands, src, quotas={"evidence": 3, "method": 1})
    assert [u["unit_id"] for u in final] == ["u1", "u2", "u3"]
    assert log["skipped_access_none"] == {"evidence": 1}
    assert log["unmet"] == {"method": {"quota": 1, "kept": 0}}


def test_finalize_survey_cap_not_relaxed():
    cands = [{"unit_id": f"u{i}", "survey_id": "s1", "source_file": "m", "char_start": i, "char_end": i,
              "cite_key": f"k{i}", "stratum": "evidence", "draw_rank": i} for i in range(5)]
    src = {("s1", f"k{i}"): rec("s1", f"k{i}", "full_text") for i in range(5)}
    final, log = finalize(cands, src, quotas={"evidence": 4}, per_survey_cap=2)
    assert len(final) == 2 and log["unmet"]["evidence"]["kept"] == 2 and log["skipped_survey_cap"]["evidence"] == 3


def test_reliability_subset_proportional_and_manifest_has_no_text():
    final = [{"unit_id": f"{s}{i}", "survey_id": "s1", "source_file": "m", "char_start": i, "char_end": i + 1,
              "cite_key": "k", "stratum": s, "draw_rank": i, "access_level": "full_text",
              "sentence_text": "SECRET SENTENCE"}
             for s, n in (("evidence", 80), ("method", 60), ("context", 60)) for i in range(n)]
    sub = reliability_subset(final)
    assert len(sub) == 50 and sub == reliability_subset(final)
    by = {s: sum(u.startswith(s) for u in sub) for s in QUOTAS}
    assert by == {"evidence": 20, "method": 15, "context": 15}
    for u in final:
        u["in_reliability_subset"] = u["unit_id"] in sub
    m = json.dumps(manifest(final, {"unmet": {}}))
    assert "SECRET" not in m and "sentence_text" not in m and "title" not in m
    assert json.loads(m)["counts"]["reliability"] == 50
