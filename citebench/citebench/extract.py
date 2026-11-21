"""Turn one unpacked arXiv survey source directory into Unit records (one per citing sentence per cited key).

Offsets (char_start/char_end) index the file text decoded from raw bytes (UTF-8, errors="replace", no newline
translation), so read_bytes().decode("utf-8", errors="replace")[char_start:char_end] == sentence_latex.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bibtexparser.bparser import BibTexParser
from pylatexenc.latex2text import LatexNodes2Text

from .units import Reference, Unit, make_unit_id, write_jsonl

# ---------------------------------------------------------------- patterns

COMMENT_RE = re.compile(r"(?<!\\)(?:\\\\)*(%[^\n]*)")
CITE_RE = re.compile(
    r"\\(?P<cmd>[Cc]ite(?:p|t|alp|alt|author|year)?|[Pp]arencite|[Tt]extcite|[Aa]utocite|[Ff]ootcite|nocite)"
    r"\*?\s*(?:\[[^\]]*\]\s*){0,2}\{(?P<keys>[^{}]*)\}"
)
ENV_RE = re.compile(
    r"\\begin\s*\{(figure|table|equation|align|algorithm|tabular|verbatim|lstlisting|thebibliography"
    r"|gather|multline|eqnarray)\*?\}"
)
CAPTION_RE = re.compile(r"\\caption(?:of\s*\{[^{}]*\})?\*?\s*(?:\[[^\]]*\]\s*)?\{")
BIBCMD_RE = re.compile(r"\\(?:bibliography|printbibliography|bibliographystyle)\b(?:\s*\[[^\]]*\])?\s*(?:\{[^{}]*\})?")
INPUT_RE = re.compile(r"\\(?:input|include|subfile|subfileinclude)\s*\{([^{}]*)\}")
SECTION_RE = re.compile(r"\\(?:sub){0,2}section\*?\s*(?:\[[^\]]*\]\s*)?\{")
BEGIN_DOC_RE = re.compile(r"\\begin\s*\{document\}")
END_DOC_RE = re.compile(r"\\end\s*\{document\}")
PB_RE = re.compile(r"\n(?:[ \t\r]*\n)+")
WS_RE = re.compile(r"\s+")
ABBR_RE = re.compile(
    r"(?<![A-Za-z])(?:e\.g|i\.e|et[\s~]+al|etc|vs|figs?|eqs?|sec|tab|cf|resp|approx|no|dr)\.$", re.I
)
_ID = r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Za-z]{2})?/\d{7})"
ARXIV_RES = [re.compile(p, re.I) for p in (r"arxiv\s*[:/ ]\s*" + _ID, r"arxiv\.org/(?:abs|pdf)/" + _ID, r"\babs/" + _ID)]
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s{}\\,]+")

_L2T = LatexNodes2Text()


def plain(s: str) -> str:
    """LaTeX to plain text with collapsed whitespace; regex strip if pylatexenc fails."""
    try:
        out = _L2T.latex_to_text(s)
    except Exception:
        out = re.sub(r"\\[a-zA-Z]+\*?|[{}$~\\]", " ", s)
    return " ".join(out.split())


def match_brace(t: str, i: int) -> int:
    """Index just past the brace group opening at t[i], or -1 if unbalanced."""
    d = 0
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    return -1


def read_text(p: Path) -> str:
    return p.read_bytes().decode("utf-8", errors="replace")


def mask_comments(text: str) -> tuple[str, str]:
    """(work, pb): comments blanked to spaces; pb keeps one '%' per comment so comment-only lines are not blank lines."""
    w, p = list(text), list(text)
    for m in COMMENT_RE.finditer(text):
        a, e = m.span(1)
        w[a:e] = " " * (e - a)
        p[a:e] = "%" + " " * (e - a - 1)
    return "".join(w), "".join(p)


# ---------------------------------------------------------------- sentence segmentation


def segments(work: str, pbs: dict[int, int], a: int, b: int):
    """Yield raw (start, end) sentence spans of work[a:b]; callers strip whitespace."""
    start = i = a
    depth, math = 0, None
    while i < b:
        if i in pbs:
            yield start, i
            i = start = pbs[i]
            depth, math = 0, None
            continue
        c = work[i]
        if c == "\\":
            n = work[i + 1 : i + 2]
            if math is None and n in ("(", "["):
                math = ")" if n == "(" else "]"
            elif n and n == math:
                math = None
            i += 2
            continue
        if c == "$":
            tok = "$$" if work[i + 1 : i + 2] == "$" else "$"
            math = None if math == tok else (tok if math is None else math)
            i += len(tok)
            continue
        if math is None:
            if c == "{":
                depth += 1
            elif c == "}":
                depth = max(0, depth - 1)
            elif c in ".?!" and depth == 0:
                m = WS_RE.match(work, i + 1, b)
                ok = (i + 1 >= b) or (m is not None and (m.end() >= b or work[m.end()].isupper() or work[m.end()] == "\\"))
                if ok and c == "." and ABBR_RE.search(work, max(a, i - 14), i + 1):
                    ok = False
                if ok:
                    yield start, i + 1
                    start = i + 1
        i += 1
    if start < b:
        yield start, b


# ---------------------------------------------------------------- bibliography


def _arxiv_id(*texts: str | None) -> str | None:
    for t in texts:
        for rx in ARXIV_RES:
            m = rx.search(t or "")
            if m:
                return m.group(1)
    return None


def _bib_raw_entries(text: str) -> dict[str, str]:
    bounds = [m.start() for m in re.finditer(r"(?m)^[ \t]*@\w+\s*[{(]", text)] + [len(text)]
    out = {}
    for m in re.finditer(r"(?m)^[ \t]*@\w+\s*[{(]\s*([^,\s]+)\s*,", text):
        nxt = next(b for b in bounds if b > m.start())
        out.setdefault(m.group(1), text[m.start() : nxt].strip())
    return out


def _bib_reference(e: dict, raw: str | None) -> Reference:
    def tf(k):
        return plain(e[k]) if e.get(k) else None

    ym = re.search(r"\d{4}", e.get("year") or e.get("date") or "")
    doi = (e.get("doi") or "").strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi) or None
    arxiv = None
    if (e.get("archiveprefix") or e.get("eprinttype") or "").lower() == "arxiv" and e.get("eprint"):
        arxiv = re.sub(r"^arxiv:\s*|v\d+$", "", e["eprint"].strip(), flags=re.I) or None
    arxiv = arxiv or _arxiv_id(
        e.get("url"), e.get("journal"), e.get("journaltitle"), e.get("note"), e.get("howpublished"),
        e.get("booktitle"), e.get("volume"),
    )
    return Reference(
        key=e["ID"],
        title=tf("title"),
        authors=[a for a in (plain(x) for x in re.split(r"\s+and\s+", e.get("author", ""))) if a],
        year=int(ym.group()) if ym else None,
        venue=tf("journal") or tf("booktitle") or tf("journaltitle"),
        doi=doi,
        arxiv_id=arxiv,
        url=(e.get("url") or "").strip() or None,
        raw=raw,
    )


def parse_bib(text: str) -> dict[str, Reference]:
    parser = BibTexParser(common_strings=True, ignore_nonstandard_types=False)
    raws = _bib_raw_entries(text)
    db = parser.parse(text)
    return {e["ID"]: _bib_reference(e, raws.get(e["ID"])) for e in db.entries}


def parse_bbl(text: str) -> dict[str, Reference]:
    text, _ = mask_comments(text)
    items = [m.start() for m in re.finditer(r"\\bibitem\b", text)]
    end_all = m.start() if (m := re.search(r"\\end\s*\{thebibliography\}", text)) else len(text)
    refs: dict[str, Reference] = {}
    for n, i in enumerate(items):
        stop = items[n + 1] if n + 1 < len(items) else end_all
        j = i + len("\\bibitem")
        while j < stop and text[j].isspace():
            j += 1
        label = None
        if text[j : j + 1] == "[":  # natbib label, may contain braces and brackets
            d, k = 0, j
            while k < stop and not (text[k] == "]" and d == 0 and k > j):
                d += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            label, j = text[j + 1 : k], k + 1
            while j < stop and text[j].isspace():
                j += 1
        if text[j : j + 1] != "{":
            continue
        close = match_brace(text, j)
        if close < 0:
            continue
        key, body = text[j + 1 : close - 1].strip(), text[close:stop]
        pieces = re.split(r"\\newblock", body)
        title = plain(pieces[1]).rstrip(".").strip() if len(pieces) >= 2 and pieces[0].strip() else None
        ym = re.search(r"(?<!\d)((?:19|20)\d{2})[a-z]?(?!\d)", label or "")
        dm = DOI_RE.search(body)
        um = re.search(r"\\(?:url|href)\s*\{([^{}]*)\}", body)
        raw = text[i:stop].strip()
        refs.setdefault(key, Reference(
            key=key,
            title=title or None,
            year=int(ym.group(1)) if ym else None,
            doi=dm.group().rstrip(".)") if dm else None,
            arxiv_id=_arxiv_id(body),
            url=um.group(1).strip() if um else None,
            raw=raw,
        ))
    return refs


# ---------------------------------------------------------------- extraction


@dataclass
class Stats:
    files_read: int = 0
    sentences_with_citations: int = 0
    units: int = 0
    distinct_keys: int = 0
    missing_keys: list[str] = field(default_factory=list)
    bib_errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"files read: {self.files_read}",
            f"sentences with citations: {self.sentences_with_citations}",
            f"units: {self.units}",
            f"distinct keys: {self.distinct_keys}",
            f"keys missing from bibliography: {len(self.missing_keys)}",
        ]
        lines += [f"bibliography error: {e}" for e in self.bib_errors]
        return "\n".join(lines)


class _Extractor:
    def __init__(self, root: Path, survey_id: str, refs: dict[str, Reference]):
        self.root, self.survey_id, self.refs = root, survey_id, refs
        self.units: list[Unit] = []
        self.stats = Stats()
        self.visited: set[Path] = set()
        self.section: str | None = None

    def resolve(self, name: str, parent: Path) -> Path | None:
        name = name.strip()
        for base in (self.root, parent.parent):
            for cand in (base / name, base / (name + ".tex")):
                try:
                    if cand.is_file() and cand.resolve().is_relative_to(self.root.resolve()):
                        return cand
                except OSError:
                    pass
        return None

    def file(self, path: Path) -> None:
        self.visited.add(path)
        rel = path.relative_to(self.root).as_posix()
        text = read_text(path)
        self.stats.files_read += 1
        work, pb = mask_comments(text)
        bm = BEGIN_DOC_RE.search(work)
        a = bm.end() if bm else 0
        em = END_DOC_RE.search(work, a)
        b = em.start() if em else len(work)

        skips = []
        pos = a
        while m := ENV_RE.search(work, pos, b):
            name = m.group(0)[m.group(0).index("{") + 1 : -1]
            pat = re.compile(r"\\(begin|end)\s*\{%s\}" % re.escape(name))
            depth, end = 1, b
            for mm in pat.finditer(work, m.end(), b):
                depth += 1 if mm.group(1) == "begin" else -1
                if depth == 0:
                    end = mm.end()
                    break
            skips.append((m.start(), end))
            pos = end
        for m in CAPTION_RE.finditer(work, a, b):
            end = match_brace(work, m.end() - 1)
            if end > 0:
                skips.append((m.start(), end))
        skips += [m.span() for m in BIBCMD_RE.finditer(work, a, b)]

        def skipped(p):
            return any(s <= p < e for s, e in skips)

        inputs = [(m.start(), m.end(), m.group(1)) for m in INPUT_RE.finditer(work, a, b) if not skipped(m.start())]
        secs, blanks = [], list(skips) + [(s, e) for s, e, _ in inputs]
        for m in SECTION_RE.finditer(work, a, b):
            end = match_brace(work, m.end() - 1)
            if end > 0 and not skipped(m.start()):
                secs.append((m.start(), plain(work[m.end() : end - 1])))
                blanks.append((m.start(), end))
        w, p = list(work), list(pb)
        for s, e in blanks:  # blank with a forced paragraph break so sentences cannot span the gap
            for arr in (w, p):
                arr[s:e] = " " * (e - s)
                arr[s : s + 2] = "\n\n"
        work, pbtxt = "".join(w), "".join(p)
        pbs = {m.start(): m.end() for m in PB_RE.finditer(pbtxt, a, b)}

        si, pos = 0, a
        for ipos, iend, name in sorted(inputs) + [(b, b, None)]:
            for s, e in segments(work, pbs, pos, ipos):
                while s < e and work[s].isspace():
                    s += 1
                while e > s and work[e - 1].isspace():
                    e -= 1
                if s == e:
                    continue
                while si < len(secs) and secs[si][0] <= s:
                    self.section = secs[si][1]
                    si += 1
                self.sentence(rel, text, work, s, e)
            while si < len(secs) and secs[si][0] < ipos:
                self.section = secs[si][1]
                si += 1
            child = self.resolve(name, path) if name else None
            if child is not None and child not in self.visited:
                self.file(child)
            pos = iend

    def sentence(self, rel: str, text: str, work: str, s: int, e: int) -> None:
        sw = work[s:e]
        cites = list(CITE_RE.finditer(sw))
        keys: list[str] = []
        for m in cites:
            for k in (x.strip() for x in m.group("keys").split(",")) if m.group("cmd") != "nocite" else ():
                if k and k not in keys:
                    keys.append(k)
        if not keys:
            return
        self.stats.sentences_with_citations += 1
        parts, last = [], 0
        for m in cites:
            parts += [sw[last : m.start()], "" if m.group("cmd") == "nocite" else "[CITE]"]
            last = m.end()
        parts.append(sw[last:])
        sentence_text = plain("".join(parts))
        for k in keys:
            self.units.append(Unit(
                unit_id=make_unit_id(self.survey_id, rel, s, k),
                survey_id=self.survey_id,
                source_file=rel,
                char_start=s,
                char_end=e,
                section=self.section,
                sentence_latex=text[s:e],
                sentence_text=sentence_text,
                cite_key=k,
                cocited_keys=[o for o in keys if o != k],
                reference=self.refs.get(k),
            ))


def _find_main(root: Path, tex_files: list[Path]) -> Path:
    cands, included = [], set()
    for p in tex_files:
        work, _ = mask_comments(read_text(p))
        if BEGIN_DOC_RE.search(work) and re.search(r"\\documentclass", work):
            cands.append(p)
        for m in INPUT_RE.finditer(work):
            for cand in (root / m.group(1).strip(), root / (m.group(1).strip() + ".tex")):
                if cand.is_file():
                    included.add(cand)
    if not cands:
        raise FileNotFoundError(f"no main .tex file (\\documentclass + \\begin{{document}}) under {root}")
    free = [c for c in cands if c not in included] or cands
    return min(free, key=lambda p: (p.name != "main.tex", p.relative_to(root).as_posix()))


def load_bibliography(root: Path, stats: Stats) -> dict[str, Reference]:
    """All .bib files merged (first wins); .bbl entries only fill keys the .bib files lack."""
    refs: dict[str, Reference] = {}
    for pattern, parse in (("*.bib", parse_bib), ("*.bbl", parse_bbl)):
        for p in sorted(root.rglob(pattern)):
            try:
                for k, r in parse(read_text(p)).items():
                    refs.setdefault(k, r)
            except Exception as ex:
                stats.bib_errors.append(f"{p.relative_to(root).as_posix()}: {type(ex).__name__}: {ex}")
    return refs


def extract(source_dir: str | Path, survey_id: str) -> tuple[list[Unit], Stats]:
    root = Path(source_dir)
    stats = Stats()
    refs = load_bibliography(root, stats)
    ex = _Extractor(root, survey_id, refs)
    ex.stats = stats
    ex.file(_find_main(root, sorted(root.rglob("*.tex"))))
    keys = {u.cite_key for u in ex.units}
    stats.units = len(ex.units)
    stats.distinct_keys = len(keys)
    stats.missing_keys = sorted(k for k in keys if k not in refs)
    return ex.units, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m citebench.extract", description=__doc__.splitlines()[0])
    ap.add_argument("source_dir")
    ap.add_argument("--survey-id", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        units, stats = extract(args.source_dir, args.survey_id)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    write_jsonl(args.out, units)
    print(stats.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
