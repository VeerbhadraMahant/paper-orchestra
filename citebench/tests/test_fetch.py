import json
import sys

import pymupdf
import requests

from citebench.fetch import Fetcher, latest_records, rebuild_abstract, run
from citebench.units import Reference, SourceRecord, Unit, read_jsonl, write_jsonl

TITLE = "Attention Is All You Need"


def make_pdf(chars_per_page=1200, pages=3) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((40, 40), "\n".join(["lorem ipsum dolor sit amet " * 2] * (chars_per_page // 56)), fontsize=8)
    return doc.tobytes()


def atom(title=TITLE, abstract="We propose the Transformer."):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v7</id>'
            f"<title>{title}</title><summary>\n {abstract}\n</summary></entry></feed>")


class R:
    def __init__(self, status=200, text="", content=None, headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}
        self.content = text.encode() if content is None else content

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self):
        pass


class Stub:
    """Session stand-in: routes maps a URL substring to a response or a list consumed in order."""

    def __init__(self, routes=None):
        self.routes, self.calls = routes or {}, []

    def get(self, url, **kw):
        self.calls.append(url)
        for sub, resp in self.routes.items():
            if sub in url:
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        return R(404, "{}")

    def n(self, sub):
        return sum(sub in c for c in self.calls)


def fetcher(tmp_path, routes=None, sleeps=None, **kw):
    s = Stub(routes)
    return Fetcher(tmp_path / "cache", session=s, sleep=(sleeps.append if sleeps is not None else lambda x: None), **kw), s


def s2(title=TITLE, abstract="An abstract.", arxiv=None, pdf=None):
    d = {"paperId": "abc", "title": title, "abstract": abstract, "externalIds": {"ArXiv": arxiv} if arxiv else {}}
    if pdf:
        d["openAccessPdf"] = {"url": pdf}
    return d


def fetch(f, **ref):
    return f.fetch_reference("sv", "k", Reference(key="k", **ref))


def test_arxiv_full_text(tmp_path):
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/1706.03762": R(content=make_pdf())})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.source_name, r.match_score, r.error) == ("full_text", "arxiv", 100, None)
    txt = (tmp_path / "cache" / r.text_path).read_text(encoding="utf-8")
    assert "lorem ipsum" in txt and len(txt) >= 2000
    import hashlib
    assert r.text_sha256 == hashlib.sha256(txt.encode()).hexdigest()
    assert r.retrieved_at.endswith("+00:00")
    assert not any("semanticscholar" in c for c in s.calls)


def test_doi_via_s2_with_open_access_pdf(tmp_path):
    body = json.dumps(s2(pdf="https://oa.example.org/p.pdf"))
    f, s = fetcher(tmp_path, {"paper/DOI:10.1/xyz": R(text=body), "oa.example.org": R(content=make_pdf())})
    r = fetch(f, title=TITLE, doi="https://doi.org/10.1/xyz")
    assert (r.access_level, r.source_name, r.source_url) == ("full_text", "semantic_scholar", "https://oa.example.org/p.pdf")
    assert s.n("paper/DOI:10.1/xyz") == 1


def test_title_match_accepted_with_arxiv_full_text(tmp_path):
    body = json.dumps({"data": [s2(title=TITLE + ".", arxiv="1706.03762")]})
    f, s = fetcher(tmp_path, {"paper/search/match": R(text=body), "arxiv.org/pdf/1706.03762": R(content=make_pdf())})
    r = fetch(f, title=TITLE.lower())
    assert (r.access_level, r.source_name) == ("full_text", "arxiv")
    assert r.match_score >= 90 and r.matched_title == TITLE + "."


def test_low_match_rejected_and_score_recorded(tmp_path):
    body = json.dumps({"data": [s2(title="Deep Residual Learning for Image Recognition", pdf="https://oa.example.org/p.pdf")]})
    f, s = fetcher(tmp_path, {"paper/search/match": R(text=body)})
    r = fetch(f, title=TITLE)
    assert (r.access_level, r.error, r.text_path) == ("none", "low_title_match", None)
    assert r.matched_title == "Deep Residual Learning for Image Recognition" and 0 <= r.match_score < 90
    assert s.n("oa.example.org") == 0  # rejected paper's text is never downloaded


def test_abstract_only(tmp_path):
    f, _ = fetcher(tmp_path, {"paper/search/match": R(text=json.dumps({"data": [s2()]}))})
    r = fetch(f, title=TITLE)
    assert (r.access_level, r.source_name, r.error) == ("abstract", "semantic_scholar", None)
    assert (tmp_path / "cache" / r.text_path).read_text(encoding="utf-8") == "An abstract."


def test_rebuild_abstract():
    assert rebuild_abstract({"world": [1, 3], "Hello": [0], "again": [2]}) == "Hello world again world"
    assert rebuild_abstract(None) is None


def test_openalex_fallback_inverted_index(tmp_path):
    w = {"id": "https://openalex.org/W1", "title": TITLE, "abstract_inverted_index": {"Transformers": [0], "attend": [1]},
         "best_oa_location": {"pdf_url": None}, "open_access": {"oa_url": "https://example.org/landing"}}
    f, s = fetcher(tmp_path, {"api.openalex.org": R(text=json.dumps({"results": [w]}))})
    r = fetch(f, title=TITLE)  # semantic scholar answers 404
    assert (r.access_level, r.source_name) == ("abstract", "openalex")
    assert (tmp_path / "cache" / r.text_path).read_text(encoding="utf-8") == "Transformers attend"
    assert s.n("example.org/landing") == 0  # not a PDF url, not downloaded


def test_retry_after_429_then_success(tmp_path):
    sleeps = []
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": [R(429, headers={"Retry-After": "7"}), R(text=atom())]}, sleeps)
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert r.access_level == "abstract" and s.n("export.arxiv.org") == 2
    assert 7.0 in sleeps


def test_persistent_500_gives_error_after_retries(tmp_path):
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(500), "api.semanticscholar": R(500), "api.openalex": R(500)})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.error) == ("none", "http_500")
    assert s.n("export.arxiv.org") == 4  # 1 try + 3 retries


def test_network_exception_is_recorded(tmp_path):
    class Boom(Stub):
        def get(self, url, **kw):
            raise requests.ConnectionError("down")

    f = Fetcher(tmp_path / "c", session=Boom(), sleep=lambda x: None)
    assert fetch(f, title=TITLE).error == "network_error"


def test_all_sources_empty(tmp_path):
    f, _ = fetcher(tmp_path)
    r = fetch(f, title=TITLE, doi="10.1/none")
    assert (r.access_level, r.error) == ("none", "not_found")


def test_missing_bib_entry_and_no_identifier(tmp_path):
    f, s = fetcher(tmp_path)
    assert f.fetch_reference("sv", "k", None).error == "missing_bib_entry"
    assert f.fetch_reference("sv", "k", Reference(key="k", venue="X")).error == "no_identifier"
    assert s.calls == []


def test_non_pdf_rejected_falls_back_to_abstract(tmp_path):
    f, _ = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(text="<html>login</html>")})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.error) == ("abstract", "full_text_failed:not_pdf")


def test_short_pdf_rejected(tmp_path):
    f, _ = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(content=make_pdf(200, 1))})
    assert fetch(f, title=TITLE, arxiv_id="1706.03762").error == "full_text_failed:pdf_too_short"


def unit(key, ref):
    return Unit(unit_id=key, survey_id="sv", source_file="a.tex", char_start=0, char_end=1, section=None,
                sentence_latex="x", sentence_text="x [CITE]", cite_key=key, reference=ref)


def routes():
    return {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(content=make_pdf())}


def test_cache_hit_makes_no_calls(tmp_path):
    units = tmp_path / "u.jsonl"
    write_jsonl(units, [unit("a", Reference(key="a", title=TITLE, arxiv_id="1706.03762"))])
    f1, s1 = fetcher(tmp_path, routes())
    r1 = run(units, tmp_path / "o1.jsonl", f1)
    assert s1.calls
    f2, s2_ = fetcher(tmp_path)  # same cache dir, session that would 404 and record
    r2 = run(units, tmp_path / "o2.jsonl", f2)
    assert s2_.calls == []
    assert (r2[0].access_level, r2[0].text_sha256) == ("full_text", r1[0].text_sha256)


def test_resume_skips_existing_and_dedups(tmp_path):
    units, out = tmp_path / "u.jsonl", tmp_path / "o.jsonl"
    ra = Reference(key="a", title=TITLE, arxiv_id="1706.03762")
    # key "a" appears in two units, "b" has no bib entry
    write_jsonl(units, [unit("a", ra), unit("a", ra), unit("b", None)])
    old = SourceRecord(cite_key="a", survey_id="sv", access_level="abstract", source_name="old")
    write_jsonl(out, [old])
    f, s = fetcher(tmp_path, routes())
    run(units, out, f)
    recs = list(read_jsonl(out, SourceRecord))
    assert [(r.cite_key, r.source_name, r.error) for r in recs] == [("a", "old", None), ("b", None, "missing_bib_entry")]
    assert s.calls == []


def test_run_survives_internal_error(tmp_path):
    units, out = tmp_path / "u.jsonl", tmp_path / "o.jsonl"
    write_jsonl(units, [unit("a", Reference(key="a", title=TITLE)), unit("b", None)])
    f, _ = fetcher(tmp_path)
    f.fetch_reference = lambda sid, key, ref: 1 / 0 if key == "a" else Fetcher.fetch_reference(f, sid, key, ref)
    recs = run(units, out, f)
    assert [r.error for r in recs] == ["internal:ZeroDivisionError", "missing_bib_entry"]


# ---- review fixes ----

def pdf_routes(**extra):
    return {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(content=make_pdf()), **extra}


def test_resume_retries_transient_and_uses_last_record(tmp_path):
    units, out = tmp_path / "u.jsonl", tmp_path / "o.jsonl"
    ra = Reference(key="a", title=TITLE, arxiv_id="1706.03762")
    write_jsonl(units, [unit("a", ra), unit("b", Reference(key="b", title=TITLE, arxiv_id="1706.03762"))])
    write_jsonl(out, [SourceRecord(cite_key="a", survey_id="sv", access_level="none", error="http_503"),
                      SourceRecord(cite_key="b", survey_id="sv", access_level="none", error="low_title_match")])
    f, s = fetcher(tmp_path, pdf_routes())
    recs = run(units, out, f)
    assert s.calls  # "a" retried, "b" (permanent) not
    assert {r.cite_key: r.access_level for r in recs} == {"a": "full_text", "b": "none"}
    assert len(list(read_jsonl(out, SourceRecord))) == 3  # appended
    assert latest_records(out)[("sv", "a")].access_level == "full_text"
    f2, s2_ = fetcher(tmp_path)
    run(units, out, f2)
    assert s2_.calls == []


def test_resume_internal_error_is_retried(tmp_path):
    units, out = tmp_path / "u.jsonl", tmp_path / "o.jsonl"
    write_jsonl(units, [unit("b", None)])
    write_jsonl(out, [SourceRecord(cite_key="b", survey_id="sv", access_level="none", error="internal:ZeroDivisionError")])
    f, _ = fetcher(tmp_path)
    assert run(units, out, f)[0].error == "missing_bib_entry"


def test_pdf_size_cap_content_length(tmp_path):
    big = R(content=make_pdf(), headers={"Content-Length": str(100 * 1024 * 1024)})
    big.iter_content = lambda size: (_ for _ in ()).throw(AssertionError("body must not be read"))
    f, _ = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": big})
    assert fetch(f, title=TITLE, arxiv_id="1706.03762").error == "full_text_failed:pdf_too_large"


def test_pdf_size_cap_streaming_total(tmp_path, monkeypatch):
    monkeypatch.setattr("citebench.fetch.MAX_PDF_BYTES", 1000)
    f, _ = fetcher(tmp_path, pdf_routes())  # no Content-Length header; body is larger than 1000 bytes
    assert fetch(f, title=TITLE, arxiv_id="1706.03762").error == "full_text_failed:pdf_too_large"


def test_falls_through_to_later_source_with_full_text(tmp_path):
    w = {"id": "W1", "title": TITLE, "best_oa_location": {"pdf_url": "https://oa.example.org/p.pdf"}}
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(text="<html/>"),
                              "api.openalex.org": R(text=json.dumps({"results": [w]})),
                              "oa.example.org": R(content=make_pdf())})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.source_name, r.source_url) == ("full_text", "openalex", "https://oa.example.org/p.pdf")


def test_abstract_kept_when_no_full_text_anywhere(tmp_path):
    w = {"id": "W1", "title": TITLE, "best_oa_location": {"pdf_url": "https://oa.example.org/p.pdf"}}
    f, _ = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(text="<html/>"),
                              "api.openalex.org": R(text=json.dumps({"results": [w]})),
                              "oa.example.org": R(text="<html/>")})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.source_name) == ("abstract", "arxiv") and r.error == "full_text_failed:not_pdf"


def test_mismatched_later_candidate_not_tried(tmp_path):
    body = json.dumps({"data": [s2(title="Something Else Entirely", pdf="https://oa.example.org/p.pdf")]})
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom()), "arxiv.org/pdf/": R(text="<html/>"),
                              "paper/search/match": R(text=body)})
    fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert s.n("oa.example.org") == 0


def test_corrupted_cache_files_are_misses(tmp_path):
    f, s = fetcher(tmp_path, pdf_routes())
    r1 = fetch(f, title=TITLE, arxiv_id="1706.03762")
    for p in (tmp_path / "cache").glob("*/*.json"):
        p.write_text("{not json", encoding="utf-8")
    r2 = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert r2.text_sha256 == r1.text_sha256 and r2.access_level == "full_text"
    assert all(json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "cache").glob("*/*.json"))


def test_malformed_last_line_skipped_and_next_append_on_new_line(tmp_path):
    units, out = tmp_path / "u.jsonl", tmp_path / "o.jsonl"
    write_jsonl(units, [unit("a", None), unit("b", None)])
    write_jsonl(out, [SourceRecord(cite_key="a", survey_id="sv", access_level="none", error="missing_bib_entry")])
    with open(out, "a", encoding="utf-8") as fh:
        fh.write('{"cite_key": "b", "surv')  # torn write, no newline
    f, _ = fetcher(tmp_path)
    run(units, out, f)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and lines[1].startswith('{"cite_key": "b", "surv')
    assert set(latest_records(out)) == {("sv", "a"), ("sv", "b")}


def test_doctype_rejected_and_not_cached(tmp_path):
    evil = '<?xml version="1.0"?><!DOCTYPE feed [<!ENTITY a "x">]>' + atom()
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(text=evil)})
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert (r.access_level, r.error) == ("none", "bad_xml_doctype")
    assert not list((tmp_path / "cache").glob("http/*arxiv*")) and s.n("export.arxiv.org") == 1


def test_arxiv_uses_https(tmp_path):
    f, s = fetcher(tmp_path, {"export.arxiv.org/api": R(text=atom())})
    fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert s.calls[0].startswith("https://export.arxiv.org/")


def test_only_200_and_404_are_cached(tmp_path):
    f, s = fetcher(tmp_path, {"api.semanticscholar": R(403), "api.openalex": R(text="not json")})
    fetch(f, title=TITLE)
    assert not (tmp_path / "cache" / "http").exists() or not list((tmp_path / "cache" / "http").glob("*.json"))
    fetch(f, title=TITLE)
    assert s.n("api.semanticscholar") == 2  # asked again, not served from cache


def test_404_is_cached(tmp_path):
    f, s = fetcher(tmp_path)
    fetch(f, title=TITLE)
    fetch(f, title=TITLE)
    assert s.n("api.openalex") == 1


def test_pymupdf_import_error_falls_back_to_abstract(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pymupdf", None)  # makes `import pymupdf` raise ImportError
    f, _ = fetcher(tmp_path, pdf_routes())
    r = fetch(f, title=TITLE, arxiv_id="1706.03762")
    assert r.access_level == "abstract" and r.error.startswith("full_text_failed:pdf_error:")
    assert not (tmp_path / "cache" / "pdf").exists()  # environment failure is not cached
