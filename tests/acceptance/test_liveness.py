"""#244-D — the per-PR SDLC LIVENESS GATE (fast: pytest, NO docker/BT).

This is the per-PR regression catch for a SILENT stop-trading regression. It does NOT run a
full-FY backtest (that is the PERIODIC band check — see the runbook in
docs/ACCEPTANCE_CONTRACT.md). Instead it drives the REAL champion_asis CONFIG through the REAL
StrategyEngine on the #247 FakeQC harness and asserts the gate criterion:

    LIVENESS  : the real champion config, on a triggering bar, FIRES at least one order
                (orders > 0). If a future change silently breaks entry wiring, this fails.
    0-TRADES  : a deliberately-non-firing config (champion with an IMPOSSIBLE signal
      GUARD     threshold, min_score=99 > the 8 max BCT score) drives the SAME harness,
                produces ZERO orders, AND `assert_liveness` FAILS on it. This PROVES the gate
                actually CATCHES a dead config — without the guard, an `orders > 0` assertion
                could pass for the wrong reason (e.g. a harness that always injects an order)
                and never fail on a real regression.

Both arms exercise the SAME `assert_liveness(orders)` gate function, so the guard literally
demonstrates the check that protects the champion is the check that rejects a dead config.

REUSES the #247 FakeQC harness (tests/integration/fake_qc.py) — no new harness, no docker, no
BT. The triggering scenario is the #247 ENTRY bar (WINNER scores 8/8, regime OK → one buy).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from engine.config import Slot, StrategyConfig
from engine.context import PhaseContext
from engine.engine import StrategyEngine
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from strategies.champion_asis import CONFIG as CHAMPION_CONFIG

from scripts.check_liveness_band import (
    BASELINE_ORDERS,
    BASELINE_ROUND_TRIPS,
    ORDERS_FLOOR,
    check_band,
)
from tests.integration.stub_entry import with_entry_seam
from tests.integration.fake_qc import (
    FakeQC,
    FakeSecurity,
    FakeSymbol,
    _Ind,
    all_pass_indicators,
)

# Re-use the #247 entry-bar reference prices (all_pass set scores 8/8 at price 100).
WINNER_PRICE = 100.0

# An impossible BCT signal threshold: the 8-condition scorer maxes at 8, so a min_score of 99
# can NEVER be met → the signal phase keeps zero candidates → zero entries. This is the
# canonical "silent regression to 0 trades" a real bug would produce (e.g. a broken signal).
IMPOSSIBLE_MIN_SCORE = 99


# ---------------------------------------------------------------------------------------------
# THE GATE — one shared function. The champion PASSES it; the dead config FAILS it.
# ---------------------------------------------------------------------------------------------


class LivenessError(AssertionError):
    """Raised by assert_liveness when a config fires zero orders (the dead-config signal)."""


def assert_liveness(order_count: int) -> None:
    """The per-PR liveness gate criterion: a live strategy MUST fire at least one order.

    order_count == 0 is the silent stop-trading regression this gate exists to catch. The
    champion drives a positive count through here (passes); the deliberately-dead config drives
    0 through here (raises) — proving the gate catches a dead config, not just that the champion
    happens to trade.
    """
    if order_count <= 0:
        raise LivenessError(
            f"LIVENESS GATE FAILED: strategy fired {order_count} orders — expected > 0. "
            "This is a silent stop-trading regression (the engine entry path produced no "
            "trades on a known-triggering bar)."
        )


# ---------------------------------------------------------------------------------------------
# Harness driver — the #247 ENTRY scenario, reduced to the single triggering bar.
# ---------------------------------------------------------------------------------------------


def _spy(qc: FakeQC, *, price: float, ma200: float) -> None:
    spy = FakeSymbol("SPY")
    qc.spy = spy
    qc.securities[spy] = FakeSecurity(price)
    qc.spy_sma200 = _Ind(ma200, ready=True)


def _entry_bar_qc() -> FakeQC:
    """A FakeQC primed on the #247 ENTRY bar: WINNER scores 8/8, regime OK → should buy."""
    qc = FakeQC(cash=1_000_000.0, total_value=1_000_000.0)
    qc.add_security("WINNER", WINNER_PRICE, all_pass_indicators())
    qc._trailing_dv = {"winner": 5_000_000.0}
    qc._ranked_today = ["WINNER"]
    _spy(qc, price=500.0, ma200=400.0)  # SPY above MA200 → regime passes
    return qc


def _run_one_entry_bar(config: StrategyConfig) -> int:
    """Drive `config` through StrategyEngine on the single triggering bar; return orders fired."""
    qc = _entry_bar_qc()
    # #386: champion_asis is the retired blind-MOO fixture — fire through an EXPLICIT stub entry seam
    # (post-MOO-delete there is no implicit default). The liveness gate is unchanged: the champion
    # drives a positive count, the dead-signal config still fires zero (no winner to stamp).
    engine = StrategyEngine(config=with_entry_seam(config), qc=qc)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 6), data=None)
    engine.on_data_with_ctx(ctx)
    return len(qc.orders)


def _dead_config() -> StrategyConfig:
    """The champion config with ONLY the signal threshold made impossible (min_score=99).

    Everything else is the real champion — universe, regime, sizing, exits, diagnostics — so the
    ONLY reason it fires zero orders is the signal never selecting a candidate. This isolates the
    0-trades cause to a single, realistic regression (a broken / over-strict signal), proving the
    gate catches it rather than catching some unrelated harness artifact.
    """
    dead_signal: Slot[object] = Slot(
        impl=BctScoreFull,
        params=BctScoreFull.Params(min_score=IMPOSSIBLE_MIN_SCORE, parabolic_threshold=0.25),
    )
    phases = dict(CHAMPION_CONFIG.phases)
    phases["signal"] = dead_signal
    return dataclasses.replace(
        CHAMPION_CONFIG,
        name=f"{CHAMPION_CONFIG.name}-dead-signal",
        phases=phases,
    )


# ---------------------------------------------------------------------------------------------
# LIVENESS — the real champion fires > 0 orders and PASSES the gate.
# ---------------------------------------------------------------------------------------------


def test_champion_config_fires_orders() -> None:
    """LIVENESS: the REAL champion_asis CONFIG, driven on a triggering bar, fires orders > 0."""
    orders = _run_one_entry_bar(CHAMPION_CONFIG)
    assert orders > 0, "champion config must fire at least one order on a triggering bar"
    # The same gate function the dead-config arm uses — champion passes it (no raise).
    assert_liveness(orders)


# ---------------------------------------------------------------------------------------------
# 0-TRADES GUARD — a dead config fires ZERO orders AND the gate FAILS on it.
# ---------------------------------------------------------------------------------------------


def test_champion_entry_config_fires_orders() -> None:
    """LIVENESS (#253): champion_entry (champion-asis + the §4 Gate-2 entry-confirm gate) STILL
    fires orders > 0 on the triggering bar. The entry-confirm gate makes entries FEWER (it gates
    on confirmation) but NOT zero — the liveness floor still passes. The WINNER all_pass set
    confirms C1 regime + C3 MACD + C4 volume (3/4, regime+volume mandatory) → qualifies → fires.
    """
    from strategies.champion_entry import CONFIG as CHAMPION_ENTRY_CONFIG

    orders = _run_one_entry_bar(CHAMPION_ENTRY_CONFIG)
    assert orders > 0, "champion_entry must still fire >0 orders (entry-confirm gates, not kills)"
    assert_liveness(orders)


def test_dead_config_fires_zero_orders() -> None:
    """The impossible-threshold config produces ZERO orders (the silent-regression condition)."""
    orders = _run_one_entry_bar(_dead_config())
    assert orders == 0, "dead config (min_score=99) must fire zero orders"


def test_liveness_gate_catches_dead_config() -> None:
    """THE LOAD-BEARING GUARD: the SAME assert_liveness gate that passes the champion must FAIL
    on the dead config. This proves the gate would catch a silent regression to 0 trades."""
    orders = _run_one_entry_bar(_dead_config())
    with pytest.raises(LivenessError):
        assert_liveness(orders)


def test_assert_liveness_gate_logic() -> None:
    """Unit-level proof of the shared gate function in isolation: > 0 passes, <= 0 raises."""
    assert_liveness(1)
    assert_liveness(75)  # the recorded full-FY baseline order count
    with pytest.raises(LivenessError):
        assert_liveness(0)
    with pytest.raises(LivenessError):
        assert_liveness(-1)


# ---------------------------------------------------------------------------------------------
# PERIODIC band check — the full-FY anti-collapse logic (scripts/check_liveness_band.py).
# This logic does NOT run a BT here; it is unit-tested on dummy result numbers so the PERIODIC
# helper is itself covered. The full-FY BT that feeds it is the documented runbook, NOT per-PR.
# ---------------------------------------------------------------------------------------------


def test_periodic_band_baseline_passes() -> None:
    """The recorded baseline (75 orders / 32 round-trips) is within band → PASS."""
    passed, _msgs = check_band(BASELINE_ORDERS, BASELINE_ROUND_TRIPS)
    assert passed is True


def test_periodic_band_zero_orders_fails() -> None:
    """Zero orders (the silent stop-trading regression) → FAIL (anti-0 trip)."""
    passed, _msgs = check_band(0, 0)
    assert passed is False


def test_periodic_band_turnover_collapse_fails() -> None:
    """Orders below 50% of baseline (< 37) → FAIL (turnover collapse), NOT a hard ==75 pin."""
    passed, _msgs = check_band(20, 8)
    assert passed is False
    # A drop to just-below-floor still trips; just-above-floor does not (band, not hard pin).
    assert check_band(ORDERS_FLOOR - 1, BASELINE_ROUND_TRIPS)[0] is False
    assert check_band(BASELINE_ORDERS - 1, BASELINE_ROUND_TRIPS)[0] is True


def test_periodic_band_missing_orders_fails() -> None:
    """A result JSON missing the order count → FAIL (can't prove liveness)."""
    passed, _msgs = check_band(None, None)
    assert passed is False
