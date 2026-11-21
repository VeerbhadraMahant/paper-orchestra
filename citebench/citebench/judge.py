"""CiteBench judge harness: (unit, source) pairs -> judge prompts under experimental conditions -> validated predictions.

Judges never see whole papers (D32). Evidence = the first passage of the source (treated as abstract or front
matter) plus the top k=5 passages by TF-IDF cosine to the citing sentence; for access level "abstract" the abstract
text only. All judges see identical evidence for a given call.

Usage:
  python -m citebench.judge build --units U.jsonl --sources S.jsonl --cache CACHE --conditions correct,no_source --out calls.jsonl
  python -m citebench.judge run --calls calls.jsonl --units U.jsonl --sources S.jsonl --cache CACHE \
      --backend claude_cli|ollama|file --model M [--dir D] --out preds.jsonl [--repeat N]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

from .extract import find_cites
from .fetch import clean_doi, latest_records, norm_title
from .retrieval import chunk, most_similar, top_passages
from .units import Reference, SourceRecord, Unit, read_jsonl

PROMPT_VERSION = "judge_v1"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / f"{PROMPT_VERSION}.md"
SHUFFLE_SEED = 20261122  # D19
OLLAMA_SEED = 20261122
TOP_K = 5
NUM_CTX = 16384  # Ollama context window, set explicitly so truncation is detectable
CLI_SYSTEM_PROMPT = "You are a careful assistant. Answer only with the JSON object requested."
MODEL_RE = re.compile(r"^[A-Za-z0-9._:" + chr(92) + "-" + chr(92) + "[" + chr(92) + "]]+$")
CONDITIONS = ("correct", "abstract_only", "no_source", "wrong_related", "shuffled")

SUPPORT = ("supported", "partially_supported", "not_supported", "contradicted", "cannot_check")
STRENGTH = ("matches", "overstated", "understated")
OVER_TYPES = ("hedge_dropped", "scope_widened", "causal_from_correlational", "number_changed",
              "certainty_inflated", "other")


# ---------------------------------------------------------------- same work

def _arxiv_norm(a: Optional[str]) -> str:
    return re.sub(r"^arxiv:|v[0-9]+$", "", (a or "").strip().lower())


def same_work(a: Optional[Reference], b: Optional[Reference]) -> bool:
    """Two bibliographic records are the same work if they share a normalized DOI, an arXiv id (version
    stripped) or a normalized title. A missing record never matches."""
    if a is None or b is None:
        return False
    if a.doi and b.doi and clean_doi(a.doi).lower() == clean_doi(b.doi).lower():
        return True
    if _arxiv_norm(a.arxiv_id) and _arxiv_norm(a.arxiv_id) == _arxiv_norm(b.arxiv_id):
        return True
    return bool(norm_title(a.title)) and norm_title(a.title) == norm_title(b.title)


# ---------------------------------------------------------------- evidence

@dataclass
class Evidence:
    parts: list[tuple[str, str]] = field(default_factory=list)  # (label, text)
    meta: dict = field(default_factory=dict)


class Context:
    """Units, source records and the text cache; builds evidence deterministically."""

    def __init__(self, units: list[Unit], sources: dict[tuple[str, str], SourceRecord], cache: str | Path):
        self.units = {u.unit_id: u for u in units}
        self.sources = sources
        self.cache = Path(cache)
        self._text: dict[tuple[str, str], Optional[str]] = {}
        self.refs: dict[tuple[str, str], Reference] = {}
        for u in units:
            if u.reference is not None:
                self.refs.setdefault((u.survey_id, u.cite_key), u.reference)

    def same_work(self, s1: str, k1: str, s2: str, k2: str) -> bool:
        return (s1 == s2 and k1 == k2) or same_work(self.refs.get((s1, k1)), self.refs.get((s2, k2)))

    def shuffle_conflict(self, u: Unit, d: Unit) -> Optional[str]:
        """Why donor d's evidence is not a valid mismatch for u (same work, or identical source text), else None."""
        if self.same_work(u.survey_id, u.cite_key, d.survey_id, d.cite_key):
            return "donor cites the same work"
        hu, hd = (getattr(self.sources.get((x.survey_id, x.cite_key)), "text_sha256", None) for x in (u, d))
        if hu and hu == hd:
            return "donor source text is identical"
        return None

    def text(self, survey_id: str, key: str) -> Optional[str]:
        k = (survey_id, key)
        if k not in self._text:
            rec = self.sources.get(k)
            txt = None
            if rec and rec.access_level != "none" and rec.text_path:
                try:
                    txt = (self.cache / rec.text_path).read_text(encoding="utf-8").strip() or None
                except OSError:
                    txt = None
            self._text[k] = txt
        return self._text[k]

    def evidence_from(self, sentence: str, survey_id: str, key: str, first_only: bool = False) -> Evidence:
        txt = self.text(survey_id, key)
        if txt is None:
            return Evidence([], {"mode": "none"})
        if self.sources[(survey_id, key)].access_level == "abstract":
            return Evidence([("Abstract", txt)], {"mode": "abstract"})
        first = chunk(txt)[0]
        parts = [("Opening passage (abstract or front matter)", first)]
        picked = []
        if not first_only:
            picked = top_passages(sentence, txt, TOP_K, skip_first=True)
            parts += [(f"Retrieved passage {n}", p.text) for n, p in enumerate(picked, 1)]
        meta = {"mode": "first_passage" if first_only else "full_text",
                "passages": [[p.index, round(p.score, 4)] for p in picked]}
        return Evidence(parts, meta)

    def own(self, u: Unit, first_only: bool = False) -> Evidence:
        return self.evidence_from(u.sentence_text, u.survey_id, u.cite_key, first_only)

    def choose_wrong_related(self, u: Unit) -> Optional[tuple[str, float]]:
        """D18: same survey, same section preferred, excluding own and cocited keys and
        any key that is the same work as one of them (DOI, arXiv id or title); highest TF-IDF cosine
        between the candidate's first passage and the citing sentence."""
        banned = {u.cite_key, *u.cocited_keys}
        in_survey = sorted(k for (s, k) in self.sources if s == u.survey_id and k not in banned
                           and not any(self.same_work(s, k, s, b) for b in banned) and self.text(s, k))
        same_section = {o.cite_key for o in self.units.values()
                        if o.survey_id == u.survey_id and u.section is not None and o.section == u.section}
        pool = [k for k in in_survey if k in same_section] or in_survey
        if not pool:
            return None
        cands = {k: chunk(self.text(u.survey_id, k))[0] for k in pool}
        return most_similar(u.sentence_text, cands)[0]


def derange(units: list[Unit], seed: int = SHUFFLE_SEED,
            conflict: Optional[Callable[[Unit, Unit], Optional[str]]] = None) -> tuple[dict[str, str], list[str]]:
    """Seeded assignment unit_id -> donor unit_id, each unit used as a donor once. A valid donor is from a different
    survey and, if `conflict(unit, donor)` is given, has no conflict (same work, identical source text). If that is
    impossible for some units, the nearest assignment is used (a different unit; itself only as the last choice) and
    a warning is returned; callers flag the affected calls."""
    ids = sorted(u.unit_id for u in units)
    by_id = {u.unit_id: u for u in units}
    survey = {u.unit_id: u.survey_id for u in units}

    def valid(u, d):
        return survey[d] != survey[u] and not (conflict and conflict(by_id[u], by_id[d]))

    best, best_score = {}, None
    for attempt in range(200):
        rng = random.Random(f"{seed}:{attempt}")
        order, free = ids[:], ids[:]
        rng.shuffle(order)
        rng.shuffle(free)
        assign, invalid, selfs = {}, 0, 0
        for u in order:
            pick = next((d for d in free if d != u and valid(u, d)), None)
            if pick is None:
                invalid += 1
                pick = next((d for d in free if d != u), None)
                if pick is None:
                    pick, selfs = u, selfs + 1
            free.remove(pick)
            assign[u] = pick
        score = (selfs, invalid)
        if best_score is None or score < best_score:
            best, best_score = assign, score
        if score == (0, 0) or (len(set(survey.values())) < 2 and selfs == 0 and conflict is None):
            break
    warnings = []
    if best_score and best_score[1]:
        warnings.append(f"shuffled: {best_score[1]} of {len(ids)} units could not get a valid donor "
                        "(different survey, different work, different source text)")
    if best_score and best_score[0]:
        warnings.append(f"shuffled: {best_score[0]} unit(s) are assigned their own evidence (too few units)")
    return best, warnings


def evidence_for(ctx: Context, u: Unit, condition: str, meta: Optional[dict] = None) -> Evidence:
    """Evidence for (unit, condition). `meta` is the evidence record stored in the call (donor choices)."""
    meta = meta or {}
    if condition == "correct":
        return ctx.own(u)
    if condition == "abstract_only":
        return ctx.own(u, first_only=True)
    if condition == "no_source":
        return Evidence([], {"mode": "none"})
    if condition == "wrong_related":
        key = meta["key"]
        ev = ctx.evidence_from(u.sentence_text, u.survey_id, key)
        ev.meta["key"] = key
        return ev
    if condition == "shuffled":
        donor = ctx.units[meta["donor_unit_id"]]
        ev = ctx.own(donor)
        ev.meta["donor_unit_id"] = donor.unit_id
        return ev
    raise ValueError(f"unknown condition {condition!r}")


# ---------------------------------------------------------------- prompt

def template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def template_sha256() -> str:
    return hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()


def target_sentence(u: Unit) -> str:
    """sentence_text with [CITE] kept only on the citation command(s) holding u.cite_key; other commands become
    [OTHER]. Commands are re-parsed from sentence_latex in the order the extractor replaced them. If the counts do
    not line up (e.g. a cite command inside a LaTeX comment), the text is returned unchanged. Text that already
    contains [OTHER] is returned unchanged too: planted copies (planted.py) store the masked, edited text and keep
    the original LaTeX, which no longer matches it."""
    if "[OTHER]" in u.sentence_text:
        return u.sentence_text
    cmds = [ks for _, _, cmd, ks in find_cites(u.sentence_latex) if cmd != "nocite"]
    pieces = u.sentence_text.split("[CITE]")
    if len(pieces) - 1 != len(cmds) or not any(u.cite_key in ks for ks in cmds):
        return u.sentence_text
    out = [pieces[0]]
    for ks, rest in zip(cmds, pieces[1:]):
        out += ["[CITE]" if u.cite_key in ks else "[OTHER]", rest]
    return "".join(out)


def render_prompt(u: Unit, ev: Evidence) -> str:
    if ev.parts:
        block = "\n\n".join(f"[{label}]\n{text}" for label, text in ev.parts)
    else:
        block = "(No source text is available for this reference.)"
    title = (u.reference.title if u.reference and u.reference.title else None) or "(unknown)"
    vals = {"sentence": target_sentence(u), "title": title, "cocited_count": str(len(u.cocited_keys)),
            "evidence": block}
    # one pass, so placeholder-like text inside the evidence is never substituted
    return re.sub(r"\{\{(sentence|title|cocited_count|evidence)\}\}", lambda m: vals[m.group(1)], template())


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def make_call_id(unit_id: str, condition: str, version: str = PROMPT_VERSION) -> str:
    return hashlib.sha1(f"{unit_id}|{condition}|{version}".encode("utf-8")).hexdigest()


def build_calls(ctx: Context, units: list[Unit], conditions: list[str]) -> tuple[list[dict], list[str]]:
    for c in conditions:
        if c not in CONDITIONS:
            raise ValueError(f"unknown condition {c!r}")
    warnings: list[str] = []
    donors: dict[str, str] = {}
    if "shuffled" in conditions:
        eligible = [u for u in units if ctx.own(u).parts]
        skipped = len(units) - len(eligible)
        if skipped:
            warnings.append(f"shuffled: {skipped} unit(s) skipped (no own source text to act as donor)")
        donors, w = derange(eligible, conflict=ctx.shuffle_conflict)
        warnings += w
    calls = []
    for u in units:
        for cond in conditions:
            meta: dict = {}
            if cond == "wrong_related":
                pick = ctx.choose_wrong_related(u)
                if pick is None:
                    warnings.append(f"wrong_related: no candidate for unit {u.unit_id}, skipped")
                    continue
                meta = {"key": pick[0], "key_score": round(pick[1], 4)}
            elif cond == "shuffled":
                if u.unit_id not in donors:
                    continue
                d = ctx.units.get(donors[u.unit_id])
                meta = {"donor_unit_id": donors[u.unit_id]}
                reason = None
                if donors[u.unit_id] == u.unit_id:
                    reason = "donor is the unit itself"
                elif d is not None:
                    reason = "donor from the same survey" if d.survey_id == u.survey_id else ctx.shuffle_conflict(u, d)
                if reason:
                    meta["shuffle_warning"] = reason
            ev = evidence_for(ctx, u, cond, meta)
            ev.meta.update(meta)
            calls.append({"call_id": make_call_id(u.unit_id, cond), "unit_id": u.unit_id, "condition": cond,
                          "prompt_version": PROMPT_VERSION, "template_sha256": template_sha256(),
                          "evidence": ev.meta, "prompt_sha256": sha256(render_prompt(u, ev))})
    return calls, warnings


def render_call(ctx: Context, call: dict) -> str:
    u = ctx.units[call["unit_id"]]
    return render_prompt(u, evidence_for(ctx, u, call["condition"], call.get("evidence")))


# ---------------------------------------------------------------- parsing

def _first_object(text: str) -> Optional[dict]:
    dec, first = json.JSONDecoder(), None
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict):
            if "support" in obj:
                return obj
            first = first or obj
    return first


def parse_reply(text: str) -> dict:
    """Validated fields from a judge reply. Anything invalid gives support=None and an `error`; no label is guessed."""
    out = {"support": None, "strength": None, "overstatement_types": [], "confidence": None,
           "evidence_quote": "", "error": None}
    obj = _first_object(text or "")
    if obj is None:
        out["error"] = "no_json_object"
        return out
    sup = obj.get("support")
    if sup not in SUPPORT:
        out["error"] = f"invalid_support: {sup!r}"
        return out
    conf = obj.get("confidence")
    if isinstance(conf, str) and conf.strip() in ("1", "2", "3"):
        conf = int(conf)
    elif isinstance(conf, float) and conf.is_integer():
        conf = int(conf)  # 2.0 is stored as 2
    if isinstance(conf, bool) or not isinstance(conf, int) or conf not in (1, 2, 3):
        out["error"] = f"invalid_confidence: {conf!r}"
        return out
    strength, types = None, []
    if sup in ("supported", "partially_supported"):
        strength = obj.get("strength")
        if strength not in STRENGTH:
            out["error"] = f"invalid_strength: {strength!r}"
            return out
        raw = obj.get("overstatement_types") or []
        if not isinstance(raw, list) or any(t not in OVER_TYPES for t in raw):
            out["error"] = f"invalid_overstatement_types: {raw!r}"
            return out
        types = list(dict.fromkeys(raw)) if strength == "overstated" else []
    quote = obj.get("evidence_quote") or ""
    if not isinstance(quote, str):
        out["error"] = "invalid_evidence_quote"
        return out
    out.update(support=sup, strength=strength, overstatement_types=types, confidence=conf,
               evidence_quote=quote[:300])
    return out


# ---------------------------------------------------------------- backends

class BackendError(Exception):
    def __init__(self, msg: str, meta: Optional[dict] = None):
        super().__init__(msg)
        self.meta = meta or {}


class Pending(Exception):
    """FileBackend: no reply file yet."""


class ClaudeCLIBackend:
    """Runs `claude -p` with no tools. Needs a logged-in Claude Code CLI on PATH. The prompt goes through stdin
    because prompts can exceed argv length limits.

    Isolation: empty working directory, `--setting-sources ""` (no user, project or local settings), a neutral
    `--system-prompt`, no tools, no MCP, no session persistence. NOT verified: that user-level memory files
    (~/.claude/CLAUDE.md, auto-memory) stay out of the context; the CLI login was expired when this was written,
    so no real call could be inspected. Check the first real run before trusting it. `--bare` would skip memory
    but needs ANTHROPIC_API_KEY, so it is not used. The full argv (without the prompt) is stored in model_meta."""

    def __init__(self, model: str, timeout: float = 600):
        if not MODEL_RE.fullmatch(model or "") or model.startswith("-"):
            raise ValueError(f"invalid model name {model!r}")
        self.model, self.timeout = model, timeout

    def complete(self, prompt: str, call_id: Optional[str] = None) -> tuple[str, dict]:
        cmd = [shutil.which("claude") or "claude", "-p", "--model", self.model, "--tools", "",
               "--strict-mcp-config", "--no-session-persistence", "--output-format", "json",
               "--setting-sources", "", "--system-prompt", CLI_SYSTEM_PROMPT]
        try:
            with tempfile.TemporaryDirectory(prefix="citebench_cli_") as cwd:
                r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                   timeout=self.timeout, cwd=cwd)
        except subprocess.TimeoutExpired:
            raise BackendError(f"timeout after {self.timeout}s", {"argv": cmd})
        except OSError as e:
            raise BackendError(f"cannot run claude: {e}", {"argv": cmd})
        try:
            d = json.loads(r.stdout)
        except ValueError:
            raise BackendError(f"unparseable CLI output (exit {r.returncode}): {(r.stderr or r.stdout)[:500]}",
                               {"argv": cmd})
        meta = {"model_ids": sorted((d.get("modelUsage") or {}).keys()), "duration_ms": d.get("duration_ms"),
                "argv": cmd}
        if d.get("is_error") or r.returncode != 0:
            raise BackendError(f"cli_error: {str(d.get('result'))[:500]}", meta)
        return d.get("result") or "", meta


class OllamaBackend:
    def __init__(self, model: str, url: str = "http://127.0.0.1:11434", timeout: float = 600):
        self.model, self.url, self.timeout = model, url.rstrip("/"), timeout
        self._digest: Optional[str] = None
        self._digest_tried = False

    def _model_digest(self) -> Optional[str]:
        if not self._digest_tried:
            self._digest_tried = True
            try:
                tags = requests.get(f"{self.url}/api/tags", timeout=30).json()
                for m in tags.get("models", []):
                    if self.model in (m.get("name"), m.get("model")):
                        self._digest = m.get("digest")
            except (requests.RequestException, ValueError):
                pass
        return self._digest

    def complete(self, prompt: str, call_id: Optional[str] = None) -> tuple[str, dict]:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False,
                "format": "json",
                "options": {"temperature": 0, "seed": OLLAMA_SEED, "num_ctx": NUM_CTX}}
        try:
            r = requests.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            d = r.json()
        except (requests.RequestException, ValueError) as e:
            raise BackendError(f"ollama_error: {e}")
        meta = {"model": self.model, "digest": self._model_digest(), "temperature": 0, "seed": OLLAMA_SEED,
                "eval_count": d.get("eval_count"), "prompt_eval_count": d.get("prompt_eval_count"),
                "total_duration": d.get("total_duration"), "num_ctx": NUM_CTX}
        used = d.get("prompt_eval_count")
        if isinstance(used, int) and used >= NUM_CTX - 16:
            raise BackendError(f"context_truncated: prompt_eval_count={used} num_ctx={NUM_CTX}", meta)
        return (d.get("message") or {}).get("content") or "", meta


class FileBackend:
    """Writes each prompt to <dir>/prompts/<call_id>.md and reads <dir>/replies/<call_id>.json if present.
    Lets an orchestrating agent session run subagents as judges and drop replies in."""

    def __init__(self, dir: str | Path):
        self.dir = Path(dir)

    def complete(self, prompt: str, call_id: Optional[str] = None) -> tuple[str, dict]:
        (self.dir / "prompts").mkdir(parents=True, exist_ok=True)
        (self.dir / "replies").mkdir(parents=True, exist_ok=True)
        (self.dir / "prompts" / f"{call_id}.md").write_text(prompt, encoding="utf-8", newline="\n")
        reply = self.dir / "replies" / f"{call_id}.json"
        if not reply.exists():
            raise Pending(call_id)
        return reply.read_text(encoding="utf-8"), {"reply_file": reply.name}


# ---------------------------------------------------------------- runner

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def latest_predictions(path: str | Path, judge: Optional[str] = None) -> dict[tuple[str, int], dict]:
    """Last record per (call_id, run_index); malformed lines are skipped. Optionally only one judge's records."""
    out: dict[tuple[str, int], dict] = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            key = (r["call_id"], r["run_index"])
        except (ValueError, KeyError, TypeError):
            continue
        if judge is None or r.get("judge") == judge:
            out[key] = r
    return out


def run_calls(calls: list[dict], ctx: Context, backend, judge: str, out: str | Path, repeat: int = 1,
              now: Callable[[], str] = _now) -> dict[str, int]:
    done = latest_predictions(out, judge)
    counts = {"done": 0, "skipped": 0, "errors": 0, "pending": 0}
    with open(out, "a", encoding="utf-8", newline="\n") as f:
        for call in calls:
            prompt = None
            for run in range(repeat):
                prev = done.get((call["call_id"], run))
                if prev is not None and not prev.get("error"):
                    counts["skipped"] += 1
                    continue
                prompt = prompt or render_call(ctx, call)
                rec = {"call_id": call["call_id"], "unit_id": call["unit_id"], "judge": judge,
                       "condition": call["condition"], "run_index": run, "prompt_version": PROMPT_VERSION,
                       "prompt_sha256": sha256(prompt), "template_sha256": call.get("template_sha256"),
                       "started_at": now()}
                if call.get("prompt_sha256") and call["prompt_sha256"] != rec["prompt_sha256"]:
                    reply, meta, err = "", {}, "prompt_hash_mismatch: rebuilt prompt differs from the built call"
                else:
                    key = call["call_id"] if run == 0 else f"{call['call_id']}.r{run}"
                    try:
                        reply, meta = backend.complete(prompt, call_id=key)
                        err = None
                    except Pending:
                        counts["pending"] += 1
                        continue
                    except BackendError as e:
                        reply, meta, err = "", e.meta, str(e)
                parsed = parse_reply(reply) if err is None else {
                    "support": None, "strength": None, "overstatement_types": [], "confidence": None,
                    "evidence_quote": "", "error": err}
                rec.update(parsed)
                rec.update(raw_reply=reply[:4000], model_meta=meta, finished_at=now())
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                counts["errors" if rec["error"] else "done"] += 1
    return counts


# ---------------------------------------------------------------- CLI

def _context(args) -> Context:
    units = list(read_jsonl(args.units, Unit))
    return Context(units, latest_records(args.sources), args.cache)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="citebench.judge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "run"):
        p = sub.add_parser(name)
        p.add_argument("--units", required=True)
        p.add_argument("--sources", required=True)
        p.add_argument("--cache", required=True)
        p.add_argument("--out", required=True)
    b = sub.choices["build"]
    b.add_argument("--conditions", default="correct")
    r = sub.choices["run"]
    r.add_argument("--calls", required=True)
    r.add_argument("--backend", choices=["claude_cli", "ollama", "file"], required=True)
    r.add_argument("--model", default="")
    r.add_argument("--dir")
    r.add_argument("--url", default="http://127.0.0.1:11434")
    r.add_argument("--timeout", type=float, default=600)
    r.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args(argv)
    ctx = _context(args)
    if args.cmd == "build":
        calls, warnings = build_calls(ctx, list(ctx.units.values()), args.conditions.split(","))
        for w in warnings:
            print(f"warning: {w}", file=sys.stderr)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            for c in calls:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"calls={len(calls)} warnings={len(warnings)}")
        return 0
    calls = [json.loads(line) for line in Path(args.calls).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.backend == "claude_cli":
        backend = ClaudeCLIBackend(args.model, args.timeout)
    elif args.backend == "ollama":
        backend = OllamaBackend(args.model, args.url, args.timeout)
    else:
        if not args.dir:
            ap.error("--dir is required for the file backend")
        backend = FileBackend(args.dir)
    counts = run_calls(calls, ctx, backend, f"{args.backend}:{args.model}", args.out, args.repeat)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
