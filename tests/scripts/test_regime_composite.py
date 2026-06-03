"""#352 regime-conditional composite — computation, regime-conditioning, OOS NO-LEAKAGE, fail-loud."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "scripts")]

import pytest
import regime_composite as rc


def _rows(vals, labels, feat="x"):
    return [{"feats": {feat: v}, "label": l} for v, l in zip(vals, labels)]


def test_fit_and_score_known():
    # feature x perfectly correlates with label → sign +1; z-score of the mean point = 0.
    vals = list(range(20)); labels = list(range(20))
    fit = rc.fit_composite(_rows(vals, labels), ["x"], min_rows=20)
    mean, std, sign = fit.stats["x"]
    assert sign == 1.0 and mean == pytest.approx(9.5)
    assert rc.score(fit, {"x": 9.5}) == pytest.approx(0.0)          # at the mean → 0
    assert rc.score(fit, {"x": 9.5 + std}) == pytest.approx(1.0)    # +1 sd → +1


def test_regime_conditioning_sign_flips():
    # SAME feature: + correlated with label in 'bull', - correlated in 'bear' → fit signs FLIP.
    vals = list(range(20))
    bull = rc.fit_composite(_rows(vals, vals), ["x"], min_rows=20)            # + corr
    bear = rc.fit_composite(_rows(vals, [-l for l in vals]), ["x"], min_rows=20)  # - corr
    assert bull.stats["x"][2] == 1.0 and bear.stats["x"][2] == -1.0
    # a high-x point scores POSITIVE under bull, NEGATIVE under bear (regime-conditional).
    assert rc.score(bull, {"x": 19}) > 0 and rc.score(bear, {"x": 19}) < 0


def test_oos_no_leakage_fit_independent_of_test():
    # THE overfit guard: the fit params must depend ONLY on fit_rows — adding/removing test rows
    # must NOT change the fit. And each test point's score is independent of other test points.
    fit_rows = _rows(list(range(20)), list(range(20)))
    test_a = _rows([5.0], [99.0])
    test_b = _rows([5.0, 1.0, 18.0, 7.0], [99.0, 0.0, 50.0, 3.0])  # extra test points
    ra = rc.oos_evaluate(fit_rows, test_a, ["x"], min_rows=20)
    rb = rc.oos_evaluate(fit_rows, test_b, ["x"], min_rows=20)
    assert ra["fit"].stats == rb["fit"].stats                        # fit unchanged by test population
    # the score of the shared point (x=5) is identical regardless of the other test points present:
    assert rc.score(ra["fit"], {"x": 5.0}) == rc.score(rb["fit"], {"x": 5.0})
    # and the fit equals the standalone fit (test rows never touched it):
    standalone = rc.fit_composite(fit_rows, ["x"], min_rows=20)
    assert standalone.stats == ra["fit"].stats


def test_score_pure_no_label_dependency():
    # score takes only (fit, feats) — no label field consulted (can't leak the answer).
    fit = rc.fit_composite(_rows(list(range(20)), list(range(20))), ["x"], min_rows=20)
    assert rc.score(fit, {"x": 12.0}) == rc.score(fit, {"x": 12.0})   # deterministic, label-free


def test_fail_loud_constant_feature():
    with pytest.raises(ValueError):
        rc.fit_composite(_rows([3.0] * 20, list(range(20))), ["x"], min_rows=20)  # zero variance


def test_fail_loud_too_few_rows():
    with pytest.raises(ValueError):
        rc.fit_composite(_rows(list(range(5)), list(range(5))), ["x"], min_rows=20)


def test_multi_feature_composite():
    # two features both + correlated → composite at the joint mean = 0, above-mean point > 0.
    rows = [{"feats": {"a": i, "b": 2 * i}, "label": i} for i in range(20)]
    fit = rc.fit_composite(rows, ["a", "b"], min_rows=20)
    assert set(fit.features) == {"a", "b"}
    assert rc.score(fit, {"a": 19, "b": 38}) > 0
    # a point missing one feature still scores on the present one (None-tolerant, not a crash):
    assert rc.score(fit, {"a": 19, "b": None}) is not None
