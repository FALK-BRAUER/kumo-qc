"""#276b-1 — the 9 CUMULATIVE FUNNEL COUNTERS (the candidate-collapse localizer).

The funnel answers Falk's "78 orders/FY is too sparse" by counting CANDIDATE-DAYS surviving each
stage of the two-clock pipeline — the collapse STAGE is the legit-vs-bug verdict. The invariants
pinned here (fixtures only, NO cloud/LEAN):

  - PER-DAY DEDUP: a candidate evaluated across MANY intraday ticks counts ONCE per day at each
    stage (set membership is the dedup) — per-tick counting would massively overcount.
  - REGIME SEPARATION: a regime-blocked day contributes 0 to regime_pass and +1 to
    regime_blocked_days (the regime cut never masquerades as the confirm cut).
  - SESSION-END ACCUMULATION: the per-day intraday survivor sets fold into the cumulative counters
    at session end and reset for T+1.
  - MONOTONIC: the cumulative counters only increase across days.
  - GUARDED RUNTIME-STAT PUSH: set_runtime_statistic absent (local/dev venv) → NO crash, and the
    cumulative attrs still hold the numbers (the source of truth for local/tests).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from runtime.lean_entry import (
    FUNNEL_INTRADAY_STAGES,
    FUNNEL_STAGES,
    BctEngineAlgorithm,
)


class _Sym:
    def __init__(self, v: str) -> None:
        self.value = v

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _Engine:
    """A fake engine exposing only what the funnel reads: _fired_entries (stage 9) and an
    on_intraday_bar that the runtime drives (the real engine is exercised elsewhere)."""

    def __init__(self) -> None:
        self._fired_entries = 0


def _fresh_algo() -> BctEngineAlgorithm:
    a = BctEngineAlgorithm()  # QCAlgorithm == object locally — __init__ NOT run
    a.time = datetime(2025, 2, 4)
    a.logged = []
    a.log = lambda m: a.logged.append(m)  # type: ignore[method-assign,assignment]
    a.engine = _Engine()
    # the funnel state is normally set by initialize(); the runtime lazy-inits it on demand, but for
    # the unit harness init it explicitly to the canonical empty state.
    a._funnel_cum = {stage: 0 for stage in FUNNEL_STAGES}
    a._funnel_today = {stage: set() for stage in FUNNEL_INTRADAY_STAGES}
    return a


# ── PER-DAY DEDUP across many intraday ticks (the core correctness claim) ──

def test_intraday_stage_counts_once_per_day_across_many_ticks() -> None:
    a = _fresh_algo()
    aapl, msft = _Sym("AAPL"), _Sym("MSFT")
    # Simulate 50 intraday 5-min ticks: AAPL reaches preflight_pass+gap_eligible+confirm_fire on
    # EVERY tick (a candidate is evaluated every tick); MSFT only reaches preflight_pass.
    for _ in range(50):
        ictx = PhaseContext(qc=a, time=a.time, data=None)
        ictx.record_funnel("preflight_pass", aapl)
        ictx.record_funnel("gap_eligible", aapl)
        ictx.record_funnel("confirm_fire", aapl)
        ictx.record_funnel("preflight_pass", msft)
        a._fold_intraday_funnel(ictx)
    # nothing flushed yet (per-day sets hold) — but the per-day sets must each hold the symbol ONCE.
    assert a._funnel_today["preflight_pass"] == {aapl, msft}
    assert a._funnel_today["confirm_fire"] == {aapl}
    # flush → cumulative counts the SET SIZE (once/day), not 50× per tick.
    a._flush_funnel_day()
    assert a._funnel_cum["preflight_pass"] == 2   # AAPL + MSFT, once each
    assert a._funnel_cum["gap_eligible"] == 1     # AAPL only
    assert a._funnel_cum["confirm_fire"] == 1     # AAPL only
    # per-day sets reset for T+1
    assert all(a._funnel_today[s] == set() for s in FUNNEL_INTRADAY_STAGES)


def test_orders_accumulate_per_tick_not_deduped() -> None:
    # stage 9 (orders) = the engine's fired-entries count; each fire is a distinct order (NO dedup).
    a = _fresh_algo()
    for fired in (1, 2, 0, 3):
        a.engine._fired_entries = fired
        ictx = PhaseContext(qc=a, time=a.time, data=None)
        a._fold_intraday_funnel(ictx)
    assert a._funnel_cum["orders"] == 1 + 2 + 0 + 3


# ── DAILY stages: regime separation ──

def test_regime_blocked_day_zero_regime_pass_increments_blocked_days() -> None:
    a = _fresh_algo()
    # 3 signal winners on a BLOCKED day → signal_winners += 3, regime_pass += 0, blocked_days += 1.
    a._accumulate_daily_funnel(["AAPL", "MSFT", "GOOG"], blocked=True)
    assert a._funnel_cum["signal_winners"] == 3
    assert a._funnel_cum["regime_pass"] == 0
    assert a._funnel_cum["regime_blocked_days"] == 1


def test_regime_unblocked_day_regime_pass_equals_signal_winners() -> None:
    a = _fresh_algo()
    a._accumulate_daily_funnel(["AAPL", "MSFT"], blocked=False)
    assert a._funnel_cum["signal_winners"] == 2
    assert a._funnel_cum["regime_pass"] == 2          # == winners when not blocked
    assert a._funnel_cum["regime_blocked_days"] == 0  # the cut is SEPARATE, not folded into pass


# ── SESSION-END ACCUMULATION + MONOTONICITY across days ──

def test_session_end_accumulation_and_monotonic_increase() -> None:
    a = _fresh_algo()
    snaps: list[dict[str, int]] = []

    def _run_day(winners: list[str], blocked: bool, confirmers: list[_Sym]) -> None:
        a._accumulate_daily_funnel(winners, blocked)
        # several intraday ticks where `confirmers` each reach confirm_fire (every tick)
        for _ in range(10):
            ictx = PhaseContext(qc=a, time=a.time, data=None)
            for sym in confirmers:
                ictx.record_funnel("preflight_pass", sym)
                ictx.record_funnel("gap_eligible", sym)
                ictx.record_funnel("confirm_fire", sym)
            a._fold_intraday_funnel(ictx)
        a._flush_funnel_day()  # session end
        snaps.append(dict(a._funnel_cum))

    _run_day(["AAPL", "MSFT"], blocked=False, confirmers=[_Sym("AAPL")])
    _run_day(["TSLA"], blocked=True, confirmers=[])              # blocked → no intraday survivors
    _run_day(["NVDA", "AMD"], blocked=False, confirmers=[_Sym("NVDA"), _Sym("AMD")])

    # monotonic: each cumulative counter never decreases day-over-day.
    for stage in FUNNEL_STAGES:
        seq = [s[stage] for s in snaps]
        assert seq == sorted(seq), f"{stage} not monotonic: {seq}"

    # explicit end totals
    assert a._funnel_cum["signal_winners"] == 2 + 1 + 2        # 5
    assert a._funnel_cum["regime_pass"] == 2 + 0 + 2           # blocked day contributes 0
    assert a._funnel_cum["regime_blocked_days"] == 1
    assert a._funnel_cum["confirm_fire"] == 1 + 0 + 2          # day1 AAPL, day3 NVDA+AMD


# ── GUARDED RUNTIME-STAT PUSH ──

def test_push_runtime_stats_noop_when_setter_absent_attrs_hold() -> None:
    # local/dev venv: set_runtime_statistic / SetRuntimeStatistic absent → NO crash; attrs hold.
    a = _fresh_algo()
    a._accumulate_daily_funnel(["AAPL"], blocked=False)
    assert not hasattr(a, "set_runtime_statistic")
    a._push_funnel_runtime_stats()  # must not raise
    assert a._funnel_cum["signal_winners"] == 1  # the source of truth is still intact


def test_push_runtime_stats_uses_setter_when_present() -> None:
    a = _fresh_algo()
    pushed: dict[str, str] = {}
    a.set_runtime_statistic = lambda k, v: pushed.__setitem__(k, v)  # type: ignore[attr-defined]
    a._accumulate_daily_funnel(["AAPL", "MSFT"], blocked=False)
    a._funnel_cum["orders"] = 7
    a._push_funnel_runtime_stats()
    assert pushed["funnel.signal_winners"] == "2"
    assert pushed["funnel.regime_pass"] == "2"
    assert pushed["funnel.orders"] == "7"
    # all 9 stages published
    assert set(pushed) == {f"funnel.{s}" for s in FUNNEL_STAGES}


def test_pascalcase_setter_also_works() -> None:
    # cloud QCAlgorithm exposes SetRuntimeStatistic (PascalCase); the push must find it too.
    a = _fresh_algo()
    pushed: dict[str, str] = {}
    a.SetRuntimeStatistic = lambda k, v: pushed.__setitem__(k, v)  # type: ignore[attr-defined]
    a._accumulate_daily_funnel(["AAPL"], blocked=False)
    a._push_funnel_runtime_stats()
    assert pushed["funnel.signal_winners"] == "1"


# ── lazy-init robustness: a bare algo reaching the accumulators must not crash ──

def test_bare_algo_lazy_inits_funnel_state() -> None:
    a = BctEngineAlgorithm()
    a.time = datetime(2025, 2, 4)
    a.engine = _Engine()
    assert not hasattr(a, "_funnel_cum")
    a._accumulate_daily_funnel(["AAPL"], blocked=False)  # lazy-inits, no crash
    assert a._funnel_cum["signal_winners"] == 1


# ── session-end flush is idempotent under QC's per-symbol on_end_of_day firing ──

def test_session_end_flush_idempotent_per_symbol() -> None:
    a = _fresh_algo()
    aapl = _Sym("AAPL")
    ictx = PhaseContext(qc=a, time=a.time, data=None)
    ictx.record_funnel("confirm_fire", aapl)
    a._fold_intraday_funnel(ictx)
    # QC fires on_end_of_day once PER SYMBOL → _flush_funnel_day runs multiple times. The first
    # accumulates + resets; subsequent calls add 0 (the sets are empty).
    a._flush_funnel_day()
    a._flush_funnel_day()
    a._flush_funnel_day()
    assert a._funnel_cum["confirm_fire"] == 1  # counted ONCE despite 3 flushes


# ── PHASE SEAMS: the gate phases actually record their survivor sets into ctx.bar_state.funnel ──
# These pin that the funnel is wired at the REAL seam (where the candidate passes the stage), not
# fabricated. Minimal fakes mirror the phase unit fixtures.

class _Sec:
    def __init__(self, price: float) -> None:
        self.price = price


class _PhaseQC:
    """Bare qc for phase.evaluate: _active + securities + the 276b-0 snapshot accessor."""

    def __init__(self) -> None:
        self._active: set[Any] = set()
        self.securities: dict[Any, _Sec] = {}
        self._snaps: dict[Any, dict[str, Any]] = {}

    def add(self, name: str, price: float) -> _Sym:
        s = _Sym(name)
        self._active.add(s)
        self.securities[s] = _Sec(price)
        return s

    def snapshot_for_entry(self, sym: Any) -> "dict[str, Any] | None":
        return self._snaps.get(sym)


def _ctx_with_stubs(qc: _PhaseQC, tickers: list[str]) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="stub", risk_dollars=0.0)
        for t in tickers
    ]
    return ctx


def test_preflight_records_preflight_pass_for_valid_only() -> None:
    from phases.entry_selection.preflight_staleness.preflight_staleness import PreFlightStaleness

    qc = _PhaseQC()
    good = qc.add("AAPL", 105.0)   # gap-up above kijun → valid
    bad = qc.add("MSFT", 90.0)     # below signal_price (gap-down) → invalid
    qc._snaps[good] = {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}
    qc._snaps[bad] = {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}
    qc._intraday = {good: {"last_close": 105.0}, bad: {"last_close": 90.0}}  # type: ignore[attr-defined]
    ctx = _ctx_with_stubs(qc, ["AAPL", "MSFT"])
    PreFlightStaleness(PreFlightStaleness.Params(), logger=None).evaluate(ctx)
    assert ctx.bar_state.funnel["preflight_pass"] == {good}  # only the valid candidate recorded


def test_gapvol_records_gap_eligible_and_confirm_fire() -> None:
    from phases.entry_selection.bct_intraday_gap_vol_confirm.bct_intraday_gap_vol_confirm import (
        BctIntradayGapVolConfirm,
    )

    class _Bar:
        def __init__(self, vol: float) -> None:
            self.volume = vol

    class _Vol:
        def __init__(self, vals: list[float]) -> None:
            self._v = vals

        @property
        def count(self) -> int:
            return len(self._v)

        def __getitem__(self, i: int) -> float:
            return self._v[i]

    qc = _PhaseQC()
    # AAPL: +5% gap, loud volume → confirmed (gap_eligible + confirm_fire).
    aapl = qc.add("AAPL", 105.0)
    # MSFT: +5% gap but QUIET volume → gap_eligible only (quiet_open), NOT confirm_fire.
    msft = qc.add("MSFT", 105.0)
    # GOOG: +1% gap (< 3% threshold) → gap_too_small → NEITHER.
    goog = qc.add("GOOG", 101.0)
    for s in (aapl, msft, goog):
        qc._snaps[s] = {"signal_price": 100.0, "daily_kijun": 95.0, "decision_date": "T"}
    qc._entry_confirm = {}  # type: ignore[attr-defined]
    qc._intraday = {  # type: ignore[attr-defined]
        aapl: {"last_close": 105.0, "last_bar": _Bar(2000.0), "vol_window": _Vol([1000.0, 1000.0])},
        msft: {"last_close": 105.0, "last_bar": _Bar(100.0), "vol_window": _Vol([1000.0, 1000.0])},
        goog: {"last_close": 101.0, "last_bar": _Bar(2000.0), "vol_window": _Vol([1000.0, 1000.0])},
    }
    ctx = _ctx_with_stubs(qc, ["AAPL", "MSFT", "GOOG"])
    BctIntradayGapVolConfirm(BctIntradayGapVolConfirm.Params(), logger=None).evaluate(ctx)
    assert ctx.bar_state.funnel.get("gap_eligible") == {aapl, msft}  # both cleared the gap; GOOG did not
    assert ctx.bar_state.funnel.get("confirm_fire") == {aapl}        # only AAPL was loud enough to confirm


def test_sizing_records_sized_and_cash_ok() -> None:
    from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap

    class _Portfolio(dict):
        def __init__(self) -> None:
            super().__init__()
            self.cash = 15_000.0
            self.total_portfolio_value = 100_000.0

        def __missing__(self, k: Any) -> Any:
            return type("H", (), {"invested": False})()

    qc = _PhaseQC()
    a1 = qc.add("AAPL", 100.0)   # target 10k → fits → sized + cash_ok
    qc.add("MSFT", 100.0)        # needs 10k, only 5k left → cash-exhausted (break) → neither
    qc.portfolio = _Portfolio()  # type: ignore[attr-defined]
    ctx = _ctx_with_stubs(qc, ["AAPL", "MSFT"])
    FlatPctHeatcap(FlatPctHeatcap.Params(position_pct=0.10), logger=None).evaluate(ctx)
    assert ctx.bar_state.funnel.get("cash_ok") == {a1}  # only AAPL cleared the cash cap
    assert ctx.bar_state.funnel.get("sized") == {a1}    # and got qty>0
