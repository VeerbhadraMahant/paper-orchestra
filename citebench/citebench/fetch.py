"""Find the best freely available text (full text, else abstract) for each cited reference.

Free sources only, no keys, no contact details: arXiv, Semantic Scholar (unauthenticated), OpenAlex,
ACL Anthology and Europe PMC (both reached through Semantic Scholar external ids).
Bot protection is never worked around: 403s and challenge pages are recorded and the next source is tried.
Every HTTP response is cached on disk, so a rerun makes no network calls.

Usage: python -m citebench.fetch units.jsonl --out sources.jsonl --cache .cache/citebench
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import quote, urlparse

import requests
from thefuzz import fuzz

from .units import Reference, SourceRecord, Unit, _from_dict, read_jsonl

HEADERS = {"User-Agent": "citebench/0.0.1 (research benchmark)"}
TIMEOUT = 20
MAX_RETRIES = 3
MAX_PDF_BYTES = 40 * 1024 * 1024
MIN_TEXT_CHARS = 2000
# minimum seconds between requests, per rate-limit group
MIN_INTERVAL = {"semanticscholar": 1.1, "arxiv": 3.0, "aclanthology.org": 1.0, "ebi.ac.uk": 1.0}
S2 = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,abstract,year,externalIds,openAccessPdf"
OPENALEX = "https://api.openalex.org/works"
OA_SELECT = "id,title,display_name,abstract_inverted_index,best_oa_location,primary_location,locations,open_access"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
ATOM = "{http://www.w3.org/2005/Atom}"
TRANSIENT = re.compile(r"network_error|http_429|http_5\d\d|internal:")
CACHEABLE_PDF_ERR = re.compile(r"not_pdf|pdf_too_large|pdf_unreadable|pdf_too_short|http_4(?!29)")


class FetchError(Exception):
    """Failure with a short machine-readable reason as its message."""


@dataclass
class Cand:
    name: str
    url: str
    title: Optional[str]
    abstract: Optional[str]
    pdfs: tuple[str, ...] = ()  # candidate PDF urls, best first
    xml: Optional[str] = None  # Europe PMC full-text XML url


def norm_title(t: Optional[str]) -> str:
    return re.sub(r"[\W_]+", " ", (t or "").replace("{", "").replace("}", "").casefold()).strip()


def clean_doi(doi: str) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi.strip(), flags=re.I)


def rebuild_abstract(inv: Optional[dict]) -> Optional[str]:
    """OpenAlex stores abstracts as {word: [positions]}; put the words back in order."""
    if not inv:
        return None
    words = {pos: w for w, positions in inv.items() for pos in positions}
    return " ".join(words[i] for i in sorted(words))


def _atomic_write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def _read_cache(p: Path, need: tuple[str, ...]) -> Optional[dict]:
    """Cached JSON dict containing one of `need`, else None (missing or corrupt file is a cache miss)."""
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and any(k in d for k in need) else None


def _validate(kind: str, body: str) -> None:
    if kind == "json":
        try:
            json.loads(body)
        except ValueError:
            raise FetchError("bad_json")
    elif kind == "xml":
        # shortcut: stdlib parser, so DTD/entity input is refused outright instead of parsed safely
        if re.search(r"<!(DOCTYPE|ENTITY)", body, re.I):
            raise FetchError("bad_xml_doctype")
        try:
            ET.fromstring(body)
        except ET.ParseError:
            raise FetchError("bad_xml")


def _is_transient(r: SourceRecord) -> bool:
    return r.access_level == "none" and bool(r.error and TRANSIENT.search(r.error))


def latest_records(path: str | Path) -> dict[tuple[str, str], SourceRecord]:
    """Last record per (survey_id, cite_key); malformed lines (e.g. a torn final write) are skipped with a warning."""
    out: dict[tuple[str, str], SourceRecord] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = _from_dict(SourceRecord, json.loads(line))
            except (ValueError, TypeError, KeyError):
                print(f"warning: {path}:{n}: skipping malformed line", file=sys.stderr)
                continue
            out[(r.survey_id, r.cite_key)] = r
    return out


def _group(url: str) -> Optional[str]:
    host = urlparse(url).netloc
    return next((g for g in MIN_INTERVAL if g in host), None)


class Fetcher:
    def __init__(self, cache: str | Path, session=None, sleep=time.sleep, clock=time.monotonic,
                 min_match: float = 90):
        self.min_match = min_match
        self.cache = Path(cache)
        self.session = session or requests.Session()
        self.sleep, self.clock = sleep, clock
        self._last: dict[str, float] = {}

    # ---- HTTP with retry, throttle, disk cache ----

    def _throttle(self, url: str) -> None:
        g = _group(url)
        if g is None:
            return
        wait = MIN_INTERVAL[g] - (self.clock() - self._last.get(g, float("-inf")))
        if wait > 0:
            self.sleep(wait)
        self._last[g] = self.clock()

    def _get(self, url: str, stream: bool = False):
        """GET with retry on 429/5xx/network errors; returns the first other response."""
        r = None
        for attempt in range(MAX_RETRIES + 1):
            self._throttle(url)
            try:
                r = self.session.get(url, timeout=TIMEOUT, headers=HEADERS, stream=stream)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code != 429 and r.status_code < 500:
                return r
            if r is not None and hasattr(r, "close"):
                r.close()
            if attempt < MAX_RETRIES:
                ra = (r.headers.get("Retry-After") or "") if r is not None else ""
                # Retry-After as an HTTP date is ignored; exponential backoff is used instead
                self.sleep(min(float(ra), 60.0) if re.fullmatch(r"\d+(\.\d+)?", ra) else 2.0**attempt)
        raise FetchError(f"http_{r.status_code}" if r is not None else "network_error")

    def _body(self, url: str, kind: str = "json") -> Optional[str]:
        """Response text of a GET, cached on disk; None on 404; FetchError on other non-200 or unparseable bodies.

        Only 200 responses that parse as `kind`, and 404s, are cached."""
        p = self.cache / "http" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        d = _read_cache(p, ("status",))
        if d is None:
            r = self._get(url)
            d = {"url": url, "status": r.status_code, "body": r.text}
            if d["status"] == 200:
                _validate(kind, d["body"])
            if d["status"] in (200, 404):
                _atomic_write(p, json.dumps(d))
        if d["status"] == 404:
            return None
        if d["status"] != 200:
            raise FetchError("http_202_challenge" if d["status"] == 202 else f"http_{d['status']}")
        return d["body"]

    def _json(self, url: str):
        body = self._body(url)
        if body is None:
            return None
        try:
            return json.loads(body)
        except ValueError:
            raise FetchError("bad_json")

    # ---- text storage ----

    def _store(self, text: str) -> str:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        _atomic_write(self.cache / "texts" / f"{sha}.txt", text)
        return sha

    def _pdf_sha(self, url: str) -> str:
        """Download a PDF, store its extracted text, return the text sha256. Deterministic outcomes are cached by URL."""
        p = self.cache / "pdf" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        d = _read_cache(p, ("error", "sha256"))
        if d:
            if d.get("error"):
                raise FetchError(d["error"])
            return d["sha256"]
        try:
            sha = self._extract_pdf(url)
        except FetchError as e:
            if CACHEABLE_PDF_ERR.match(str(e)):  # transient or environment failures are retried next run
                _atomic_write(p, json.dumps({"url": url, "error": str(e)}))
            raise
        _atomic_write(p, json.dumps({"url": url, "sha256": sha}))
        return sha

    def _xml_sha(self, url: str) -> str:
        """Europe PMC full-text XML to plain text, stored; same minimum-length rule as PDFs."""
        body = self._body(url, "xml")  # refuses DOCTYPE/ENTITY
        if body is None:
            raise FetchError("http_404")
        text = " ".join(" ".join(ET.fromstring(body).itertext()).split())
        if len(text) < MIN_TEXT_CHARS:
            raise FetchError("xml_too_short")
        return self._store(text)

    def _extract_pdf(self, url: str) -> str:
        try:
            return self._extract_pdf_unsafe(url)
        except FetchError:
            raise
        except Exception as e:  # ImportError, pymupdf errors: let the abstract fallback run
            raise FetchError(f"pdf_error:{type(e).__name__}")

    def _extract_pdf_unsafe(self, url: str) -> str:
        import pymupdf

        r = self._get(url, stream=True)
        try:
            if r.status_code != 200:
                raise FetchError("http_202_challenge" if r.status_code == 202 else f"http_{r.status_code}")
            cl = r.headers.get("Content-Length") or ""
            if cl.isdigit() and int(cl) > MAX_PDF_BYTES:
                raise FetchError("pdf_too_large")
            buf = bytearray()
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > MAX_PDF_BYTES:
                    raise FetchError("pdf_too_large")
        finally:
            r.close()
        data = bytes(buf)
        if not data.startswith(b"%PDF"):
            raise FetchError("not_pdf")
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                text = "\n".join(page.get_text() for page in doc)
        except Exception:
            raise FetchError("pdf_unreadable")
        if len(text.strip()) < MIN_TEXT_CHARS:
            raise FetchError("pdf_too_short")
        return self._store(text)

    # ---- sources: each returns a Cand, None if not found, or raises FetchError ----

    def _arxiv(self, arxiv_id: str) -> Optional[Cand]:
        aid = re.sub(r"^arxiv:", "", arxiv_id.strip(), flags=re.I)
        body = self._body(f"https://export.arxiv.org/api/query?id_list={quote(aid)}", "xml")
        if body is None:
            return None
        entry = ET.fromstring(body).find(ATOM + "entry")  # body already validated by _body
        if entry is None or "api/errors" in (entry.findtext(ATOM + "id") or ""):
            return None
        t, s = (" ".join((entry.findtext(ATOM + k) or "").split()) or None for k in ("title", "summary"))
        return Cand("arxiv", f"https://arxiv.org/abs/{aid}", t, s, (f"https://arxiv.org/pdf/{aid}",))

    def _arxiv_title(self, ref: Reference) -> Optional[Cand]:
        """Last resort: first title-search hit that matches the title and, if the year is known, is within 1 year."""
        q = quote(f'ti:"{ref.title}"', safe=":")
        body = self._body(f"https://export.arxiv.org/api/query?search_query={q}&max_results=3", "xml")
        for entry in (ET.fromstring(body).findall(ATOM + "entry") if body else []):
            t, s = (" ".join((entry.findtext(ATOM + k) or "").split()) or None for k in ("title", "summary"))
            if fuzz.token_sort_ratio(norm_title(ref.title), norm_title(t)) < self.min_match:
                continue
            year = (entry.findtext(ATOM + "published") or "")[:4]  # first-version date
            if ref.year and not (year.isdigit() and abs(int(year) - ref.year) <= 1):
                continue
            aid = re.sub(r"v\d+$", "", (entry.findtext(ATOM + "id") or "").rsplit("/abs/", 1)[-1])
            if aid:
                return Cand("arxiv_title_search", f"https://arxiv.org/abs/{aid}", t, s, (f"https://arxiv.org/pdf/{aid}",))
        return None

    def _s2(self, ref: Reference) -> Optional[Cand]:
        lookups = []
        if ref.doi:
            lookups.append((f"{S2}/paper/DOI:{quote(clean_doi(ref.doi), safe='/:()')}?fields={S2_FIELDS}", False))
        if ref.title:
            lookups.append((f"{S2}/paper/search/match?query={quote(ref.title)}&fields={S2_FIELDS}", True))
        for url, wrapped in lookups:
            d = self._json(url)
            paper = ((d or {}).get("data") or [None])[0] if wrapped else d
            if not paper:
                continue
            ids = paper.get("externalIds") or {}
            oa = (paper.get("openAccessPdf") or {}).get("url")
            pdfs = [u for u in (f"https://arxiv.org/pdf/{ids['ArXiv']}" if ids.get("ArXiv") else None,
                                f"https://aclanthology.org/{ids['ACL']}.pdf" if ids.get("ACL") else None, oa) if u]
            pmc = str(ids.get("PubMedCentral") or "").removeprefix("PMC")
            return Cand("semantic_scholar", f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}",
                        paper.get("title"), paper.get("abstract"), tuple(dict.fromkeys(pdfs)),
                        f"{EPMC}/PMC{pmc}/fullTextXML" if pmc else None)
        return None

    def _openalex(self, ref: Reference) -> Optional[Cand]:
        if ref.doi:
            url = f"{OPENALEX}?filter=doi:{quote(clean_doi(ref.doi), safe='/:()')}&select={OA_SELECT}"
        elif ref.title:
            url = f"{OPENALEX}?search={quote(ref.title)}&per-page=1&select={OA_SELECT}"
        else:
            return None
        d = self._json(url)
        w = ((d or {}).get("results") or [None])[0]
        if not w:
            return None
        pdfs = [(w.get("best_oa_location") or {}).get("pdf_url")]  # best location is open access by definition
        pdfs += [loc.get("pdf_url") for loc in [w.get("primary_location"), *(w.get("locations") or [])]
                 if loc and loc.get("is_oa")]
        oa = (w.get("open_access") or {}).get("oa_url")
        if oa and re.search(r"\.pdf($|\?)|/pdf", oa):
            pdfs.append(oa)
        return Cand("openalex", w.get("id") or url, w.get("title") or w.get("display_name"),
                    rebuild_abstract(w.get("abstract_inverted_index")), tuple(dict.fromkeys(u for u in pdfs if u)))

    def _candidates(self, ref: Reference, errors: list[str]) -> Iterator[Cand]:
        stages = []
        if ref.arxiv_id:
            stages.append(lambda: self._arxiv(ref.arxiv_id))
        stages += [lambda: self._s2(ref), lambda: self._openalex(ref)]
        arxiv_seen = bool(ref.arxiv_id)
        for stage in stages:
            try:
                c = stage()
            except FetchError as e:
                errors.append(str(e))
                continue
            if c:
                arxiv_seen |= any("arxiv.org/" in u for u in c.pdfs)
                yield c
        if not arxiv_seen and ref.title:  # lazy: only reached when nothing earlier gave full text
            try:
                c = self._arxiv_title(ref)
            except FetchError as e:
                errors.append(str(e))
                return
            if c:
                yield c

    # ---- one reference ----

    def fetch_reference(self, survey_id: str, key: str, ref: Optional[Reference]) -> SourceRecord:
        def rec(level: str, **kw) -> SourceRecord:
            return SourceRecord(cite_key=key, survey_id=survey_id, access_level=level,
                                retrieved_at=datetime.now(timezone.utc).isoformat(), **kw)

        if ref is None:
            return rec("none", error="missing_bib_entry")
        if not (ref.title or ref.arxiv_id or ref.doi):
            return rec("none", error="no_identifier")
        errors: list[str] = []
        worst: Optional[tuple[float, str]] = None  # best-scoring rejected candidate
        fallback = None  # first accepted candidate with an abstract: (cand, meta, why)
        no_text = None  # first accepted candidate with nothing: (cand, meta, why)
        tried: set[str] = set()
        for c in self._candidates(ref, errors):
            score = fuzz.token_sort_ratio(norm_title(ref.title), norm_title(c.title)) if ref.title else None
            if score is not None and score < self.min_match:
                worst = max(worst or (-1.0, ""), (float(score), c.title or ""))
                continue
            meta = dict(matched_title=c.title, match_score=score)
            why = None
            for u in (*c.pdfs, *([c.xml] if c.xml else [])):
                if u in tried:
                    continue
                tried.add(u)
                try:
                    sha = self._xml_sha(u) if u == c.xml else self._pdf_sha(u)
                except FetchError as e:
                    why = why or f"full_text_failed:{e}"
                    continue
                name = ("europe_pmc" if u == c.xml else c.name if c.name.startswith("arxiv")
                        else "arxiv" if "arxiv.org/" in u else c.name)
                return rec("full_text", source_name=name, source_url=u, text_sha256=sha,
                           text_path=f"texts/{sha}.txt", **meta)
            if c.abstract and fallback is None:
                fallback = (c, meta, why)
            elif not c.abstract and no_text is None:
                no_text = (c, meta, why)
        if fallback:
            c, meta, why = fallback
            sha = self._store(c.abstract)
            return rec("abstract", source_name=c.name, source_url=c.url, text_sha256=sha,
                       text_path=f"texts/{sha}.txt", error=why, **meta)
        extra = sorted(set(errors))
        if no_text:
            c, meta, why = no_text
            return rec("none", source_name=c.name, source_url=c.url,
                       error="; ".join([why or "no_text_available"] + extra), **meta)
        if worst:
            return rec("none", matched_title=worst[1], match_score=worst[0], error="; ".join(["low_title_match"] + extra))
        return rec("none", error="; ".join(extra) or "not_found")


# ---- batch run ----

def run(units_path: str | Path, out: str | Path, fetcher: Fetcher, max_refs: Optional[int] = None) -> list[SourceRecord]:
    """Fetch every distinct (survey_id, cite_key) not already in `out`; append records as they finish."""
    refs: dict[tuple[str, str], Optional[Reference]] = {}
    for u in read_jsonl(units_path, Unit):
        k = (u.survey_id, u.cite_key)
        refs[k] = refs.get(k) or u.reference
    keys = list(refs)[:max_refs]
    out = Path(out)
    latest = latest_records(out) if out.exists() else {}
    done = {k: r for k, r in latest.items() if not _is_transient(r)}  # transient failures are retried
    result = [done[k] for k in keys if k in done]
    out.parent.mkdir(parents=True, exist_ok=True)
    # a torn final line must not swallow the next record
    needs_nl = out.exists() and out.read_bytes()[-1:] not in (b"", b"\n")
    with open(out, "a", encoding="utf-8", newline="\n") as f:
        if needs_nl:
            f.write("\n")
        for sid, key in (k for k in keys if k not in done):
            try:
                r = fetcher.fetch_reference(sid, key, refs[(sid, key)])
            except Exception as e:  # one bad reference must not stop the run
                r = SourceRecord(cite_key=key, survey_id=sid, access_level="none", error=f"internal:{type(e).__name__}")
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
            f.flush()
            result.append(r)
    return result


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m citebench.fetch")
    ap.add_argument("units")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=".cache/citebench")
    ap.add_argument("--min-match", type=float, default=90)
    ap.add_argument("--max-refs", type=int)
    a = ap.parse_args(argv)
    f = Fetcher(a.cache, min_match=a.min_match)
    recs = run(a.units, a.out, f, a.max_refs)
    levels = Counter(r.access_level for r in recs)
    print(f"references={len(recs)} full_text={levels['full_text']} abstract={levels['abstract']} none={levels['none']}")
    for err, n in Counter(r.error for r in recs if r.error).most_common():
        print(f"  error {err}: {n}")


if __name__ == "__main__":
    main()
