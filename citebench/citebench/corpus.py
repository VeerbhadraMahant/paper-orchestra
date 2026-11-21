"""Corpus selection (D1 to D7) and safe arXiv source download/extraction for CiteBench."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import random
import sys
import tarfile
import time
from dataclasses import asdict
from pathlib import Path

SEED = 20261122
UA = "citebench/0.0.1 (research benchmark)"
MAX_BYTES = 200 * 1024 * 1024
YEAR_MIN, YEAR_MAX = 2022, 2026  # D1; year field is a proxy for the first-posted date (upper bound 2026-06-30)
MIN_REFS = 100  # D2


def eligible(candidates: list[dict], exclude_ids: set[str] | frozenset[str] = frozenset()):
    """Apply D1, D2 and explicit exclusions. Returns (eligible, [(arxiv_id, reason)]).

    D1 uses the candidate's `year` as a proxy for the first-posted date: 2022..2026 pass, so a 2026 survey
    posted after 2026-06-30 would slip through until the date is verified. ref_count None is ineligible.
    """
    ok, out = [], []
    for c in candidates:
        if c["arxiv_id"] in exclude_ids:
            out.append((c["arxiv_id"], "excluded"))
        elif not (YEAR_MIN <= int(c["year"]) <= YEAR_MAX):
            out.append((c["arxiv_id"], "year_out_of_range"))
        elif c.get("ref_count") is None:
            out.append((c["arxiv_id"], "ref_count_unverified"))
        elif c["ref_count"] < MIN_REFS:
            out.append((c["arxiv_id"], "ref_count_below_100"))
        else:
            ok.append(c)
    return ok, out


def draw(eligible_list: list[dict], n: int = 10, per_subfield_cap: int = 2, seed: int = SEED):
    """D6/D7: each subfield is shuffled with its own generator (seed|subfield) from the arxiv_id-sorted list, so a
    subfield's order does not depend on which other subfields exist. Subfields are visited round-robin in a seeded
    shuffle of the sorted subfield names (not alphabetical). Returns (selection, log)."""
    by_sf: dict[str, list[dict]] = {}
    for c in sorted(eligible_list, key=lambda c: c["arxiv_id"]):
        by_sf.setdefault(c["subfield"], []).append(c)
    for sf in by_sf:
        random.Random(f"{seed}|{sf}").shuffle(by_sf[sf])
    sf_order = sorted(by_sf)
    random.Random(f"{seed}|subfields").shuffle(sf_order)
    taken = {sf: 0 for sf in by_sf}
    sel, log = [], []
    while len(sel) < n:
        progressed = False
        for sf in sf_order:
            if len(sel) >= n:
                break
            if taken[sf] >= per_subfield_cap or not by_sf[sf]:
                continue
            c = by_sf[sf].pop(0)
            taken[sf] += 1
            sel.append(c)
            log.append(f"pick {c['arxiv_id']} subfield={sf} order={len(sel)}")
            progressed = True
        if not progressed:
            break
    if len(sel) < n:
        log.append(f"only {len(sel)} of {n} selected: pool or subfield caps exhausted")
    return sel, log


# ---- safe source extraction ----

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_UNPACKED = 500 * 1024 * 1024  # decompressed bytes, and total extracted bytes
MAX_MEMBERS = 5000


def _safe_target(dest: Path, name: str) -> Path:
    p = Path(name)
    if p.is_absolute() or name.startswith("/") or ".." in p.parts or ":" in name or "\\" in name:
        raise ValueError(f"unsafe tar member path: {name!r}")
    if any(part.split(".")[0].strip().upper() in _RESERVED for part in name.split("/")):
        raise ValueError(f"reserved device name in tar member path: {name!r}")
    t, d = (dest / p).resolve(), dest.resolve()
    if d not in t.parents and t != d:
        raise ValueError(f"tar member escapes destination: {name!r}")
    return t


def extract_eprint(data: bytes, dest: str | Path, max_bytes: int = MAX_UNPACKED, max_members: int = MAX_MEMBERS) -> str:
    """Extract an arXiv e-print into dest. Returns "tar", "single_tex" or "no_tex_source".

    Raises ValueError on unsafe tars (absolute or `..` paths, symlinks, hardlinks, devices); every member is
    validated before anything is written. Nothing is executed. Raises ValueError when the decompressed data or
    the sum of member sizes exceeds `max_bytes`, or there are more than `max_members` members (decompression bombs).
    """
    dest = Path(dest)
    if data[:4] == b"%PDF":
        return "no_tex_source"
    gz = data[:2] == b"\x1f\x8b"
    raw = data
    if gz:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                raw = g.read(max_bytes + 1)
        except (OSError, EOFError):
            return "no_tex_source"
        if len(raw) > max_bytes:
            raise ValueError(f"decompressed e-print exceeds {max_bytes} bytes")
        if raw[:4] == b"%PDF":
            return "no_tex_source"
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError:
        tf = None
    if tf is None:
        if not gz:
            return "no_tex_source"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.tex").write_bytes(raw)
        return "single_tex"
    with tf:
        members = tf.getmembers()
        if len(members) > max_members:
            raise ValueError(f"tar has more than {max_members} members")
        if sum(m.size for m in members if m.isfile()) > max_bytes or any(m.size > max_bytes for m in members):
            raise ValueError(f"tar members exceed {max_bytes} bytes")
        for m in members:
            if not (m.isfile() or m.isdir()):
                raise ValueError(f"unsafe tar member type: {m.name!r}")
            _safe_target(dest, m.name)
        dest.mkdir(parents=True, exist_ok=True)
        for m in members:
            t = _safe_target(dest, m.name)
            if m.isdir():
                t.mkdir(parents=True, exist_ok=True)
            else:
                t.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(m)
                t.write_bytes(f.read() if f else b"")
    return "tar" if any(dest.rglob("*.tex")) else "no_tex_source"


def _download(arxiv_id: str, session) -> bytes:
    r = session.get(f"https://arxiv.org/e-print/{arxiv_id}", headers={"User-Agent": UA}, timeout=60, stream=True)
    r.raise_for_status()
    buf = bytearray()
    for chunk in r.iter_content(65536):
        buf += chunk
        if len(buf) > MAX_BYTES:
            raise ValueError("e-print exceeds 200 MB cap")
    return bytes(buf)


def fetch_sources(selected: list[dict], dest: str | Path, session=None, sleep=time.sleep) -> dict[str, dict]:
    """Download and extract each survey; resumable via DEST/<id>.status.json. Returns {id: status}."""
    import requests

    session = session or requests.Session()
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out, first = {}, True
    for c in selected:
        i = c["arxiv_id"]
        sf = dest / f"{i}.status.json"
        if sf.exists():
            out[i] = json.loads(sf.read_text(encoding="utf-8"))
            continue
        if not first:
            sleep(3)
        first = False
        try:
            status = {"arxiv_id": i, "status": extract_eprint(_download(i, session), dest / i)}
        except Exception as e:  # not cached, so a rerun retries it
            print(f"{i}: {type(e).__name__}: {e}", file=sys.stderr)
            out[i] = {"arxiv_id": i, "status": "error", "error": f"{type(e).__name__}: {e}"}
            continue
        status["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        sf.write_text(json.dumps(status), encoding="utf-8")
        out[i] = status
    return out


def extract_all(selected: list[dict], dest: str | Path, work: str | Path) -> dict[str, str]:
    from .extract import extract
    from .units import write_jsonl

    dest, units_dir = Path(dest), Path(work) / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for c in selected:
        i = c["arxiv_id"]
        sf, out = dest / f"{i}.status.json", units_dir / f"{i}.jsonl"
        if out.exists():
            res[i] = "skipped_done"
        elif not sf.exists() or json.loads(sf.read_text(encoding="utf-8")).get("status") not in ("tar", "single_tex"):
            res[i] = "no_tex_source"
        else:
            units, stats = extract(dest / i, i)
            write_jsonl(out, units)
            (units_dir / f"{i}.stats.json").write_text(json.dumps(asdict(stats), indent=1), encoding="utf-8")
            res[i] = f"{stats.units} units"
        print(f"{i}: {res[i]}")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m citebench.corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--candidates", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--n", type=int, default=10)
    d.add_argument("--seed", type=int, default=SEED)
    for name in ("fetch-sources", "extract-all"):
        p = sub.add_parser(name)
        p.add_argument("--selected", required=True)
        p.add_argument("--dest", required=True)
        if name == "extract-all":
            p.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "draw":
        cands = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
        ok, excl = eligible(cands)
        sel, log = draw(ok, n=a.n, seed=a.seed)
        Path(a.out).write_text(json.dumps({
            "selected": sel, "exclusions": excl, "log": log, "seed": a.seed,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, indent=1,
            ensure_ascii=False), encoding="utf-8")
        print(f"selected {len(sel)}; excluded {len(excl)}")
        return 0
    sel = json.loads(Path(a.selected).read_text(encoding="utf-8"))["selected"]
    if a.cmd == "fetch-sources":
        print({k: v["status"] for k, v in fetch_sources(sel, a.dest).items()})
    else:
        extract_all(sel, a.dest, a.work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
