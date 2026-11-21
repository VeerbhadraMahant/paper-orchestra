import json
import subprocess
from unittest import mock

import pytest

from citebench import judge
from citebench.judge import (ClaudeCLIBackend, Context, FileBackend, OllamaBackend, BackendError, Pending,
                             build_calls, derange, evidence_for, latest_predictions, parse_reply, render_prompt,
                             run_calls)
from citebench.units import Reference, SourceRecord, Unit


def topic(word: str, n: int = 40) -> str:
    return f"{word} {word}s study of {word} methods. " * n


def make_world(tmp_path, surveys=("S1", "S2")):
    cache = tmp_path / "cache"
    (cache / "texts").mkdir(parents=True)
    units, sources = [], {}
    spec = {  # key -> (access, abstract word, body word)
        "a": ("full_text", "diffusion", "privacy"), "b": ("full_text", "federated", "privacy"),
        "c": ("full_text", "diffusion", "memorization"), "d": ("abstract", "privacy", ""),
        "e": ("none", "", "")}
    for s in surveys:
        for i, (key, (acc, w1, w2)) in enumerate(spec.items()):
            rec = SourceRecord(cite_key=key, survey_id=s, access_level=acc)
            if acc != "none":
                body = f"{w1.capitalize()} front matter abstract. " + (f"\n\n{topic('filler', 30)}\n\n{topic(w2)}" if w2 else "")
                p = cache / "texts" / f"{s}_{key}.txt"
                p.write_text(body, encoding="utf-8")
                rec.text_path = f"texts/{s}_{key}.txt"
            sources[(s, key)] = rec
        units.append(Unit(unit_id=f"{s}-u1", survey_id=s, source_file="x.tex", char_start=1, char_end=2,
                          section="Attacks", sentence_latex="", sentence_text="Diffusion privacy attack [CITE].",
                          cite_key="a", cocited_keys=["b"], reference=Reference(key="a", title="Paper A")))
        units.append(Unit(unit_id=f"{s}-u2", survey_id=s, source_file="x.tex", char_start=5, char_end=6,
                          section="Defenses", sentence_text="Federated privacy defense [CITE].",
                          sentence_latex="", cite_key="b", reference=Reference(key="b", title="Paper B")))
        units.append(Unit(unit_id=f"{s}-u3", survey_id=s, source_file="x.tex", char_start=9, char_end=10,
                          section="Attacks", sentence_text="Memorization of diffusion [CITE].",
                          sentence_latex="", cite_key="c"))
    return Context(units, sources, cache), units


# ---- conditions

def test_correct_evidence_full_abstract_none(tmp_path):
    ctx, units = make_world(tmp_path)
    u = units[0]
    ev = evidence_for(ctx, u, "correct")
    assert ev.meta["mode"] == "full_text" and ev.parts[0][1].startswith("Diffusion front matter")
    assert 1 < len(ev.parts) <= 6 and ev.meta["passages"]
    first = evidence_for(ctx, u, "abstract_only")
    assert len(first.parts) == 1 and first.parts[0] == ev.parts[0]
    assert evidence_for(ctx, u, "no_source").parts == []
    ctx.sources[("S1", "a")].access_level = "abstract"
    ctx._text.clear()
    assert evidence_for(ctx, u, "correct").meta["mode"] == "abstract"
    ctx.sources[("S1", "a")].access_level = "none"
    ctx._text.clear()
    assert evidence_for(ctx, u, "correct").parts == []


def test_wrong_related_excludes_own_and_cocited_stays_in_survey_prefers_section(tmp_path):
    ctx, units = make_world(tmp_path)
    u = units[0]  # cites a, cocited b, section Attacks
    key, score = ctx.choose_wrong_related(u)
    # same-section keys in S1 are a and c; a is own, so c is chosen even though d or e might be elsewhere
    assert key == "c" and score > 0
    calls, _ = build_calls(ctx, [u], ["wrong_related"])
    meta = calls[0]["evidence"]
    assert meta["key"] == "c" and meta["key"] not in {u.cite_key, *u.cocited_keys}
    ev = evidence_for(ctx, u, "wrong_related", meta)
    assert ev.parts[0][1].startswith("Diffusion front matter")  # c's own first passage
    # a unit whose section has no other candidate falls back to the whole survey
    key2, _ = ctx.choose_wrong_related(units[1])  # b, section Defenses (only b)
    assert key2 not in {"b", "e"}


def test_wrong_related_none_when_no_candidates(tmp_path):
    ctx, units = make_world(tmp_path)
    for k in ("b", "c", "d"):
        ctx.sources[("S1", k)].access_level = "none"
    ctx._text.clear()
    assert ctx.choose_wrong_related(units[0]) is None
    calls, warnings = build_calls(ctx, [units[0]], ["wrong_related"])
    assert calls == [] and warnings


def test_shuffled_crosses_surveys_and_is_reproducible(tmp_path):
    ctx, units = make_world(tmp_path)
    d1, w1 = derange(units)
    d2, _ = derange(units)
    assert d1 == d2 and not w1
    assert sorted(d1.values()) == sorted(u.unit_id for u in units)
    by_id = {u.unit_id: u for u in units}
    assert all(by_id[k].survey_id != by_id[v].survey_id for k, v in d1.items())
    calls, _ = build_calls(ctx, units, ["shuffled"])
    c = next(c for c in calls if c["unit_id"] == "S1-u1")
    assert c["evidence"]["donor_unit_id"] == d1["S1-u1"]
    assert judge.render_call(ctx, c) == judge.render_call(ctx, c)


def test_shuffled_single_survey_falls_back_with_warning(tmp_path):
    ctx, units = make_world(tmp_path, surveys=("S1",))
    d, w = derange(units)
    assert w and all(k != v for k, v in d.items())
    calls, warnings = build_calls(ctx, units, ["shuffled"])
    assert warnings and all(c["evidence"].get("shuffle_warning") for c in calls)


def test_build_skips_shuffled_units_without_donor_text(tmp_path):
    ctx, units = make_world(tmp_path)
    ctx.sources[("S1", "a")].access_level = "none"
    ctx._text.clear()
    calls, warnings = build_calls(ctx, units, ["shuffled"])
    assert "S1-u1" not in {c["unit_id"] for c in calls} and any("skipped" in w for w in warnings)


# ---- prompt

def test_prompt_parts_and_no_source(tmp_path):
    ctx, units = make_world(tmp_path)
    u = units[0]
    p = render_prompt(u, evidence_for(ctx, u, "correct"))
    for needle in ("Diffusion privacy attack [CITE].", "Paper A", "cited in the same sentence: 1", "[Opening passage",
                   "ONLY the evidence", "cannot_check", "partially_supported", "contradicted", "causal_from_correlational",
                   '"evidence_quote"'):
        assert needle in p
    assert "{{" not in p and chr(0x2014) not in judge.template()
    n = render_prompt(u, evidence_for(ctx, u, "no_source"))
    assert "No source text is available" in n and "Opening passage" not in n
    assert "(unknown)" in render_prompt(units[2], evidence_for(ctx, units[2], "no_source"))


def test_template_hash_and_call_record(tmp_path):
    ctx, units = make_world(tmp_path)
    calls, _ = build_calls(ctx, units[:1], ["correct", "no_source"])
    assert [c["condition"] for c in calls] == ["correct", "no_source"]
    assert all(c["prompt_version"] == "judge_v1" and len(c["template_sha256"]) == 64 for c in calls)
    assert calls[0]["call_id"] != calls[1]["call_id"]
    assert "evidence_text" not in json.dumps(calls) and "front matter" not in json.dumps(calls)


# ---- parsing

GOOD = {"support": "supported", "strength": "overstated", "overstatement_types": ["hedge_dropped"],
        "confidence": 2, "evidence_quote": "q"}


def test_parse_fenced_prose_and_plain():
    for text in (json.dumps(GOOD), "```json\n" + json.dumps(GOOD) + "\n```",
                 "Sure, here is my answer: " + json.dumps(GOOD) + " Hope that helps {not json}"):
        r = parse_reply(text)
        assert r["error"] is None and r["support"] == "supported" and r["overstatement_types"] == ["hedge_dropped"]


def test_parse_invalid_and_garbage_never_guess():
    for bad in ({**GOOD, "support": "yes"}, {**GOOD, "confidence": 5}, {**GOOD, "strength": "huge"},
                {**GOOD, "overstatement_types": ["bogus"]}, {"strength": "matches"}):
        r = parse_reply(json.dumps(bad))
        assert r["support"] is None and r["error"]
    for garbage in ("", "I think it is supported", "{broken json"):
        r = parse_reply(garbage)
        assert r["support"] is None and r["error"] == "no_json_object"


def test_parse_normalizes_strength_for_unsupported_and_truncates_quote():
    r = parse_reply(json.dumps({"support": "cannot_check", "strength": "matches", "overstatement_types": ["other"],
                                "confidence": "3", "evidence_quote": "x" * 400}))
    assert r["error"] is None and r["strength"] is None and r["overstatement_types"] == []
    assert r["confidence"] == 3 and len(r["evidence_quote"]) == 300


# ---- backends

def cp(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_claude_cli_success_error_timeout():
    ok = json.dumps({"result": "hello", "is_error": False, "modelUsage": {"claude-x": {}}, "duration_ms": 5})
    with mock.patch("subprocess.run", return_value=cp(ok)) as run:
        text, meta = ClaudeCLIBackend("haiku").complete("PROMPT")
    assert text == "hello" and meta["model_ids"] == ["claude-x"]
    args, kw = run.call_args
    assert kw["input"] == "PROMPT" and "PROMPT" not in args[0]
    assert "--tools" in args[0] and "--strict-mcp-config" in args[0] and "--no-session-persistence" in args[0]
    err = json.dumps({"result": "rate limited", "is_error": True})
    with mock.patch("subprocess.run", return_value=cp(err)):
        with pytest.raises(BackendError, match="rate limited"):
            ClaudeCLIBackend("haiku").complete("p")
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 1)):
        with pytest.raises(BackendError, match="timeout"):
            ClaudeCLIBackend("haiku", timeout=1).complete("p")
    with mock.patch("subprocess.run", return_value=cp("not json", 1, "boom")):
        with pytest.raises(BackendError, match="unparseable"):
            ClaudeCLIBackend("haiku").complete("p")


def test_ollama_backend_request_shape_and_digest():
    chat = mock.Mock(json=lambda: {"message": {"content": "{}"}, "eval_count": 3})
    chat.raise_for_status = lambda: None
    tags = mock.Mock(json=lambda: {"models": [{"name": "qwen3:8b", "digest": "abc123"}]})
    with mock.patch("requests.post", return_value=chat) as post, mock.patch("requests.get", return_value=tags):
        b = OllamaBackend("qwen3:8b")
        text, meta = b.complete("P")
        b.complete("P")
    body = post.call_args.kwargs["json"]
    assert body["stream"] is False and body["format"] == "json"
    assert body["options"]["temperature"] == 0 and "seed" in body["options"]
    assert post.call_args.args[0] == "http://127.0.0.1:11434/api/chat"
    assert text == "{}" and meta["digest"] == "abc123"
    import requests
    with mock.patch("requests.post", side_effect=requests.ConnectionError("down")):
        with pytest.raises(BackendError):
            OllamaBackend("m").complete("P")


def test_file_backend_pending_then_answered(tmp_path):
    b = FileBackend(tmp_path / "d")
    with pytest.raises(Pending):
        b.complete("PROMPT", call_id="c1")
    assert (tmp_path / "d" / "prompts" / "c1.md").read_text(encoding="utf-8") == "PROMPT"
    (tmp_path / "d" / "replies" / "c1.json").write_text(json.dumps(GOOD), encoding="utf-8")
    text, _ = b.complete("PROMPT", call_id="c1")
    assert parse_reply(text)["support"] == "supported"


# ---- runner

class Fake:
    def __init__(self, replies):
        self.replies, self.n = list(replies), 0

    def complete(self, prompt, call_id=None):
        self.n += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {"model_ids": ["fake"]}


def test_run_resume_retry_errors_and_repeat(tmp_path):
    ctx, units = make_world(tmp_path)
    calls, _ = build_calls(ctx, units[:2], ["correct"])
    out = tmp_path / "p.jsonl"
    ok = json.dumps(GOOD)
    be = Fake([ok, BackendError("boom")])
    c = run_calls(calls, ctx, be, "fake:m", out)
    assert c["done"] == 1 and c["errors"] == 1
    recs = [json.loads(line) for line in out.read_text().splitlines()]
    assert recs[1]["support"] is None and "boom" in recs[1]["error"]
    assert recs[0]["prompt_version"] == "judge_v1" and recs[0]["judge"] == "fake:m" and recs[0]["started_at"].endswith("+00:00")
    # resume: the good record is skipped, the error is retried; append-only, last wins
    be2 = Fake([ok])
    c2 = run_calls(calls, ctx, be2, "fake:m", out)
    assert be2.n == 1 and c2["skipped"] == 1 and c2["done"] == 1
    assert len(out.read_text().splitlines()) == 3
    assert all(not r["error"] for r in latest_predictions(out).values())
    # repeat: run_index 0 is cached, 1 and 2 are new
    be3 = Fake([ok] * 4)
    run_calls(calls, ctx, be3, "fake:m", out, repeat=3)
    assert be3.n == 4
    assert {k[1] for k in latest_predictions(out)} == {0, 1, 2}


def test_run_with_file_backend_skips_pending_and_detects_hash_mismatch(tmp_path):
    ctx, units = make_world(tmp_path)
    calls, _ = build_calls(ctx, units[:1], ["correct"])
    out = tmp_path / "p.jsonl"
    fb = FileBackend(tmp_path / "fd")
    assert run_calls(calls, ctx, fb, "file:x", out)["pending"] == 1
    assert not out.read_text()
    (tmp_path / "fd" / "replies" / f"{calls[0]['call_id']}.json").write_text(json.dumps(GOOD), encoding="utf-8")
    assert run_calls(calls, ctx, fb, "file:x", out)["done"] == 1
    bad = [{**calls[0], "prompt_sha256": "0" * 64}]
    out2 = tmp_path / "p2.jsonl"
    assert run_calls(bad, ctx, Fake([]), "fake:m", out2)["errors"] == 1
    assert "prompt_hash_mismatch" in json.loads(out2.read_text())["error"]


def test_cli_build_and_run(tmp_path, capsys):
    from citebench.units import write_jsonl
    ctx, units = make_world(tmp_path)
    write_jsonl(tmp_path / "u.jsonl", units)
    write_jsonl(tmp_path / "s.jsonl", ctx.sources.values())
    base = ["--units", str(tmp_path / "u.jsonl"), "--sources", str(tmp_path / "s.jsonl"), "--cache", str(ctx.cache)]
    assert judge.main(["build", *base, "--conditions", "correct,no_source", "--out", str(tmp_path / "c.jsonl")]) == 0
    assert len((tmp_path / "c.jsonl").read_text().splitlines()) == len(units) * 2
    assert judge.main(["run", *base, "--calls", str(tmp_path / "c.jsonl"), "--backend", "file", "--model", "m",
                       "--dir", str(tmp_path / "fd"), "--out", str(tmp_path / "p.jsonl")]) == 0
    assert "pending=" in capsys.readouterr().out


def test_target_sentence_marks_only_the_target_command():
    from citebench.judge import target_sentence
    from citebench.units import Unit

    def mk(key, latex, text):
        return Unit(unit_id="u", survey_id="s", source_file="f", char_start=0, char_end=1, section=None,
                    sentence_latex=latex, sentence_text=text, cite_key=key)

    latex = r"A \cite{a} beats B \citep{b,c}."
    text = "A [CITE] beats B [CITE]."
    assert target_sentence(mk("a", latex, text)) == "A [CITE] beats B [OTHER]."
    assert target_sentence(mk("c", latex, text)) == "A [OTHER] beats B [CITE]."
    # one command holding several keys stays a single [CITE]
    assert target_sentence(mk("b", r"X \cite{a,b}.", "X [CITE].")) == "X [CITE]."
    # counts do not line up: unchanged
    assert target_sentence(mk("a", r"A \cite{a}.", "A [CITE] [CITE].")) == "A [CITE] [CITE]."


# ---- review fixes

def test_parse_confidence_integral_float_and_bool():
    r = parse_reply(json.dumps({**GOOD, "confidence": 2.0}))
    assert r["error"] is None and r["confidence"] == 2 and isinstance(r["confidence"], int)
    for bad in (2.5, True, False, None, [2], 4.0):
        assert parse_reply(json.dumps({**GOOD, "confidence": bad}))["error"]


def test_wrong_related_excludes_same_work_under_other_key(tmp_path):
    ctx, units = make_world(tmp_path)
    # key "d" is the same paper as the unit's own key "a" (duplicate bib entry, same DOI, different title text)
    ctx.refs[("S1", "a")] = Reference(key="a", title="Paper A", doi="https://doi.org/10.1/X")
    ctx.refs[("S1", "d")] = Reference(key="d", title="Other spelling", doi="10.1/x")
    # key "c" has the same arXiv id as the cocited key "b"
    ctx.refs[("S1", "b")] = Reference(key="b", title="Paper B", arxiv_id="2401.00001v2")
    ctx.refs[("S1", "c")] = Reference(key="c", title="Different", arxiv_id="arXiv:2401.00001")
    assert ctx.choose_wrong_related(units[0]) is None  # only a, b, c, d have text; all are the same work as a or b
    ctx.refs[("S1", "c")] = Reference(key="c", title="Paper A")  # same normalized title as a
    assert ctx.choose_wrong_related(units[0]) is None
    ctx.refs[("S1", "c")] = Reference(key="c", title="Unrelated")
    assert ctx.choose_wrong_related(units[0])[0] == "c"


def test_same_work_rules():
    R = Reference
    assert judge.same_work(R(key="x", doi="doi:10.1/A"), R(key="y", doi="10.1/a"))
    assert judge.same_work(R(key="x", arxiv_id="1234.5678v1"), R(key="y", arxiv_id="arXiv:1234.5678v3"))
    assert judge.same_work(R(key="x", title="A {Good} Title!"), R(key="y", title="a good title"))
    assert not judge.same_work(R(key="x", title=""), R(key="y", title=""))
    assert not judge.same_work(None, R(key="y", title="t"))


def test_shuffled_avoids_same_work_and_same_text_donors(tmp_path):
    ctx, units = make_world(tmp_path)
    for s in ("S1", "S2"):
        ctx.sources[(s, "a")].text_sha256 = "h-a"
    d, w = derange(units, conflict=ctx.shuffle_conflict)
    by_id = {u.unit_id: u for u in units}
    assert not w
    for k, v in d.items():
        assert by_id[k].survey_id != by_id[v].survey_id
        assert ctx.shuffle_conflict(by_id[k], by_id[v]) is None
    # S1-u1 (key a) can never take S2-u1 (key a): same work and same text
    assert d["S1-u1"] != "S2-u1"


def test_shuffled_flags_unavoidable_conflict_per_call(tmp_path):
    ctx, units = make_world(tmp_path)
    units = [u for u in units if u.unit_id in ("S1-u1", "S2-u1")]  # both cite key a: no valid donor exists
    calls, warnings = build_calls(ctx, units, ["shuffled"])
    assert warnings and all("shuffle_warning" in c["evidence"] for c in calls)
    assert all("same work" in c["evidence"]["shuffle_warning"] for c in calls)


def test_claude_cli_isolation_args_cwd_and_model_validation(tmp_path):
    ok = json.dumps({"result": "hi", "is_error": False})
    with mock.patch("subprocess.run", return_value=cp(ok)) as run:
        _, meta = ClaudeCLIBackend("haiku").complete("PROMPT")
    argv = run.call_args.args[0]
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--system-prompt") + 1] == judge.CLI_SYSTEM_PROMPT
    assert meta["argv"] == argv and "PROMPT" not in argv
    cwd = run.call_args.kwargs["cwd"]
    assert cwd and not __import__("os").path.exists(cwd)  # a fresh temp dir, removed afterwards
    for bad in ("haiku --foo", "a b", "x;rm", "", "--help", "m\n"):
        with pytest.raises(ValueError):
            ClaudeCLIBackend(bad)
    assert ClaudeCLIBackend("claude-opus-4.5:x[1m]")


def test_ollama_context_truncation_is_an_error():
    def chat(n):
        c = mock.Mock(json=lambda: {"message": {"content": "{}"}, "prompt_eval_count": n})
        c.raise_for_status = lambda: None
        return c
    with mock.patch("requests.get", side_effect=__import__("requests").ConnectionError()):
        with mock.patch("requests.post", return_value=chat(100)) as post:
            _, meta = OllamaBackend("m").complete("P")
        assert post.call_args.kwargs["json"]["options"]["num_ctx"] == 16384
        assert meta["prompt_eval_count"] == 100 and meta["num_ctx"] == 16384
        with mock.patch("requests.post", return_value=chat(16384 - 16)):
            with pytest.raises(BackendError, match="context_truncated") as ei:
                OllamaBackend("m").complete("P")
        assert ei.value.meta["prompt_eval_count"] == 16384 - 16


def test_target_sentence_keeps_masked_text_with_other():
    from citebench.judge import target_sentence
    u = Unit(unit_id="u", survey_id="s", source_file="f", char_start=0, char_end=1, section=None,
             sentence_latex=r"A \cite{a} beats B \citep{b}.", sentence_text="A [CITE] beats B [OTHER].",
             cite_key="a")
    assert target_sentence(u) == "A [CITE] beats B [OTHER]."
