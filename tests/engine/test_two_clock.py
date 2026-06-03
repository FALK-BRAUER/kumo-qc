"""#270/#274 two-clock tick-routing split — behavior-unchanged + the clock partition.

The split tags each phase with PHASE_RESOLUTION (default "daily") and precomputes the daily /
intraday PHASE_ORDER subsets at init. on_data_with_ctx replays the daily subset (the back-compat
decision clock); on_intraday_bar replays the intraday subset (empty until an intraday phase is
wired). These tests prove: (1) with no intraday phase the daily subset == the full order and the
intraday clock is a no-op (BEHAVIOUR UNCHANGED); (2) an intraday-tagged phase routes to
on_intraday_bar, NOT on_daily_bar; (3) mixed-clock instances of one kind fail loud; (4) the
FIRE sentinels follow their phases' clock.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from engine.base import ConfigError
from engine.config import StrategyConfig
from engine.context import PhaseContext
from engine.engine import (
    FIRE_ENTRIES,
    FIRE_EXITS,
    PHASE_ORDER,
    StrategyEngine,
)
from tests.harness.stub_phases import slot


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


def _ctx() -> PhaseContext:
    return PhaseContext(qc=FakeQC(), time=datetime(2025, 1, 2), data=None)


def _champion(**extra: object) -> StrategyConfig:
    """A complete champion stack (passes the #272 gate) for clock tests."""
    phases: dict[str, object] = {
        "universe": slot("universe"), "signal": slot("signal"),
        # sizing is IN the entry-execution chain → it must share the entry clock (#276b-1 chain
        # guard). Bind it to entry_timing's resolution so the test stack is chain-consistent by
        # construction (an explicit mismatch is tested separately in test_entry_chain_*).
        "sizing": slot("sizing", **_res(extra, "entry_timing")),
        "entry_timing": slot("entry_timing", **_res(extra, "entry_timing")),
        "exit_hard": slot("exit_hard", **_res(extra, "exit_hard")),
    }
    return StrategyConfig(name="champ", version="1.0.0", phases=phases)


def _res(extra: dict[str, object], kind: str) -> dict[str, object]:
    r = extra.get(kind)
    return {"resolution": r} if isinstance(r, str) else {}


# ── 1. behaviour unchanged: no intraday phase → daily subset == full order, intraday no-op ──

def test_all_daily_means_daily_subset_is_full_order() -> None:
    # Every phase defaults daily → the daily subset must equal the FULL PHASE_ORDER and the
    # intraday subset must be EMPTY (the pre-#274 single-clock behaviour, exactly).
    eng = StrategyEngine(config=_champion(), qc=FakeQC())
    assert eng._daily_order == list(PHASE_ORDER), "daily subset != full order with all-daily phases"
    assert eng._intraday_order == [], "intraday subset must be empty when no phase is intraday"


def test_intraday_clock_is_noop_when_no_intraday_phase() -> None:
    # on_intraday_bar with an empty intraday subset fires nothing — pure no-op.
    eng = StrategyEngine(config=_champion(), qc=FakeQC())
    ctx = _ctx()
    eng.on_intraday_bar(ctx)  # must not raise, must not fire
    assert eng._fired_entries == 0 and eng._fired_exits == 0


def test_daily_clock_runs_the_daily_phases() -> None:
    # on_data_with_ctx (daily clock) runs universe/signal/sizing as before.
    eng = StrategyEngine(config=_champion(), qc=FakeQC())
    ctx = _ctx()
    eng.on_data_with_ctx(ctx)
    for kind in ("universe", "signal", "sizing"):
        assert eng.phases[kind][0].called, f"daily phase {kind} did not run on the daily clock"


# ── 2. routing: an intraday-tagged phase goes to on_intraday_bar, NOT on_daily_bar ──

def test_intraday_phase_routes_to_intraday_clock_only() -> None:
    # Tag entry_timing + exit_hard intraday. They must be in the intraday subset, NOT the daily
    # subset; running on_data_with_ctx must NOT call them; on_intraday_bar must.
    eng = StrategyEngine(config=_champion(entry_timing="intraday", exit_hard="intraday"),
                         qc=FakeQC())
    assert "entry_timing" not in [x for x in eng._daily_order if isinstance(x, str)]
    assert "entry_timing" in [x for x in eng._intraday_order if isinstance(x, str)]
    assert "exit_hard" in [x for x in eng._intraday_order if isinstance(x, str)]
    # daily run does NOT call the intraday phases
    eng.on_data_with_ctx(_ctx())
    assert not eng.phases["entry_timing"][0].called, "intraday phase ran on the daily clock!"
    # intraday run DOES
    eng.on_intraday_bar(_ctx())
    assert eng.phases["entry_timing"][0].called, "intraday phase did not run on the intraday clock"


def test_daily_decision_phases_stay_on_daily_when_execution_is_intraday() -> None:
    # The realistic split: signal/universe/sizing daily, entry/exit intraday. Decision phases must
    # NOT appear in the intraday subset.
    eng = StrategyEngine(config=_champion(entry_timing="intraday", exit_hard="intraday"),
                         qc=FakeQC())
    intraday_kinds = [x for x in eng._intraday_order if isinstance(x, str)]
    assert "signal" not in intraday_kinds and "universe" not in intraday_kinds


# ── 3. mixed-clock instances of one kind → fail loud ──

def test_mixed_clock_instances_of_one_kind_raise() -> None:
    # exit_hard is a list-kind; two instances on DIFFERENT clocks is incoherent → ConfigError.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_timing": slot("entry_timing"),
        "exit_hard": [slot("exit_hard", resolution="daily"),
                      slot("exit_hard", resolution="intraday")],
    })
    with pytest.raises(ConfigError, match="MIXED clocks"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_invalid_resolution_raises() -> None:
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_timing": slot("entry_timing", resolution="hourly"),  # not daily|intraday
        "exit_hard": slot("exit_hard"),
    })
    with pytest.raises(ConfigError, match="invalid PHASE_RESOLUTION"):
        StrategyEngine(config=cfg, qc=FakeQC())


# ── 4. FIRE sentinels follow their phases' clock ──

def test_fire_entries_follows_entry_clock() -> None:
    # entry intraday → FIRE_ENTRIES must be in the intraday subset (fires after intraday confirm).
    eng = StrategyEngine(config=_champion(entry_timing="intraday", exit_hard="intraday"),
                         qc=FakeQC())
    assert FIRE_ENTRIES in eng._intraday_order, "FIRE_ENTRIES not routed to the intraday clock"
    assert FIRE_ENTRIES not in eng._daily_order


def test_fire_exits_follows_exit_clock() -> None:
    eng = StrategyEngine(config=_champion(entry_timing="intraday", exit_hard="intraday"),
                         qc=FakeQC())
    assert FIRE_EXITS in eng._intraday_order, "FIRE_EXITS not routed to the intraday clock"


def test_fire_sentinels_stay_daily_when_all_daily() -> None:
    # MUTATION-BITE control: all-daily → both FIRE sentinels stay on the daily clock (the
    # pre-#274 placement). Proves the routing keys on the clock, not a hardcoded side.
    eng = StrategyEngine(config=_champion(), qc=FakeQC())
    assert FIRE_ENTRIES in eng._daily_order and FIRE_EXITS in eng._daily_order
    assert FIRE_ENTRIES not in eng._intraday_order


def test_fire_exits_routes_independently_of_fire_entries() -> None:
    # r274 coverage gap: every other fixture puts entry_timing + exit_hard on the SAME clock, so a
    # FIRE_EXITS↔FIRE_ENTRIES clock-key swap would pass undetected. Split them — entry DAILY,
    # exit INTRADAY — and assert each sentinel follows ITS OWN phase's clock, not the other's.
    eng = StrategyEngine(config=_champion(entry_timing="daily", exit_hard="intraday"),
                         qc=FakeQC())
    # FIRE_ENTRIES follows entry_timing (daily); FIRE_EXITS follows exit_hard (intraday)
    assert FIRE_ENTRIES in eng._daily_order, "FIRE_ENTRIES should follow daily entry_timing"
    assert FIRE_ENTRIES not in eng._intraday_order
    assert FIRE_EXITS in eng._intraday_order, "FIRE_EXITS should follow intraday exit_hard"
    assert FIRE_EXITS not in eng._daily_order


# ── SG8 (Falk, #270/#276b-0): the daily clock DECIDES ONLY — fires ZERO orders ──

def _champion_intraday_exec() -> StrategyConfig:
    """The champion EXECUTION shape: decision phases daily; the entry-execution chain
    (entry_selection + entry_timing + SIZING) on the intraday clock (the #276b-1 chain-clock
    invariant — sizing sizes the confirmed entry at confirm time); exit_hard intraday here too."""
    return StrategyConfig(name="champ-intraday", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", resolution="intraday"),  # IN the entry-execution chain → intraday
        "entry_selection": slot("entry_selection", resolution="intraday"),
        "entry_timing": slot("entry_timing", resolution="intraday"),
        "exit_hard": slot("exit_hard", resolution="intraday"),
    })


def test_sg8_order_producing_fires_are_off_the_daily_clock() -> None:
    # SG8 (structural): with the entry + exit execution phases intraday, the order-PRODUCING fire
    # sentinels (FIRE_ENTRIES, FIRE_EXITS) are NOT on the daily clock → the daily clock cannot fill.
    # A daily-clock fill IS the retired blind-MOO model; this is the guard it can't creep back.
    eng = StrategyEngine(config=_champion_intraday_exec(), qc=FakeQC())
    assert FIRE_ENTRIES not in eng._daily_order, "SG8: FIRE_ENTRIES must not be on the daily clock"
    assert FIRE_EXITS not in eng._daily_order, "SG8: FIRE_EXITS must not be on the daily clock"
    assert FIRE_ENTRIES in eng._intraday_order and FIRE_EXITS in eng._intraday_order


def test_sg8_daily_clock_run_fires_zero_orders() -> None:
    # SG8 (behavioral): replaying the daily decision clock fires NOTHING — it produces candidates
    # + the snapshot, never an order.
    eng = StrategyEngine(config=_champion_intraday_exec(), qc=FakeQC())
    eng.on_data_with_ctx(_ctx())
    assert eng._fired_entries == 0 and eng._fired_exits == 0 and eng._fired_adds == 0, \
        "SG8 violated: the daily clock fired an order"


def test_entry_chain_mixed_clock_fails_loud() -> None:
    # #276b-1 chain-clock guard: a phase IN the entry-execution chain (sizing) on a different clock
    # than FIRE_ENTRIES (entry intraday, sizing daily) → stubs reach the fire seam UNSIZED → silent
    # 0 orders. Must CRASH at init, not silently fire nothing (the footgun the proof-of-life hit).
    phases = {
        "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", resolution="daily"),            # MISMATCH (chain is daily here)
        "entry_timing": slot("entry_timing", resolution="intraday"),
        "exit_hard": slot("exit_hard", resolution="intraday"),
    }
    cfg = StrategyConfig(name="mixed-chain", version="1.0.0", phases=phases)
    with pytest.raises(ConfigError, match="entry-execution chain mixed clocks"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_entry_chain_consistent_intraday_ok() -> None:
    # the consistent case: entire entry-execution chain (sizing + entry_timing) intraday → no raise.
    phases = {
        "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", resolution="intraday"),
        "entry_timing": slot("entry_timing", resolution="intraday"),
        "exit_hard": slot("exit_hard", resolution="daily"),       # exit_hard OUTSIDE the chain — OK
    }
    cfg = StrategyConfig(name="consistent", version="1.0.0", phases=phases)
    StrategyEngine(config=cfg, qc=FakeQC())  # must NOT raise
