"""#352 L1 runner tests — the bear-composite OOS-ranking wiring.

Covers the runner contract that the primitive tests (test_regime_composite.py) don't:
the bear feature set, the OOS quarter split, the RE-RANK-NOT-REJECT property (the grade scores
ALL held-out rows, never filters/vetoes), OOS ranking when signal is present, and fail-loud on a
degenerate fit. The no-leakage guarantee itself lives in test_regime_composite.py (frozen fit).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

import run_352_composite as r352  # noqa: E402

_FEATS = r352.BEAR_FEATURES


def _row(tk: str, label: float, vals: dict[str, float | None]) -> dict:
    return {"ticker": tk, "label": label, "feats": dict(vals)}


def _signal_quarter(tag: str, n: int = 25) -> list[dict]:
    """n rows where every bear feature increases with i and the FY-label tracks it → a clean monotone
    relationship, so a composite fit on one such quarter should rank a same-shaped quarter OOS."""
    rows = []
    for i in range(n):
        v = float(i)
        rows.append(_row(f"{tag}{i}", label=v / 10.0, vals={f: v + 0.1 * j for j, f in enumerate(_FEATS)}))
    return rows


def _perq_signal() -> dict[str, list[dict]]:
    return {q: _signal_quarter(q) for q in ("Q1", "Q2", "Q3", "Q4")}


def test_bear_features_are_falks_three() -> None:
    assert r352.BEAR_FEATURES == ["dist_ath", "dist_to_prior_high", "continuous_growth"]


def test_l1_oos_ranks_winners_above_losers_out_of_sample() -> None:
    res = r352.l1_oos(_perq_signal())
    # held-out bear grades exist and rank positively (Spearman>0, AUC>0.5) on the monotone signal
    for key in ("bear_Q1_to_Q4", "bear_Q4_to_Q1"):
        assert res[key]["spearman"] is not None and res[key]["spearman"] > 0.0, key
        assert res[key]["auc"] is not None and res[key]["auc"] > 0.5, key


def test_l1_is_rerank_not_reject_scores_every_test_row() -> None:
    """RE-RANK, NOT VETO: the held-out grade must score ALL test rows that have features — it never
    drops/filters a candidate (the critical distinction from the rejected #342 index gate)."""
    perq = _perq_signal()
    res = r352.l1_oos(perq)
    assert res["bear_Q1_to_Q4"]["n_test"] == len(perq["Q4"])  # every Q4 row scored, none vetoed
    assert res["bear_Q4_to_Q1"]["n_test"] == len(perq["Q1"])


def test_l1_oos_fail_loud_on_degenerate_fit() -> None:
    """A constant feature in the fit quarter can't be z-scored → fit_composite must raise, not impute."""
    perq = _perq_signal()
    for r in perq["Q1"]:
        r["feats"]["dist_ath"] = 5.0  # constant → zero variance
    with pytest.raises(ValueError, match="constant"):
        r352.l1_oos(perq)


def test_l1_oos_computes_bull_no_harm_grades() -> None:
    res = r352.l1_oos(_perq_signal())
    assert "bull_to_Q2" in res and "bull_to_Q3" in res
    assert res["bull_to_Q2"]["n_test"] > 0
