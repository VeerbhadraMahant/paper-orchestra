"""Shared data contract for CiteBench. Every stage reads and writes these records as JSONL.

One Unit = one (citing sentence, one cited reference) pair. Multi-cite sentences yield one Unit per key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional, Type, TypeVar

AccessLevel = Literal["full_text", "abstract", "none"]


@dataclass
class Reference:
    """Bibliographic record for one cited work, taken from the survey's .bib (never invented)."""

    key: str
    title: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Unit:
    unit_id: str  # make_unit_id(survey_id, source_file, char_start, cite_key)
    survey_id: str  # arXiv id of the survey, e.g. "2402.06196"
    source_file: str  # path of the .tex file relative to the survey source root
    char_start: int  # offset of the sentence in that file (original LaTeX)
    char_end: int
    section: Optional[str]  # nearest enclosing \section/\subsection title, plain text
    sentence_latex: str  # the sentence exactly as in the source
    sentence_text: str  # plain text; each citation command replaced by "[CITE]"
    cite_key: str  # the reference this unit is about
    cocited_keys: list[str] = field(default_factory=list)  # other keys cited in the same sentence
    reference: Optional[Reference] = None  # None if the key is missing from the .bib


@dataclass
class SourceRecord:
    """What the fetcher found for one cited reference. Text is cached on disk, not stored inline."""

    cite_key: str
    survey_id: str
    access_level: AccessLevel
    source_name: Optional[str] = None  # e.g. "arxiv", "semantic_scholar", "openalex"
    source_url: Optional[str] = None
    text_path: Optional[str] = None  # cached plain-text file, relative to the cache root
    text_sha256: Optional[str] = None
    retrieved_at: Optional[str] = None  # ISO 8601 UTC
    matched_title: Optional[str] = None  # title reported by the source, for match auditing
    match_score: Optional[float] = None  # title similarity 0..100 between .bib title and matched_title
    error: Optional[str] = None  # why access_level is "none", if known


def make_unit_id(survey_id: str, source_file: str, char_start: int, cite_key: str) -> str:
    raw = f"{survey_id}|{source_file}|{char_start}|{cite_key}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


T = TypeVar("T", Unit, SourceRecord, Reference)


def _from_dict(cls: Type[T], d: dict) -> T:
    known = {f.name for f in fields(cls)}
    d = {k: v for k, v in d.items() if k in known}
    if cls is Unit and d.get("reference") is not None:
        d["reference"] = Reference(**d["reference"])
    return cls(**d)


def write_jsonl(path: str | Path, records: Iterable) -> int:
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: str | Path, cls: Type[T]) -> Iterator[T]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield _from_dict(cls, json.loads(line))
