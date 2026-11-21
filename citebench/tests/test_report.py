import json

from citebench.report import bucket, coverage, main
from citebench.units import Reference, SourceRecord, Unit, write_jsonl


def unit(key, year):
    return Unit(unit_id=key, survey_id="sv", source_file="a.tex", char_start=0, char_end=1, section=None,
                sentence_latex="x", sentence_text="x [CITE]", cite_key=key,
                reference=Reference(key=key, year=year) if year else None)


def rec(key, level, name=None, err=None):
    return SourceRecord(cite_key=key, survey_id="sv", access_level=level, source_name=name, error=err)


def test_bucket_edges():
    assert [bucket(y) for y in (1999, 2000, 2009, 2010, 2014, 2015, 2019, 2020, None)] == \
        ["<2000", "2000-2009", "2000-2009", "2010-2014", "2010-2014", "2015-2019", "2015-2019", "2020+", "unknown"]


def test_coverage_table_and_cli(tmp_path, capsys):
    u, s, j = tmp_path / "u.jsonl", tmp_path / "s.jsonl", tmp_path / "o.json"
    write_jsonl(u, [unit("a", 1997), unit("b", 1998), unit("c", 2021), unit("d", None)])
    write_jsonl(s, [rec("a", "abstract", "openalex", "full_text_failed:http_403"), rec("b", "none", err="not_found"),
                    rec("c", "full_text", "arxiv"), rec("d", "none", err="not_found; http_202_challenge"),
                    rec("c", "full_text", "arxiv")])  # duplicate: only the latest counts
    rep = coverage(u, s)
    t = rep["table"]
    assert t["<2000"] == {"n": 2, "full_text": 0, "abstract": 1, "none": 1,
                          "full_text_pct": 0.0, "abstract_pct": 50.0, "none_pct": 50.0}
    assert t["2020+"]["full_text_pct"] == 100.0 and t["unknown"]["none"] == 1
    assert t["total"]["n"] == 4 and t["total"]["full_text_pct"] == 25.0
    assert rep["source_name"] == {"arxiv": 1, "openalex": 1}
    assert rep["errors"]["not_found"] == 2 and rep["errors"]["http_202_challenge"] == 1
    main(["coverage", "--units", str(u), "--sources", str(s), "--json", str(j)])
    assert "2000-2009" in capsys.readouterr().out and json.loads(j.read_text())["table"]["total"]["n"] == 4
