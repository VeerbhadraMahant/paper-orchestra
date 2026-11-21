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
CITE_CMD_RE = re.compile(
    r"\\(?P<cmd>[Cc]ite(?:p|t|alp|alt|author|year|yearpar|num|s|text)?|[Pp]arencite|[Tt]extcite|[Aa]utocite"
    r"|[Ff]ootcite|nocite)(?![A-Za-z])\*?"
)
CITE_TOKEN_RE = re.compile(r"\\[Cc]ite[a-zA-Z]*")
BEGIN_ANY_RE = re.compile(r"\\begin\s*\{")
ITEM_RE = re.compile(r"\\item(?![A-Za-z])")
LIST_ENV_RE = re.compile(r"\\(?:begin|end)\s*\{(?:itemize|enumerate|description)\}")
PARAGRAPH_RE = re.compile(r"\\(?:sub)?paragraph\*?\s*(?:\[[^\]]*\]\s*)?\{")
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
    r"(?<![A-Za-z])(?:e\.g|i\.e|et[\s~]+al|vs|figs?|eqs?|sec|tab|cf|resp|approx|no|dr)\.$", re.I
)
ETC_RE = re.compile(r"(?<![A-Za-z])etc\.$", re.I)
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


def _skip_ws(s: str, j: int) -> int:
    while j < len(s) and s[j].isspace():
        j += 1
    return j


def _skip_opts(s: str, j: int, n: int = 2) -> int:
    """Skip up to n optional [..] groups; braces inside are balanced, so a ']' within {..} does not close one."""
    for _ in range(n):
        k = _skip_ws(s, j)
        if s[k : k + 1] != "[":
            break
        d, q = 0, k + 1
        while q < len(s):
            c = s[q]
            if c == "\\":
                q += 2
                continue
            if c == "{":
                d += 1
            elif c == "}":
                d -= 1
            elif c == "]" and d <= 0:
                break
            q += 1
        else:
            break
        j = q + 1
    return j


def find_cites(s: str) -> list[tuple[int, int, str, list[str]]]:
    """(start, end, cmd, keys) per parsable citation command. \\citetext carries no key and is ignored.
    \\cites takes consecutive {keys} groups (biblatex multicite); every other command takes one."""
    out, pos = [], 0
    while m := CITE_CMD_RE.search(s, pos):
        pos = m.end()
        cmd = m.group("cmd")
        if cmd.lower() == "citetext":
            continue
        j, end, groups = _skip_opts(s, m.end()), m.end(), []
        while True:
            k = _skip_ws(s, j)
            e = match_brace(s, k) if s[k : k + 1] == "{" else -1
            if e < 0:
                break
            groups.append(s[k + 1 : e - 1])
            end = e
            if cmd.lower() != "cites":
                break
            j = _skip_opts(s, e)
        if not groups or any("{" in g or "}" in g for g in groups):
            continue
        keys = [x.strip() for g in groups for x in g.split(",") if x.strip()]
        out.append((m.start(), end, cmd, keys))
        pos = end
    return out


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
                j = i + 1
                while j < b and work[j] in ")]'\"":  # closing punctuation stays with the sentence
                    j += 1
                m = WS_RE.match(work, j, b)
                nxt = work[m.end()] if m is not None and m.end() < b else ""
                ok = j >= b or (m is not None and (m.end() >= b or nxt.isupper() or nxt == "\\"))
                if ok and c == "." and ETC_RE.search(work, max(a, i - 4), i + 1):
                    ok = j >= b or nxt.isupper()  # "etc. Then" splits; "etc. \cite{x}" does not
                elif ok and c == "." and ABBR_RE.search(work, max(a, i - 14), i + 1):
                    ok = False
                if ok:
                    yield start, j
                    start = i = j
                    continue
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


BIB_KEY_RE = re.compile(r"(?m)^[ \t]*@\w+\s*[{(]\s*([^,\s]+)\s*,")


def _bib_raw_entries(text: str) -> dict[str, str]:
    bounds = [m.start() for m in re.finditer(r"(?m)^[ \t]*@\w+\s*[{(]", text)] + [len(text)]
    out = {}
    for m in BIB_KEY_RE.finditer(text):
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
    out: dict[str, Reference] = {}
    for e in db.entries:  # first entry wins, as in _bib_raw_entries, so raw and fields come from one entry
        out.setdefault(e["ID"], _bib_reference(e, raws.get(e["ID"])))
    return out


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
    # silent-loss counters
    unresolved_includes: int = 0  # missing, or resolving outside the source root (\input, \include, \subfile, files)
    cites_in_skipped_regions: int = 0  # citation commands inside skipped envs, captions, section/paragraph titles
    unterminated_envs: int = 0  # \begin{X} of a skipped env with no \end{X}
    unmatched_cite_tokens: int = 0  # \cite* tokens the parser could not read
    unmatched_examples: list[str] = field(default_factory=list)
    duplicate_bib_keys: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"files read: {self.files_read}",
            f"sentences with citations: {self.sentences_with_citations}",
            f"units: {self.units}",
            f"distinct keys: {self.distinct_keys}",
            f"keys missing from bibliography: {len(self.missing_keys)}",
            f"unresolved includes: {self.unresolved_includes}",
            f"cites in skipped regions: {self.cites_in_skipped_regions}",
            f"unterminated envs: {self.unterminated_envs}",
            f"unmatched cite tokens: {self.unmatched_cite_tokens}",
            f"duplicate bib keys: {len(self.duplicate_bib_keys)}",
        ]
        lines += [f"unmatched cite example: {e}" for e in self.unmatched_examples]
        lines += [f"bibliography error: {e}" for e in self.bib_errors]
        return "\n".join(lines)


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s < out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


class _Extractor:
    def __init__(self, root: Path, survey_id: str, refs: dict[str, Reference]):
        self.root, self.survey_id, self.refs = root, survey_id, refs  # root must already be resolved
        self.units: list[Unit] = []
        self.stats = Stats()
        self.visited: set[Path] = set()
        self.section: str | None = None

    def resolve(self, name: str, parent: Path) -> Path | None:
        """Resolved path of an included file, or None if missing or outside the root."""
        name = name.strip()
        for base in (self.root, parent.parent):
            for cand in (base / name, base / (name + ".tex")):
                try:
                    r = cand.resolve()
                    if r.is_file() and r.is_relative_to(self.root):
                        return r
                except (OSError, ValueError):
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
            depth, end = 1, None
            for mm in pat.finditer(work, m.end(), b):
                depth += 1 if mm.group(1) == "begin" else -1
                if depth == 0:
                    end = mm.end()
                    break
            if end is None:
                # Unterminated: skip only to the end of the paragraph, or the next \begin or section, whichever
                # comes first, so one missing \end does not swallow the rest of the file.
                self.stats.unterminated_envs += 1
                nxt = [x.start() for x in (BEGIN_ANY_RE.search(work, m.end(), b), SECTION_RE.search(work, m.end(), b),
                                           PB_RE.search(pb, m.end(), b)) if x]
                end = min(nxt + [b])
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
        titles = []  # title spans whose citations are dropped
        for m in SECTION_RE.finditer(work, a, b):
            end = match_brace(work, m.end() - 1)
            if end > 0 and not skipped(m.start()):
                secs.append((m.start(), plain(work[m.end() : end - 1])))
                blanks.append((m.start(), end))
                titles.append((m.start(), end))
        for m in PARAGRAPH_RE.finditer(work, a, b):  # run-in headings: sentence boundary, not a section
            end = match_brace(work, m.end() - 1)
            if end > 0 and not skipped(m.start()):
                blanks.append((m.start(), end))
                titles.append((m.start(), end))
        for rx in (ITEM_RE, LIST_ENV_RE):  # each list item is its own sentence even without a period
            blanks += [m.span() for m in rx.finditer(work, a, b) if not skipped(m.start())]
        for s, e in _merge(skips + titles):
            self.stats.cites_in_skipped_regions += sum(1 for c in find_cites(work[s:e]) if c[2] != "nocite")
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
            if name is not None:
                child = self.resolve(name, path)
                if child is None:
                    self.stats.unresolved_includes += 1
                elif child not in self.visited:
                    self.file(child)
            pos = iend

    def sentence(self, rel: str, text: str, work: str, s: int, e: int) -> None:
        sw = work[s:e]
        cites = find_cites(sw)
        parsed = {c[0] for c in cites}
        for m in CITE_TOKEN_RE.finditer(sw):
            if m.start() not in parsed and m.group().lower() != "\\citetext":
                self.stats.unmatched_cite_tokens += 1
                if len(self.stats.unmatched_examples) < 5:
                    self.stats.unmatched_examples.append(sw[m.start() : m.start() + 40].replace("\n", " "))
        keys: list[str] = []
        for _, _, cmd, ks in cites:
            for k in ks if cmd != "nocite" else ():
                if k not in keys:
                    keys.append(k)
        if not keys:
            return
        self.stats.sentences_with_citations += 1
        parts, last = [], 0
        for cs, ce, cmd, _ in cites:
            parts += [sw[last:cs], "" if cmd == "nocite" else "[CITE]"]
            last = ce
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


def _files_in_root(root: Path, pattern: str, stats: Stats) -> list[Path]:
    """Resolved paths of files matching pattern under root; those resolving outside it (symlinks) are counted."""
    out = []
    for p in sorted(root.rglob(pattern)):
        if p.is_dir():
            continue
        try:
            r = p.resolve()
        except OSError:
            r = None
        if r is not None and r.is_file() and r.is_relative_to(root):
            out.append(r)
        else:
            stats.unresolved_includes += 1
    return sorted(set(out))


def _find_main(root: Path, tex_files: list[Path]) -> Path:
    cands, begin_only, included = [], [], set()
    for p in tex_files:
        work, _ = mask_comments(read_text(p))
        if BEGIN_DOC_RE.search(work):
            (cands if re.search(r"\\documentclass", work) else begin_only).append(p)
        for m in INPUT_RE.finditer(work):
            for cand in (root / m.group(1).strip(), root / (m.group(1).strip() + ".tex")):
                try:
                    if cand.resolve().is_file():
                        included.add(cand.resolve())
                except (OSError, ValueError):
                    pass
    # \documentclass may sit in an \input'ed header file (e.g. ACM templates): fall back to \begin{document}
    cands = cands or begin_only
    if not cands:
        raise FileNotFoundError(f"no main .tex file (\\documentclass + \\begin{{document}}) under {root}")
    free = [c for c in cands if c not in included] or cands
    return min(free, key=lambda p: (p.name != "main.tex", p.relative_to(root).as_posix()))


def load_bibliography(root: Path, stats: Stats) -> dict[str, Reference]:
    """All .bib files merged (first wins); .bbl entries only fill keys the .bib files lack."""
    refs: dict[str, Reference] = {}
    dups: set[str] = set(stats.duplicate_bib_keys)
    root = root.resolve()
    for pattern, parse in (("*.bib", parse_bib), ("*.bbl", parse_bbl)):
        for p in _files_in_root(root, pattern, stats):
            try:
                text = read_text(p)
                if pattern == "*.bib":
                    keys = BIB_KEY_RE.findall(text)
                    dups |= {k for k in keys if keys.count(k) > 1}
                for k, r in parse(text).items():
                    if k in refs and pattern == "*.bib":
                        dups.add(k)
                    refs.setdefault(k, r)
            except Exception as ex:
                stats.bib_errors.append(f"{p.relative_to(root).as_posix()}: {type(ex).__name__}: {ex}")
    stats.duplicate_bib_keys = sorted(dups)
    return refs


def extract(source_dir: str | Path, survey_id: str) -> tuple[list[Unit], Stats]:
    root = Path(source_dir).resolve()
    stats = Stats()
    refs = load_bibliography(root, stats)
    ex = _Extractor(root, survey_id, refs)
    ex.stats = stats
    ex.file(_find_main(root, _files_in_root(root, "*.tex", stats)))
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
