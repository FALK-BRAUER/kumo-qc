"""Gap A — multi-bar hold → exit on Kijun breach (not immediate).

Exercises the H3/EXP-2 Kijun-trail behavior at the engine level:
- Position opens on entry bar
- Holds for 3+ bars while close stays above Kijun (NO premature exit)
- Exits only when close finally breaches Kijun

This tests the engine's patience — that the exit phase does NOT fire
on every bar, only when the stop condition is actually met.
"""
from __future__ import annotations

from datetime import datetime

from engine.context import PhaseContext
from engine.engine import StrategyEngine
from strategies.champion_asis import CONFIG

from tests.integration.fake_qc import (
    FakeHolding,
    FakeQC,
    FakeSecurity,
    FakeSymbol,
    _Ind,
    all_pass_indicators,
    below_sma200_indicators,
)

# Reference prices chosen so the all_pass indicator set scores 8/8 at WINNER_PRICE=100
# (sma200=50, daily cloud-top=85, etc. — see all_pass_indicators docstring).
WINNER_PRICE = 100.0
KIJUN = 88.0  # daily kijun in the all_pass set; close < KIJUN triggers the exit-phase stop


def _spy(qc: FakeQC, *, price: float, ma200: float, ready: bool = True) -> None:
    """Wire the SPY regime inputs spy_200ma reads: qc.spy, qc.spy_sma200, securities[spy].
    SPY is its own Symbol-like; it is NOT in _ranked_today so it is never a trade candidate."""
    spy = FakeSymbol("SPY")
    qc.spy = spy
    qc.securities[spy] = FakeSecurity(price)
    qc.spy_sma200 = _Ind(ma200, ready=ready)


def _make_qc() -> tuple[FakeQC, FakeSymbol, FakeSymbol]:
    """Two equities: WINNER (scores 8/8) and LAGGARD (pre-filtered out, below SMA200)."""
    qc = FakeQC(cash=1_000_000.0, total_value=1_000_000.0)
    winner = qc.add_security("WINNER", WINNER_PRICE, all_pass_indicators())
    laggard = qc.add_security("LAGGARD", WINNER_PRICE, below_sma200_indicators())
    qc._trailing_dv = {"winner": 5_000_000.0, "laggard": 4_000_000.0}
    return qc, winner, laggard


def _ctx(qc: FakeQC, when: datetime) -> PhaseContext:
    return PhaseContext(qc=qc, time=when, data=None)


def _tick(engine: StrategyEngine, qc: FakeQC, when: datetime) -> PhaseContext:
    ctx = _ctx(qc, when)
    engine.on_data_with_ctx(ctx)
    return ctx


# ==========================================================================================
# THE SCENARIO — six bars, ledger asserted across the whole sequence.
# ==========================================================================================


def test_e2e_multi_bar_hold_then_exit_on_kijun_breach() -> None:
    """Full cycle: entry → hold 3 bars (close > Kijun, no exit) → exit on Kijun breach.

    Asserts the order ledger and position state across a multi-bar hold:
    - entry fires on bar1
    - NO exit orders during bars 2-4 (close stays above Kijun)
    - exit fires on bar5 (close drops below Kijun)
    - position_meta cleared on exit
    """
    qc, winner, _laggard = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # --------------------------------------------------------------------------------------
    # BAR 0 — WARMUP. Empty ranked set → clean tick, no trades.
    # --------------------------------------------------------------------------------------
    qc._ranked_today = []
    _spy(qc, price=500.0, ma200=400.0, ready=False)
    bar0 = _tick(engine, qc, datetime(2025, 1, 3))
    assert bar0.bar_state.ranked_candidates == []
    assert qc.orders == []
    assert engine._fired_entries == 0
    assert engine._fired_exits == 0

    # --------------------------------------------------------------------------------------
    # BAR 1 — ENTRY. WINNER scores 8/8, regime OK (SPY > MA200).
    #   -> sizing sizes WINNER -> FIRE_ENTRIES submits buy -> position_meta recorded.
    # --------------------------------------------------------------------------------------
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    bar1 = _tick(engine, qc, datetime(2025, 1, 6))

    assert [o.ticker for o in bar1.bar_state.sized_orders] == ["WINNER"]
    assert qc.orders == [(winner, expected_qty)]
    assert winner in qc._position_meta
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    assert engine._fired_entries == 1
    assert engine._fired_exits == 0

    # Reflect the fill in the portfolio (harness bookkeeping).
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # --------------------------------------------------------------------------------------
    # BAR 2 — HOLD. Close = 90 (> Kijun 88). No exit should fire.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = 90.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)

    orders_before = len(qc.orders)
    bar2 = _tick(engine, qc, datetime(2025, 1, 7))

    assert winner in qc._position_meta, "position_meta must survive hold bar"
    assert engine._fired_exits == 0, "NO exit should fire while close > Kijun"
    assert len(qc.orders) == orders_before, "NO new orders during hold"
    # position still open
    assert qc.portfolio[winner].quantity == expected_qty

    # --------------------------------------------------------------------------------------
    # BAR 3 — HOLD. Close = 92 (> Kijun 88). Still no exit.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = 92.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)

    orders_before = len(qc.orders)
    bar3 = _tick(engine, qc, datetime(2025, 1, 8))

    assert winner in qc._position_meta
    assert engine._fired_exits == 0, "NO exit should fire while close > Kijun"
    assert len(qc.orders) == orders_before, "NO new orders during hold"
    assert qc.portfolio[winner].quantity == expected_qty

    # --------------------------------------------------------------------------------------
    # BAR 4 — HOLD. Close = 95 (> Kijun 88). Still no exit.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = 95.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)

    orders_before = len(qc.orders)
    bar4 = _tick(engine, qc, datetime(2025, 1, 9))

    assert winner in qc._position_meta
    assert engine._fired_exits == 0, "NO exit should fire while close > Kijun"
    assert len(qc.orders) == orders_before, "NO new orders during hold"
    assert qc.portfolio[winner].quantity == expected_qty

    # --------------------------------------------------------------------------------------
    # BAR 5 — EXIT. Close = 83 (< Kijun 88). Kijun-stop fires.
    #   -> exit phase emits intent -> FIRE_EXITS submits sell.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = KIJUN - 5.0  # 83 < 88 → Kijun-stop fires
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)

    orders_before = len(qc.orders)
    bar5 = _tick(engine, qc, datetime(2025, 1, 10))

    # Exit intent produced for WINNER.
    assert [(e.ticker, e.qty) for e in bar5.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    # FIRE_EXITS submitted the sell.
    assert qc.orders[orders_before:] == [(winner, -expected_qty)]
    assert winner not in qc._position_meta, "position_meta must be cleared on exit"
    assert engine._fired_entries == 0  # no new entry
    assert engine._fired_exits == 1    # exit fired

    # Reflect the close in the portfolio (WINNER now flat).
    qc.portfolio[winner] = FakeHolding(invested=False, quantity=0)

    # --------------------------------------------------------------------------------------
    # FULL-SEQUENCE LEDGER — the complete order tape across all 6 bars.
    #   entry → hold → hold → hold → exit
    #   Only TWO orders: the entry and the exit. No premature exits during hold.
    # --------------------------------------------------------------------------------------
    assert qc.orders == [
        (winner, expected_qty),     # bar1: ENTRY  WINNER  +1000
        (winner, -expected_qty),    # bar5: EXIT   WINNER  -1000
    ], "must be exactly 2 orders: entry + exit, no premature exits during hold"


# ==========================================================================================
# Supporting assertions — decompose each transition in isolation.
# ==========================================================================================


def test_e2e_no_premature_exit_when_close_above_kijun() -> None:
    """Position holds for multiple bars without exiting while close stays above Kijun."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2-4: hold (3 bars, close above Kijun)
    for day, close_price in enumerate([90.0, 92.0, 95.0], start=7):
        qc.securities[winner].close = close_price
        qc._ranked_today = ["WINNER", "LAGGARD"]
        _spy(qc, price=500.0, ma200=400.0)
        bar = _tick(engine, qc, datetime(2025, 1, day))

        # No exit intents, no exit orders, position_meta survives.
        assert bar.bar_state.exit_intents == [], f"no exit intent on day {day} (close={close_price} > Kijun={KIJUN})"
        assert engine._fired_exits == 0, f"no exit fired on day {day}"
        assert winner in qc._position_meta, f"position_meta survives day {day}"
        assert qc.portfolio[winner].quantity == expected_qty

    # bar5: close below Kijun → exit fires
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    bar5 = _tick(engine, qc, datetime(2025, 1, 10))

    assert [(e.ticker, e.qty) for e in bar5.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    assert engine._fired_exits == 1
    assert winner not in qc._position_meta


def test_e2e_exit_fires_immediately_on_kijun_breach() -> None:
    """Exit fires on the FIRST bar where close drops below Kijun (no delay)."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2: hold (close above Kijun)
    qc.securities[winner].close = 90.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    bar2 = _tick(engine, qc, datetime(2025, 1, 7))

    assert bar2.bar_state.exit_intents == [], "no exit on hold bar"
    assert engine._fired_exits == 0

    # bar3: Kijun breach → exit fires immediately (same bar)
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    bar3 = _tick(engine, qc, datetime(2025, 1, 8))

    assert [(e.ticker, e.qty) for e in bar3.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    assert engine._fired_exits == 1
    assert winner not in qc._position_meta


def test_e2e_position_unchanged_during_hold() -> None:
    """Position quantity and position_meta remain stable during the hold period."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    initial_meta = qc._position_meta[winner].copy()

    # bar2-3: hold (2 bars)
    for day, close_price in enumerate([90.0, 92.0], start=7):
        qc.securities[winner].close = close_price
        qc._ranked_today = ["WINNER", "LAGGARD"]
        _spy(qc, price=500.0, ma200=400.0)
        _tick(engine, qc, datetime(2025, 1, day))

        # Position state completely unchanged during hold.
        assert qc.portfolio[winner].quantity == expected_qty
        assert qc._position_meta[winner] == initial_meta, \
            f"position_meta must be stable during hold, changed on day {day}"
        assert engine._fired_exits == 0
        assert len(qc.orders) == 1  # only the original entry order

    # bar4: Kijun breach → exit
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 9))

    assert qc.portfolio[winner].quantity == expected_qty  # still reported as entry qty until harness updates
    assert winner not in qc._position_meta  # but meta cleared by engine
    assert engine._fired_exits == 1
    assert len(qc.orders) == 2  # entry + exit
