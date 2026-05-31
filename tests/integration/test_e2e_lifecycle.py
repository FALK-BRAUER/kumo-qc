"""#247 — E2E integration lifecycle scenario.

Drives the REAL champion_asis.CONFIG through StrategyEngine.on_data_with_ctx on a realistic
FakeQC across the EXISTING lifecycle and asserts the order/position LEDGER flows end-to-end:

    warmup -> universe (dv_rank_cap) -> signal (bct_score_full)
      -> regime (spy_200ma, vix_percentile) -> [ENTRY SEAM #228] -> sizing (flat_pct_heatcap)
      -> FIRE_ENTRIES -> exit (kijun_g3_exits) -> FIRE_EXITS -> diagnostics

This is distinct from the per-phase unit tests (which exercise each phase in isolation) and
from the engine unit tests (which drive STUB phases). Here the REAL phases compose, on the
real CONFIG, and we assert the cross-bar LEDGER — proof the lifecycle actually flows.

==========================================================================================
ENTRY-PHASE INSERTION SEAM (#228, parked — HQ forward-compat ruling)
==========================================================================================
The parked ENTRY phase slots in CLEANLY between SIGNAL and SIZING:
    warmup -> universe -> signal -> ENTRY -> sizing -> stop -> exit
The engine already reserves that seam: PHASE_ORDER lists "entry_selection"/"entry_timing"
immediately after "ranking" and before "sizing" (src/engine/engine.py PHASE_ORDER), and both
are ENTRY_ONLY_PHASES (suppressed on a blocked bar, like sizing). To slot the entry phase in
later, NO harness rewrite is needed — only:
  1. add an `"entry_selection"` (or `"entry_timing"`) Slot to a future CONFIG, and
  2. add its FakeQC fidelity here (whatever the entry phase reads off qc/bar_state).
The scenario assertions below key on the LEDGER (orders/positions), not on the phase set, so
they remain valid once entry is inserted: an entry phase that filters candidates only changes
WHICH names size, not the structural entry->fill->exit->close flow this test pins.
==========================================================================================

INTEGRATION-GAP WATCH (#244): this test drives the REAL phases. If a real phase could not be
driven end-to-end without a src change, that is a genuine finding to FLAG (not patch under a
test ticket). None was needed — the FakeQC supplies exactly what the phases read; see the
report. The single deliberate quirk: the engine's FIRE_ENTRIES records _position_meta and
the signal phase skips invested holdings, so a held position is not re-entered — that is the
engine's existing behavior, exercised faithfully, not a workaround.
"""
from __future__ import annotations

import json
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
# THE SCENARIO — one engine, three bars, ledger asserted across the whole sequence.
# ==========================================================================================


def test_e2e_lifecycle_entry_then_exit_then_blocked() -> None:
    qc, winner, laggard = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)

    # The running ledger we assert against (built across the bars).
    # Each entry: (ticker, qty). Mirrors the engine's order capture (qc.orders).

    # --------------------------------------------------------------------------------------
    # BAR 0 — WARMUP. Pre-warmup day: the selection gate has produced NO ranked universe yet
    #   (_ranked_today == []). universe emits zero candidates, signal/sizing have nothing to
    #   do, no order fires. (This is the canonical warmup arm: dv_rank_cap returns "empty" on
    #   _ranked_today == [], the engine still completes a clean tick.)
    # --------------------------------------------------------------------------------------
    qc._ranked_today = []
    _spy(qc, price=500.0, ma200=400.0, ready=False)  # spy_sma200 still warming → regime passes
    bar0 = _tick(engine, qc, datetime(2025, 1, 3))
    assert bar0.bar_state.ranked_candidates == []
    assert qc.orders == []
    assert engine._fired_entries == 0

    # --------------------------------------------------------------------------------------
    # BAR 1 — ENTRY. WINNER scores 8/8, regime OK (SPY > MA200), LAGGARD pre-filtered out.
    #   universe ranks [WINNER, LAGGARD] -> signal keeps WINNER (8>=7), drops LAGGARD (<sma200)
    #   -> regime passes -> sizing sizes WINNER qty>0 -> FIRE_ENTRIES submits a buy.
    # --------------------------------------------------------------------------------------
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)  # SPY above MA200 → regime OK

    bar1 = _tick(engine, qc, datetime(2025, 1, 6))

    # signal funnel: exactly one candidate sized (WINNER), LAGGARD dropped by pre-filter.
    assert [o.ticker for o in bar1.bar_state.sized_orders] == ["WINNER"]
    sized = bar1.bar_state.sized_orders[0]
    assert sized.qty > 0  # flat_pct_heatcap sized it: 10% of 1M / price 100 = 1000 sh
    expected_qty = int(1_000_000.0 * 0.10 / WINNER_PRICE)
    assert sized.qty == expected_qty == 1000

    # FIRE_ENTRIES submitted a market-on-open BUY for exactly WINNER, qty>0.
    assert qc.orders == [(winner, expected_qty)]
    assert engine._fired_entries == 1
    assert engine._fired_exits == 0
    # position meta recorded (the engine's open-position bookkeeping the exit phase reads).
    assert winner in qc._position_meta
    assert qc._position_meta[winner]["entry_price"] == WINNER_PRICE
    # LEDGER so far: WINNER OPENED @ 1000 sh.

    # Reflect the fill in the portfolio for subsequent bars (LEAN would; the FakeQC is the
    # account of record here). This is harness bookkeeping, NOT a phase/src change.
    qc.portfolio[winner] = FakeHolding(invested=True, quantity=expected_qty)

    # --------------------------------------------------------------------------------------
    # BAR 2 — EXIT. WINNER's close breaches the daily Kijun (88) -> kijun_g3_exits emits the
    #   exit -> FIRE_EXITS submits the sell -> position closed. No NEW entry (already invested
    #   → signal skips it; LAGGARD still sub-floor). Ledger: WINNER CLOSED, qty out = -1000.
    # --------------------------------------------------------------------------------------
    qc.securities[winner].close = KIJUN - 5.0  # 83 < kijun 88 → Kijun-stop branch fires
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)  # regime still OK (isolating the exit, not a block)

    orders_before = len(qc.orders)
    bar2 = _tick(engine, qc, datetime(2025, 1, 7))

    # exit phase produced exactly one exit intent for WINNER, full position, qty negative.
    assert [(e.ticker, e.qty) for e in bar2.bar_state.exit_intents] == [("WINNER", -expected_qty)]
    # FIRE_EXITS submitted the sell; no new entry order this bar (WINNER invested → skipped).
    assert qc.orders[orders_before:] == [(winner, -expected_qty)]
    assert engine._fired_exits == 1
    assert engine._fired_entries == 0  # WINNER already invested → signal declines re-entry
    # position meta cleared on exit (engine._fire FIRE_EXITS path).
    assert winner not in qc._position_meta
    # LEDGER now: WINNER OPENED 1000 then CLOSED -1000 = flat.

    # Reflect the close in the portfolio.
    qc.portfolio[winner] = FakeHolding(invested=False, quantity=0)

    # --------------------------------------------------------------------------------------
    # BAR 3 — BLOCKED. SPY < MA200 (spy_200ma blocks) -> entries SUPPRESSED. A freshly-held
    #   LAGGARD position's EXIT still fires (exit-side runs on a blocked bar). Assert: no new
    #   entry order; the exit IS submitted. This proves the blocked-bar entry/exit asymmetry
    #   end-to-end on the real regime+exit phases.
    # --------------------------------------------------------------------------------------
    # Give LAGGARD an open position whose close breaches ITS kijun (same all_pass kijun=88;
    # below_sma200 set keeps the same d_ichi). WINNER now scores 8/8 again and is FLAT, so on
    # an UNBLOCKED bar it WOULD re-enter — the block is what must suppress it.
    qc.portfolio[laggard] = FakeHolding(invested=True, quantity=500)
    qc._indicators[laggard] = all_pass_indicators()  # so its d_ichi.kijun is ready for exit
    qc.securities[laggard].close = KIJUN - 5.0  # breaches kijun → exit should fire
    qc._position_meta[laggard] = {"entry_date": datetime(2025, 1, 2), "entry_price": 200.0}
    qc.securities[winner].close = WINNER_PRICE  # WINNER healthy again (would re-enter if unblocked)
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)  # SPY 300 < MA200 400 → regime BLOCKS entries

    orders_before = len(qc.orders)
    bar3 = _tick(engine, qc, datetime(2025, 1, 8))

    # Entry-side suppressed: SIGNAL runs before REGIME in PHASE_ORDER, so it still writes
    # qty=0 stub OrderIntents — but SIZING (entry-only) is suppressed on the blocked bar, so
    # NOTHING is sized to qty>0 and FIRE_ENTRIES submits no buy. Assert no sized qty>0 + 0
    # entries fired (the true entry-suppression semantics, not "no signal stubs").
    assert all(o.qty == 0 for o in bar3.bar_state.sized_orders)
    assert engine._fired_entries == 0
    buys_this_bar = [(s, q) for (s, q) in qc.orders[orders_before:] if q > 0]
    assert buys_this_bar == [], "blocked bar must submit NO new entry orders"
    # Exit-side STILL fires on the blocked bar: LAGGARD's stop breach → sell submitted.
    assert [(e.ticker, e.qty) for e in bar3.bar_state.exit_intents] == [("LAGGARD", -500)]
    assert qc.orders[orders_before:] == [(laggard, -500)]
    assert engine._fired_exits == 1
    # LEDGER final: WINNER open+close (flat); LAGGARD close -500 (the blocked-bar exit).

    # --------------------------------------------------------------------------------------
    # FULL-SEQUENCE LEDGER ASSERTION — the whole order tape across the 3 bars, in order.
    # Proves the lifecycle composed: entry fill, exit close, blocked-bar exit-only.
    # --------------------------------------------------------------------------------------
    assert qc.orders == [
        (winner, expected_qty),    # bar1: ENTRY  WINNER  +1000
        (winner, -expected_qty),   # bar2: EXIT   WINNER  -1000
        (laggard, -500),           # bar3: EXIT   LAGGARD -500 (entries blocked, exit fires)
    ]


# ==========================================================================================
# Supporting lifecycle assertions (decompose the scenario; each pins one transition).
# ==========================================================================================


def test_e2e_warmup_bar_no_trade() -> None:
    """WARMUP transition in isolation: empty _ranked_today (selection gate not warm) ->
    universe emits zero candidates -> clean tick, no order, no position."""
    qc, _, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    qc._ranked_today = []
    _spy(qc, price=500.0, ma200=400.0, ready=False)

    ctx = _tick(engine, qc, datetime(2025, 1, 3))

    assert ctx.bar_state.ranked_candidates == []
    assert ctx.bar_state.sized_orders == []
    assert qc.orders == []
    assert engine._fired_entries == 0 and engine._fired_exits == 0


def test_e2e_entry_bar_opens_position() -> None:
    """ENTRY transition in isolation: candidate scores >=7 + regime OK -> buy + meta."""
    qc, winner, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=500.0, ma200=400.0)

    ctx = _tick(engine, qc, datetime(2025, 1, 6))

    assert [o.ticker for o in ctx.bar_state.sized_orders] == ["WINNER"]
    assert qc.orders == [(winner, 1000)]
    assert winner in qc._position_meta
    assert engine._fired_entries == 1


def test_e2e_regime_off_suppresses_entry_but_not_exit() -> None:
    """BLOCKED-bar asymmetry in isolation: a fresh held stop-breach exits while entries are
    suppressed by spy_200ma. WINNER scores 8/8 and is flat, yet must NOT enter (blocked)."""
    qc, winner, laggard = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)

    # held LAGGARD breaching its kijun; flat WINNER that would otherwise enter.
    qc.portfolio[laggard] = FakeHolding(invested=True, quantity=300)
    qc._indicators[laggard] = all_pass_indicators()
    qc.securities[laggard].close = KIJUN - 5.0
    qc._position_meta[laggard] = {"entry_date": datetime(2025, 1, 2), "entry_price": 150.0}
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)  # blocks entries

    ctx = _tick(engine, qc, datetime(2025, 1, 8))

    # entry-side suppressed: nothing sized to qty>0, no buy fired (signal stubs may exist —
    # signal runs before regime; sizing, the entry-only phase, is what gets skipped).
    assert all(o.qty == 0 for o in ctx.bar_state.sized_orders)
    assert engine._fired_entries == 0
    assert qc.orders == [(laggard, -300)]            # only the exit fired
    assert engine._fired_exits == 1


def test_e2e_regime_block_emits_block_event_and_runs_diagnostics() -> None:
    """The SPY<MA200 bar (1) EMITS a regime BLOCK event AND (2) still runs the always-run
    diagnostics tail. Both assertions are load-bearing: the BLOCK assertion fails if the
    regime stops blocking; the chart assertion fails if diagnostics stops running on a
    blocked bar."""
    qc, _, _ = _make_qc()
    engine = StrategyEngine(config=CONFIG, qc=qc)
    qc._ranked_today = ["WINNER", "LAGGARD"]
    _spy(qc, price=300.0, ma200=400.0)  # SPY 300 < MA200 400 → spy_200ma must BLOCK

    _tick(engine, qc, datetime(2025, 1, 8))

    # (1) The regime BLOCK actually fired: ComponentLogger.log_phase emits an
    # {"evt":"BLOCK","kind":"regime","marker":"spy_200ma_v1",...} JSON line to qc.Log when
    # the regime PhaseResult.blocked is True. Assert that exact event is present — this is the
    # load-bearing proof the block occurred (regression: regime stops blocking → this fails).
    block_events = [json.loads(m) for m in qc.logged if '"evt":"BLOCK"' in m]
    assert any(
        e["kind"] == "regime" and e["marker"] == "spy_200ma_v1" for e in block_events
    ), f"expected a regime BLOCK event on the SPY<MA200 bar, got {block_events}"

    # (2) chart_emit ran (diagnostics is ALWAYS_RUN even on a blocked bar) → it plotted the
    # universe counts.
    assert any(series == "active_set" for (_chart, series, _v) in qc.plots)
    assert any(series == "ranked" for (_chart, series, _v) in qc.plots)
