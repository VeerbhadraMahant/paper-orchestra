"""Deterministic passage retrieval for the judge harness (D32): chunking and a tiny TF-IDF."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import NamedTuple

STOPWORDS = frozenset(
    "a an and are as at be been but by can could did do does for from had has have he her his how i if in into is "
    "it its may might more most no not of on or our she should so such than that the their them then there these "
    "they this those to was we were what when where which while who whom why will with would you your also "
    "however thus et al".split()
)


class Passage(NamedTuple):
    index: int  # position in the chunk list of the document
    text: str
    score: float


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def _split_long(s: str, limit: int) -> list[str]:
    out = []
    while len(s) > limit:
        cut = s.rfind(" ", 0, limit)
        cut = cut if cut > 0 else limit
        out.append(s[:cut].strip())
        s = s[cut:].strip()
    return out + ([s] if s else [])


def _segments(text: str, limit: int) -> list[str]:
    segs = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        if len(para) <= limit:
            segs.append(para)
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            segs.extend(_split_long(sent, limit))
    return segs


def _tail(s: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    if len(s) <= overlap:
        return s
    t = s[-overlap:]
    if not s[-overlap - 1].isspace() and " " in t:  # do not start inside a word
        t = t.split(" ", 1)[1]
    return t


def chunk(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Pack paragraphs (then sentences) into chunks of at most `size` characters; each chunk
    after the first starts with the last ~`overlap` characters of the previous one."""
    segs = _segments(text, size - overlap - 1)
    chunks: list[str] = []
    cur = ""
    for s in segs:
        if cur and len(cur) + 1 + len(s) > size:
            chunks.append(cur)
            tail = _tail(cur, overlap)
            cur = f"{tail} {s}" if tail else s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        chunks.append(cur)
    return chunks


def _idf(docs: list[list[str]]) -> dict[str, float]:
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    return {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}  # smoothed


def _vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    v = {t: c * idf[t] for t, c in Counter(tokens).items() if t in idf}
    norm = math.sqrt(sum(x * x for x in v.values()))
    return {t: x / norm for t, x in v.items()} if norm else {}


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def _scores(query: str, docs: list[str]) -> list[float]:
    toks = [tokenize(d) for d in docs]
    idf = _idf(toks)
    q = _vec(tokenize(query), idf)
    return [_cos(q, _vec(t, idf)) for t in toks]


def top_passages(sentence: str, text: str, k: int = 5, skip_first: bool = False) -> list[Passage]:
    """Top-k chunks of `text` by TF-IDF cosine to `sentence` (score > 0 only), in document order.
    skip_first leaves chunk 0 out of the ranking (it is shown separately as front matter)."""
    chunks = chunk(text)
    scores = _scores(sentence, chunks)
    ranked = sorted(range(1 if skip_first else 0, len(chunks)), key=lambda i: (-scores[i], i))
    keep = sorted(i for i in ranked[:k] if scores[i] > 0)
    return [Passage(i, chunks[i], scores[i]) for i in keep]


def most_similar(query: str, candidates: dict[str, str]) -> list[tuple[str, float]]:
    """Candidate keys ranked by TF-IDF cosine to `query` (ties broken by key). idf is fit on the candidates."""
    keys = sorted(candidates)
    scores = _scores(query, [candidates[k] for k in keys])
    return sorted(zip(keys, scores), key=lambda p: (-p[1], p[0]))
