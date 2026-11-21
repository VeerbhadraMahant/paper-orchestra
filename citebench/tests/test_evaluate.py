import json
import math

import pytest

from citebench import evaluate as ev

S, P, N, C, X = ev.SUPPORT


def test_prf_and_macro_exclude_absent_classes():
    gold = [S, S, N, N]
    pred = [S, N, N, N]
    prf = ev.per_class_prf(gold, pred)
    assert prf[S]["precision"] == 1 and prf[S]["recall"] == 0.5
    assert prf[S]["f1"] == pytest.approx(2 / 3)
    assert prf[N]["f1"] == pytest.approx(0.8)
    assert prf[C]["f1"] == 0 and prf[C]["support"] == 0
    # only supported and not_supported enter the average
    assert ev.macro_f1(gold, pred) == pytest.approx((2 / 3 + 0.8) / 2)


def test_accuracy_and_confusion():
    gold = [S, S, N, N]
    pred = [S, N, N, N]
    assert ev.accuracy(gold, pred) == 0.75
    m = ev.confusion_matrix(gold, pred)
    assert m[0][0] == 1 and m[0][2] == 1 and m[2][2] == 2
    assert sum(map(sum, m)) == 4
    with pytest.raises(ValueError):
        ev.confusion_matrix(["bogus"], [S])


def test_missing_policy():
    gold = [S, S, N, N]
    pred = [S, None, N, N]
    assert ev.accuracy(gold, pred) == 0.75  # missing counted wrong
    assert ev.accuracy(gold, pred, missing="exclude") == 1.0
    assert ev.confusion_matrix(gold, pred)[0][5] == 1
    assert ev.confusion_matrix(gold, pred, missing="exclude")[0][5] == 0
    prf = ev.per_class_prf(gold, pred)
    assert prf[S]["recall"] == 0.5 and prf[S]["precision"] == 1
    assert ev.n_missing(pred) == 1
    assert ev.correct_flags(gold, pred) == [True, None, True, True]
    with pytest.raises(ValueError):
        ev.accuracy(gold, pred, missing="bogus")


def test_kappa():
    assert ev.cohen_kappa([S, N, N], [S, N, N]) == 1.0
    a = [1] * 25 + [0] * 25
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert ev.cohen_kappa(a, b) == pytest.approx(0.4)  # po 0.7, pe 0.5
    assert ev.cohen_kappa([S, S], [S, S]) == 1.0  # pe = 1 degenerate
    assert ev.cohen_kappa([S, None], [S, S], missing="exclude") == 1.0


def test_bootstrap_ci_contains_point_and_is_reproducible():
    gold = [S, S, N, N, S, N, S, S, N, C] * 5
    pred = [S, N, N, N, S, S, S, S, N, C] * 5
    r1 = ev.bootstrap_ci(ev.accuracy, gold, pred, n=300, seed=7)
    r2 = ev.bootstrap_ci(ev.accuracy, gold, pred, n=300, seed=7)
    r3 = ev.bootstrap_ci(ev.accuracy, gold, pred, n=300, seed=8)
    assert r1 == r2 and r1 != r3
    point, lo, hi = r1
    assert point == ev.accuracy(gold, pred) and lo <= point <= hi and lo < hi
    # no variation means a degenerate interval
    assert ev.bootstrap_ci(ev.accuracy, [S] * 5, [S] * 5, n=50) == (1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        ev.bootstrap_ci(ev.accuracy, [S], [S, S])


def test_cluster_bootstrap():
    gold = [S, S, N, N, S, S, N, N]
    pred = [S, S, N, S, S, N, N, N]
    clusters = ["a", "a", "b", "b", "c", "c", "d", "d"]
    r1 = ev.cluster_bootstrap_ci(ev.accuracy, clusters, gold, pred, n=200, seed=1)
    assert r1 == ev.cluster_bootstrap_ci(ev.accuracy, clusters, gold, pred, n=200, seed=1)
    assert r1[0] == 0.75 and r1[1] <= 0.75 <= r1[2]
    # a single cluster cannot vary: the CI collapses to the point
    one = ev.cluster_bootstrap_ci(ev.accuracy, ["x"] * 4, [S, S, N, N], [S, N, N, N], n=50)
    assert one[1] == one[0] == one[2]


def test_ece_and_brier():
    conf = [3, 3, 3, 3, 1, 1]
    correct = [True, True, True, False, True, False]
    # level 3: acc 0.75 vs 0.95 -> 0.2 weighted 4/6; level 1: acc 0.5 vs 0.5 -> 0
    assert ev.ece_by_level(conf, correct) == pytest.approx(0.2 * 4 / 6)
    assert ev.ece_by_level([3, None], [True, None], missing="exclude") == pytest.approx(0.05)
    # missing correctness counts as wrong by default: bin 3 has acc 0.5
    assert ev.ece_by_level([3, 3], [True, None]) == pytest.approx(0.45)
    assert ev.ece_by_level([3, None], [True, None]) == pytest.approx(0.05)  # no confidence: skipped
    with pytest.raises(ValueError):
        ev.ece_by_level([3], [True], missing="x")
    assert math.isnan(ev.ece_by_level([None], [None]))
    probs = ev.prob_supported([3, 1, 2], [S, N, None])
    assert probs == [0.95, 0.5, None]
    assert ev.brier([0.95, 0.5], [True, False]) == pytest.approx((0.0025 + 0.25) / 2)
    assert ev.brier([0.9, None], [True, True]) == pytest.approx(0.01)
    custom = {1: 0.6, 2: 0.7, 3: 0.8}
    assert ev.prob_supported([2], [N], custom) == [pytest.approx(0.3)]


def test_mcnemar():
    a = [True] * 1 + [False] * 9 + [True] * 5
    b = [False] * 1 + [True] * 9 + [True] * 5
    # b = 1, c = 9 -> 2 * (1 + 10) / 1024
    assert ev.mcnemar_exact(a, b) == pytest.approx(22 / 1024)
    assert ev.mcnemar_exact(b, a) == pytest.approx(22 / 1024)
    assert ev.mcnemar_exact([True, False], [False, True]) == 1.0  # 1 vs 1, capped
    assert ev.mcnemar_exact([True, True], [True, True]) == 1.0  # no discordant pairs
    assert ev.mcnemar_exact([True, None], [False, True]) == pytest.approx(1.0)
    assert ev.mcnemar_exact([True, None], [False, True], missing="exclude") == 1.0
    # missing counted wrong creates a discordant pair: 0 vs 4 -> 2 / 16
    assert ev.mcnemar_exact([None] * 4, [True] * 4) == pytest.approx(2 / 16)
    assert ev.mcnemar_exact([None] * 4, [True] * 4, missing="exclude") == 1.0


def test_holm():
    assert ev.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert ev.holm([0.5, 0.9]) == [1.0, 1.0]
    assert ev.holm([0.4]) == [0.4]
    assert ev.holm([]) == []


def test_memory_reliance():
    r = ev.memory_reliance([S, S, P, N])
    assert r == {"n": 4, "supported": 0.5, "partially_supported": 0.25}
    r = ev.memory_reliance([S, None, N, N])
    assert r["n"] == 4 and r["supported"] == 0.25
    assert ev.memory_reliance([S, None, N, N], missing="exclude")["supported"] == pytest.approx(1 / 3)
    assert math.isnan(ev.memory_reliance([])["supported"])


@pytest.mark.parametrize("ptype", ev.HEDGE_TYPES)
def test_detected_hedge_family(ptype):
    assert not ev.detected(ptype, "supported", "matches")
    assert not ev.detected(ptype, "supported", None)
    assert not ev.detected(ptype, "supported", "understated")
    assert ev.detected(ptype, "supported", "overstated")
    for s in (P, N, C, X):
        assert ev.detected(ptype, s, "matches")


@pytest.mark.parametrize("ptype", ev.WRONG_TARGET_TYPES)
def test_detected_wrong_target_family(ptype):
    assert ev.detected(ptype, N, "matches") and ev.detected(ptype, C, None)
    for s in (S, P, X):
        assert not ev.detected(ptype, s, "overstated")


def test_detected_unknown_type():
    with pytest.raises(ValueError):
        ev.detected("certainty_inflated", S, None)


def test_detection_rates_and_false_positive():
    recs = [
        {"ptype": "negation", "support": C, "strength": None},
        {"ptype": "negation", "support": S, "strength": "matches"},
        {"ptype": "negation", "support": None, "strength": None},
        {"ptype": "hedge_dropped", "support": S, "strength": "overstated"},
    ]
    r = ev.detection_rates(recs)
    assert r["negation"] == {"n": 3, "missing": 1, "hits": 1, "rate": pytest.approx(1 / 3)}
    assert r["hedge_dropped"]["rate"] == 1.0
    assert ev.detection_rates(recs, missing="exclude")["negation"]["rate"] == 0.5
    fp = ev.false_positive_rate([
        {"support": S, "strength": "matches"},
        {"support": S, "strength": "overstated"},
        {"support": N, "strength": None},
        {"support": None, "strength": None},
    ])
    assert fp["n"] == 4 and fp["hits"] == 2 and fp["rate"] == 0.5
    assert ev.false_positive_rate([{"support": None}], missing="exclude")["n"] == 0


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_cli_end_to_end(tmp_path, capsys):
    gold = tmp_path / "gold.jsonl"
    pred = tmp_path / "pred.jsonl"
    _write(gold, [{"unit_id": f"u{i}", "annotator_id": "A1", "support": s}
                  for i, s in enumerate([S, S, N, N])])
    _write(pred, [
        # src: u0 right, u1 errored then retried (last row wins), u2 right, u3 absent (missing, D27)
        {"unit_id": "u0", "judge": "j1", "condition": "src", "support": S, "confidence": 3},
        {"unit_id": "u1", "judge": "j1", "condition": "src", "support": None},
        {"unit_id": "u1", "judge": "j1", "condition": "src", "support": S},
        {"unit_id": "u2", "judge": "j1", "condition": "src", "support": N},
        {"unit_id": "u2", "judge": "j1", "condition": "src", "run_index": 1, "support": S},  # repeat: not scored
        # nosrc: all four answered, one wrong
        {"unit_id": "u0", "judge": "j1", "condition": "nosrc", "support": N},
        {"unit_id": "u1", "judge": "j1", "condition": "nosrc", "support": S},
        {"unit_id": "u2", "judge": "j1", "condition": "nosrc", "support": N},
        {"unit_id": "u3", "judge": "j1", "condition": "nosrc", "support": N},
        {"unit_id": "zz", "judge": "j1", "condition": "src", "support": S},
    ])
    with pytest.raises(ValueError, match="use --by condition"):
        ev.main(["--gold", str(gold), "--pred", str(pred), "--n-boot", "50"])
    single = tmp_path / "single.jsonl"
    _write(single, [r for r in map(json.loads, pred.read_text().splitlines())
                    if r.get("condition") in ("src", None) or r["unit_id"] == "zz"])
    assert ev.main(["--gold", str(gold), "--pred", str(single), "--n-boot", "50"]) == 0
    out = capsys.readouterr().out
    assert "judge=j1" in out and "condition=" not in out
    assert "n=4 missing=1" in out
    assert "not_supported=" in out and "1 prediction rows" in out

    assert ev.main(["--gold", str(gold), "--pred", str(pred), "--by", "condition", "--n-boot", "50"]) == 0
    out2 = capsys.readouterr().out
    assert "condition=src" in out2 and "condition=nosrc" in out2
    assert "n=4 missing=1" in out2 and "n=4 missing=0" in out2
    assert "accuracy=0.750" in out2
    # deterministic
    ev.main(["--gold", str(gold), "--pred", str(pred), "--by", "condition", "--n-boot", "50"])
    assert capsys.readouterr().out == out2


def test_cli_duplicate_gold_rejected(tmp_path):
    gold = tmp_path / "g.jsonl"
    pred = tmp_path / "p.jsonl"
    _write(gold, [{"unit_id": "a", "support": S}, {"unit_id": "a", "support": N}])
    _write(pred, [{"unit_id": "a", "judge": "j", "support": S}])
    with pytest.raises(ValueError):
        ev.evaluate_files(str(gold), str(pred))
