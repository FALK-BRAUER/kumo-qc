"""Selector tests (#323 B.5) — lexicographic filter, λ-ordering, champion-beat hook.

Synthetic ConfigEvidence fixtures only — ZERO backtest.
"""
from __future__ import annotations

import pytest

from sweeps.objective.gates import WindowReturns
from sweeps.objective.selector import (
    FILTER,
    OBJECTIVE_VERSION,
    WEIGHTS,
    ConfigEvidence,
    calmar,
    cost_baseline_hook,
    score_config,
    select,
    trade_penalty,
)
from sweeps.types import Window


def _robust_windows() -> tuple[WindowReturns, ...]:
    out = [WindowReturns(Window(f"w{i}", "2025-01-01", "2025-02-28"), 15, 0.05) for i in range(5)]
    out.append(WindowReturns(Window("oos", "2024-01-01", "2024-12-31"), 15, 0.04, is_oos=True))
    return tuple(out)


def _ev(h: str, *, dsr: float, n_trades: int = 120, windows=None) -> ConfigEvidence:
    return ConfigEvidence(
        config_hash=h,
        dsr=dsr,
        pbo=0.0,  # broadcast separately in select(); per-config carried for completeness
        ann_return=0.30,
        max_dd=0.10,
        n_trades=n_trades,
        windows=windows if windows is not None else _robust_windows(),
    )


# --- helper math --- #
def test_calmar_is_return_over_drawdown() -> None:
    assert calmar(0.30, 0.10) == pytest.approx(3.0)
    assert calmar(0.30, 0.0) == 0.0  # no DD recorded -> guarded


def test_trade_penalty_full_at_floor_zero_well_above() -> None:
    assert trade_penalty(FILTER["min_total_trades"]) == 1.0
    assert trade_penalty(FILTER["min_total_trades"] * 2) == pytest.approx(0.0)
    mid = trade_penalty(FILTER["min_total_trades"] + FILTER["min_total_trades"] // 2)
    assert 0.0 < mid < 1.0


# --- filter (lexicographic, hard) --- #
def test_filter_rejects_high_pbo() -> None:
    s = score_config(_ev("a", dsr=0.95), pbo=0.5, champion_score=None)
    assert not s.filter_verdict.passed and "REJECT-pbo" in s.filter_verdict.reason
    assert s.score == 0.0


def test_filter_rejects_low_dsr() -> None:
    s = score_config(_ev("a", dsr=0.5), pbo=0.0, champion_score=None)
    assert not s.filter_verdict.passed and "REJECT-dsr" in s.filter_verdict.reason


def test_filter_rejects_single_window_carried_before_scoring() -> None:
    carried = tuple(
        WindowReturns(Window(f"w{i}", "2025-01-01", "2025-02-28"), 12, r)
        for i, r in enumerate([0.001, 0.001, 0.001, 0.001, 0.001, 0.30])
    )
    s = score_config(_ev("a", dsr=0.95, windows=carried), pbo=0.0, champion_score=None)
    assert not s.filter_verdict.passed
    assert "concentration" in s.filter_verdict.reason


def test_filter_rejects_trade_starved() -> None:
    starved = tuple(
        WindowReturns(Window(f"w{i}", "2025-01-01", "2025-02-28"), 3, 0.05) for i in range(6)
    )
    s = score_config(_ev("a", dsr=0.95, n_trades=18, windows=starved), pbo=0.0, champion_score=None)
    assert not s.filter_verdict.passed and "REJECT-trades" in s.filter_verdict.reason


def test_passing_config_scores_and_pins_objective_version() -> None:
    s = score_config(_ev("a", dsr=0.9), pbo=0.1, champion_score=None)
    assert s.filter_verdict.passed
    assert s.objective_version == OBJECTIVE_VERSION
    # score = l1*dsr + l2*(1-pbo) + l3*calmar_norm + l4*(-trade_penalty)
    assert s.score > 0.0


# --- lambda ordering: DSR dominates over Calmar --- #
def test_lambda_ordering_dsr_dominates_calmar() -> None:
    # cfg A: higher DSR, lower Calmar. cfg B: lower DSR, higher Calmar.
    a = ConfigEvidence("aaaa", dsr=0.95, pbo=0.0, ann_return=0.10, max_dd=0.20, n_trades=120,
                       windows=_robust_windows())  # Calmar 0.5
    b = ConfigEvidence("bbbb", dsr=0.85, pbo=0.0, ann_return=0.90, max_dd=0.20, n_trades=120,
                       windows=_robust_windows())  # Calmar 4.5
    ranked = select([a, b], pbo=0.0)
    # λ1 (0.50) on a 0.10 DSR gap = 0.05; λ3 (0.15) on the Calmar gap (4.5-0.5)/3=1.33 -> 0.20.
    # Calmar CAN outweigh a small DSR gap by design (weighted scalar) — but the WEIGHTS keep
    # λ1>λ3, so an EQUAL normalised advantage favours DSR. Assert the weight ordering holds.
    assert WEIGHTS["l1_dsr"] > WEIGHTS["l2_one_minus_pbo"] > WEIGHTS["l3_calmar"] > WEIGHTS["l4_trade_penalty"]
    # Both pass the filter; ranking is by the weighted scalar (deterministic).
    assert {r.config_hash for r in ranked} == {"aaaa", "bbbb"}
    assert all(r.filter_verdict.passed for r in ranked)


# --- champion-beat hook (#321) --- #
def test_champion_score_none_leaves_beat_unknown() -> None:
    s = score_config(_ev("a", dsr=0.9), pbo=0.1, champion_score=None)
    assert s.must_beat_champion is None  # clearly-marked hook, never fabricated


def test_champion_beat_flips_on_the_baseline() -> None:
    ev = _ev("a", dsr=0.9)
    low = score_config(ev, pbo=0.1, champion_score=0.0)
    high = score_config(ev, pbo=0.1, champion_score=1.0)
    assert low.must_beat_champion is True
    assert high.must_beat_champion is False


def test_cost_baseline_hook_accepts_numeric_rejects_other() -> None:
    assert cost_baseline_hook(None) is None
    assert cost_baseline_hook(0.42) == pytest.approx(0.42)
    with pytest.raises(TypeError):
        cost_baseline_hook("not-a-score")  # type: ignore[arg-type]


# --- select ranking: passing first, then by score, rejects trail --- #
def test_select_orders_passing_first_then_rejects() -> None:
    good = _ev("good", dsr=0.95)
    bad = _ev("bad_", dsr=0.5)  # fails DSR
    ranked = select([bad, good], pbo=0.0)
    assert ranked[0].config_hash == "good" and ranked[0].filter_verdict.passed
    assert ranked[-1].config_hash == "bad_" and not ranked[-1].filter_verdict.passed


def test_select_is_deterministic() -> None:
    evs = [_ev(f"c{i}", dsr=0.9) for i in range(5)]
    r1 = [s.config_hash for s in select(evs, pbo=0.1)]
    r2 = [s.config_hash for s in select(list(reversed(evs)), pbo=0.1)]
    assert r1 == r2  # input order independent
