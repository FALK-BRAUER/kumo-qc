"""Gap B — regime transition full cycle (open → block → exit-during-block → unblock → re-enter).

Exercises the three known bug surfaces across a complete blocked-bar regime cycle:
1. position_meta survives across blocked bars (not stale/corrupted)
2. Exit fires on a blocked bar (entry/exit asymmetry)
3. Clean re-entry after unblock (no double-entry, no corrupted state)

Ties directly to H4 (regime gating) and the #268 regime work.
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
# THE SCENARIO — five bars, ledger asserted across the whole sequence.
# ==========================================================================================


def test_e2e_regime_transition_full_cycle() -> None:
    """Full cycle: entry → block (hold) → exit-during-block → unblock → re-enter.

    Asserts the order ledger, position_meta state, and per-bar fired counters
    across a complete regime transition to catch the three bug surfaces:
    - stale position_meta across blocked bars
    - exit asymmetry (exit fires when entries are blocked)
    - double-entry or corrupted state after unblock
    """
    qc, winner, laggard = _make_qc()
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
    # BAR 2 — HOLD DURING BLOCK. SPY < MA200 (regime blocks entries).
    #   WINNER close=100 > Kijun=88 → no exit yet.
    #   position_meta must survive across this blocked bar (bug surface #1).
    # --------------------------------------------------------------------------------------
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)  # SPY 300 < MA200 400 → BLOCK entries
    # close stays at 100 (> Kijun 88), so no exit fires

    bar2 = _tick(engine, qc, datetime(2025, 1, 7))

    # position_meta survived the blocked bar — not stale, not corrupted.
    assert winner in qc._position_meta, "position_meta must survive across blocked bar"
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    # No new entries (blocked), no exits (close > Kijun).
    assert engine._fired_entries == 0
    assert engine._fired_exits == 0
    # Order ledger unchanged: still just the bar1 entry.
    assert len(qc.orders) == 1

    # --------------------------------------------------------------------------------------
    # BAR 3 — EXIT DURING BLOCK. SPY still < MA200 (still blocked).
    #   WINNER close drops below Kijun → exit fires (bug surface #2: asymmetry).
    #   Entries still suppressed; position_meta cleared on exit.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = KIJUN - 5.0  # 83 < 88 → Kijun-stop fires
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)  # still BLOCKED

    orders_before = len(qc.orders)
    bar3 = _tick(engine, qc, datetime(2025, 1, 8))

    # Exit intent produced for WINNER despite blocked bar.
    assert [(e.ticker, e.qty) for e in bar3.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    # FIRE_EXITS submitted the sell; no new buy (entries blocked).
    assert qc.orders[orders_before:] == [(winner, -expected_qty)]
    assert winner not in qc._position_meta, "position_meta must be cleared on exit"
    assert engine._fired_entries == 0  # entries still blocked
    assert engine._fired_exits == 1    # exit asymmetry: exit fires on blocked bar

    # Reflect the close in the portfolio (WINNER now flat).
    qc.portfolio[winner] = FakeHolding(invested=False, quantity=0)

    # --------------------------------------------------------------------------------------
    # BAR 4 — UNBLOCK AND RE-ENTER. SPY > MA200 (regime unblocks).
    #   WINNER flat, scores 8/8 again -> clean re-entry (bug surface #3).
    #   Must NOT double-enter; must set fresh position_meta.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = WINNER_PRICE  # reset close to healthy
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)  # SPY 500 > MA200 400 → UNBLOCKED

    orders_before = len(qc.orders)
    bar4 = _tick(engine, qc, datetime(2025, 1, 9))

    # Re-entry sized and fired exactly once (no double-entry).
    assert [o.ticker for o in bar4.bar_state.sized_orders] == ["WINNER"]
    assert qc.orders[orders_before:] == [(winner, expected_qty)]
    assert winner in qc._position_meta, "fresh position_meta after re-entry"
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    assert engine._fired_entries == 1  # re-entered cleanly
    assert engine._fired_exits == 0

    # --------------------------------------------------------------------------------------
    # FULL-SEQUENCE LEDGER — the complete order tape across all 5 bars.
    #   entry → hold(blocked) → exit(blocked) → re-entry(unblocked)
    #   Proves: lifecycle composed, regime transition handled correctly end-to-end.
    # --------------------------------------------------------------------------------------
    assert qc.orders == [
        (winner, expected_qty),     # bar1: ENTRY  WINNER  +1000
        (winner, -expected_qty),    # bar3: EXIT   WINNER  -1000 (during block)
        (winner, expected_qty),     # bar4: RE-ENTRY WINNER +1000 (after unblock)
    ]


# ==========================================================================================
# Supporting assertions — decompose each transition in isolation.
# ==========================================================================================


def test_e2e_position_meta_survives_blocked_bar() -> None:
    """position_meta is NOT stale after a blocked bar where the position is held."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2: blocked bar, no exit
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 7))

    # position_meta intact (not stale, not dropped)
    assert winner in qc._position_meta
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    # No new entry (blocked), no exit (close > Kijun)
    assert engine._fired_entries == 0
    assert engine._fired_exits == 0


def test_e2e_exit_fires_on_blocked_bar() -> None:
    """Exit asymmetry: exit phase fires when entries are blocked by regime."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2: blocked + exit
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)
    bar2 = _tick(engine, qc, datetime(2025, 1, 7))

    # Exit produced despite block; entry suppressed.
    assert [(e.ticker, e.qty) for e in bar2.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    assert engine._fired_entries == 0
    assert engine._fired_exits == 1


def test_e2e_no_double_entry_after_unblock() -> None:
    """After unblock, a flat symbol that re-enters does so exactly once."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2: exit during block
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 7))
    qc.portfolio[winner] = FakeHolding(invested=False, quantity=0)

    # bar3: unblock → re-enter
    qc.securities[winner].close = WINNER_PRICE
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    bar3 = _tick(engine, qc, datetime(2025, 1, 8))

    # Exactly one re-entry — no double-order, no duplicate position_meta.
    assert [o.ticker for o in bar3.bar_state.sized_orders] == ["WINNER"]
    # Verify the order list has exactly the three expected orders (no extras).
    assert qc.orders == [
        (winner, expected_qty),     # bar1
        (winner, -expected_qty),    # bar2
        (winner, expected_qty),     # bar3
    ]
    assert engine._fired_entries == 1  # only one entry this bar
    assert engine._fired_exits == 0


def test_e2e_reentry_resets_position_meta_cleanly() -> None:
    """Re-entry after unblock sets a fresh position_meta (not corrupted stale state)."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    expected_qty = 1000

    # bar1: entry
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 6))
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # bar2: exit during block
    qc.securities[winner].close = KIJUN - 5.0
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 7))
    qc.portfolio[winner] = FakeHolding(invested=False, quantity=0)

    # bar3: unblock → re-enter
    qc.securities[winner].close = WINNER_PRICE
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)
    _tick(engine, qc, datetime(2025, 1, 8))

    # Fresh position_meta with correct entry price (not stale/corrupted).
    assert winner in qc._position_meta
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    # No residual stale keys
    assert "exit_date" not in qc._position_meta[winner]


