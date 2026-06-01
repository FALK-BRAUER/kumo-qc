"""Tests for runtime.lean_entry — the #182 site, now LIVE-coarse selection gate (#238 / Y).

The pure, extractable logic is unit-tested here:
  - coarse_to_dollar_volume: coarse feed → {ticker: single-day DV}, lowercased (the prefilter
    input + the per-day value pushed into the maintained rolling-20d-DV windows).
  - active_set_hash: determinism + order-independence (the diff-ladder selection rung).
  - the selection-gate FLOOR KNOBS (the floors live on this class under Y, not a phase).
  - on_securities_changed: indicator-lifecycle bookkeeping (register/dispose).
  - on_data warmup guard.

SCALING FIX (incremental-DV): the per-day history() fan-out is GONE. _coarse_selection now
maintains a rolling 20-day DV (qc._dv_windows) from the coarse feed and builds bar_metrics
FROM the windows — covered here with a stubbed Symbol factory + a history() that explodes if
called (proving the selection path is history-free). WARMUP_DAYS is now DERIVED (560d, weekly-
Ichimoku readiness) — asserted against the LEAN IchimokuKinkoHyo.WarmUpPeriod formula.

The remaining QC-runtime glue (add_universe wiring, the LEAN coarse-feed type) is integration-
verified on a LEAN run — pragma:no cover, not unit-testable without QC.
"""
from __future__ import annotations

import runtime.lean_entry as lean_entry
from runtime.lean_entry import (
    BctEngineAlgorithm,
    active_set_hash,
    coarse_to_close,
    coarse_to_dollar_volume,
)
from runtime.universe_select import DvWindow, rolling_dv_mean


def test_selection_gate_floor_knobs_are_the_agreed_defaults() -> None:
    # Under Y the floors live on the lean_entry class (the selection gate), not a per-bar
    # filter phase. These are the SINGLE source of the floor + rank + cap values.
    assert BctEngineAlgorithm.MIN_PRICE == 10.0
    assert BctEngineAlgorithm.MIN_AVG_DOLLAR_VOLUME == 100_000_000.0  # liquidity (fintrack ~943/day)
    assert BctEngineAlgorithm.ADV_WINDOW == 20
    assert BctEngineAlgorithm.PREFILTER_DV == 25_000_000.0
    assert BctEngineAlgorithm.COARSE_MAX == 9999


def test_warmup_days_is_the_derived_weekly_ichimoku_value() -> None:
    # GATE 2: WARMUP_DAYS is DERIVED from the WEEKLY IchimokuKinkoHyo(9,26,26,52,26,26)
    # readiness (78 weekly bars = senkouB 52 + senkouB-delay 26), NOT the old un-derived 750.
    # 78 weeks + 1 partial-week + 1-week buffer = 560 cal days; binding over daily-ichimoku
    # (~109d) + 200-day SMA (~280d). See the WARMUP_DAYS docstring for the full derivation.
    assert BctEngineAlgorithm.WARMUP_DAYS == 560
    # the weekly Ichimoku readiness the derivation pins to (must stay the binding constraint):
    t, k, sad, sb, sbd = 9, 26, 26, 52, 26
    assert max(t + sad, k + sad, sb + sbd) == 78


class FakeSymbolValue:
    """Mimics QC Symbol exposing `.value` (the ticker)."""

    def __init__(self, value: str) -> None:
        self.value = value


class FakeCoarse:
    """Mimics a CoarseFundamental row: `.symbol.value` + `.dollar_volume` + `.price` (RAW)."""

    def __init__(self, ticker: str, dollar_volume: float, price: float = 50.0) -> None:
        self.symbol = FakeSymbolValue(ticker)
        self.dollar_volume = dollar_volume
        self.price = price  # CoarseFundamental.Price = RAW price (the price-floor input)


def test_coarse_to_close_extracts_raw_price_lowercased() -> None:
    # The price floor reads coarse `.price` (RAW), NOT history close (the scaling fix) and NOT
    # `.adjusted_price` (adjusted corrupts the RAW contract). GATE 1: coarse .price == RAW close.
    coarse = [FakeCoarse("AAPL", 5.0e9, price=243.82), FakeCoarse("MSFT", 4.0e9, price=418.69)]
    assert coarse_to_close(coarse) == {"aapl": 243.82, "msft": 418.69}


def test_coarse_to_close_coerces_float_and_empty() -> None:
    assert coarse_to_close([FakeCoarse("nvda", 3.0e9, price=138)]) == {"nvda": 138.0}
    assert coarse_to_close([]) == {}


def test_coarse_to_dollar_volume_extracts_and_lowercases() -> None:
    # QC coarse tickers are uppercase; we lower-case to the zip-stem / qc._active convention
    # so the downstream case-insensitive intersection (universe + signal phases) hits.
    coarse = [FakeCoarse("AAPL", 5.0e9), FakeCoarse("MSFT", 4.0e9)]
    dv = coarse_to_dollar_volume(coarse)
    assert dv == {"aapl": 5.0e9, "msft": 4.0e9}


def test_coarse_to_dollar_volume_empty_feed() -> None:
    assert coarse_to_dollar_volume([]) == {}


def test_coarse_to_dollar_volume_coerces_float() -> None:
    # dollar_volume may arrive as an int-like; coerce to float for the prefilter comparison.
    dv = coarse_to_dollar_volume([FakeCoarse("nvda", 3)])
    assert dv == {"nvda": 3.0}
    assert isinstance(dv["nvda"], float)


def test_on_securities_changed_registers_active_and_disposes() -> None:
    # Lifecycle control-flow (#213c): added → _active.add + _register_indicators; removed →
    # _active.discard + remove_consolidator + del. QC-type construction (_register_indicators
    # body) is integration-verified; here we test the bookkeeping with a stubbed register.
    from runtime.lean_entry import BctEngineAlgorithm

    class FakeSym:
        def __init__(self, v): self.value = v
        def __hash__(self): return hash(self.value)
        def __eq__(self, o): return isinstance(o, FakeSym) and o.value == self.value

    class FakeSec:
        def __init__(self, sym): self.symbol = sym

    class FakeChanges:
        def __init__(self, added, removed):
            self.added_securities = added
            self.removed_securities = removed

    class FakeSubMgr:
        def __init__(self): self.removed = []
        def remove_consolidator(self, sym, cons): self.removed.append((sym, cons))

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally; initialize() not invoked
    algo._active = set()
    algo._indicators = {}
    algo.subscription_manager = FakeSubMgr()
    registered = []

    def fake_register(sym):
        registered.append(sym)
        # #253: the contract now carries a daily_consolidator alongside the weekly one; the
        # unsubscribe path disposes BOTH.
        algo._indicators[sym] = {
            "consolidator": f"cons_{sym.value}",
            "daily_consolidator": f"daily_{sym.value}",
        }
    algo._register_indicators = fake_register  # type: ignore[method-assign]

    aapl, msft = FakeSym("AAPL"), FakeSym("MSFT")
    # add both
    algo.on_securities_changed(FakeChanges([FakeSec(aapl), FakeSec(msft)], []))
    assert algo._active == {aapl, msft}
    assert registered == [aapl, msft]
    assert set(algo._indicators) == {aapl, msft}
    # remove one — both the weekly and the #253 daily consolidator are disposed.
    algo.on_securities_changed(FakeChanges([], [FakeSec(aapl)]))
    assert algo._active == {msft}
    assert aapl not in algo._indicators
    assert algo.subscription_manager.removed == [(aapl, "cons_AAPL"), (aapl, "daily_AAPL")]


def test_on_data_skips_engine_during_warmup() -> None:
    # WARMUP GUARD (#213d): the engine must NOT run while warming up — LEAN rejects orders
    # during warm-up, and running the pipeline over the 560d warmup is wrong + far too slow.
    from datetime import datetime as _dt

    from runtime.lean_entry import BctEngineAlgorithm

    class FakeEngine:
        def __init__(self): self.calls = 0
        def on_data_with_ctx(self, ctx): self.calls += 1

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo.engine = FakeEngine()
    algo.time = _dt(2025, 6, 2)
    # #275b: on_data is two-clock now — give it the intraday state initialize() would set. Empty
    # intraday set + data=None → no intraday bars → the daily clock runs (the `not self._intraday`
    # fallback), exactly the pre-#275b behaviour this test pins. #275b-fix: on_data's daily path
    # now reconciles intraday subs → needs _active + _ranked_today (empty → clean no-op here).
    algo._intraday = {}
    algo._intraday_active = set()
    algo._active = set()
    algo._ranked_today = []

    algo.is_warming_up = True
    algo.on_data(None)
    assert algo.engine.calls == 0  # skipped during warmup

    algo.is_warming_up = False
    algo.on_data(None)
    assert algo.engine.calls == 1  # runs once warmup finishes (daily clock; no intraday subs)


def test_on_data_two_clock_routing() -> None:
    # #275b S1 (the load-bearing routing): on_data routes the DAILY bar → on_data_with_ctx
    # (decision clock) and 5-min bars → on_intraday_bar (execution clock). Pin all three slice
    # shapes so the gate `spy_bar is not None or not self._intraday` can't drift silently.
    from datetime import datetime as _dt

    from runtime.lean_entry import BctEngineAlgorithm

    class FakeEngine:
        def __init__(self): self.daily = 0; self.intraday = 0
        def on_data_with_ctx(self, ctx): self.daily += 1
        def on_intraday_bar(self, ctx): self.intraday += 1

    class FakeSym:
        def __init__(self, v): self.value = v
        def __hash__(self): return hash(self.value)
        def __eq__(self, o): return isinstance(o, FakeSym) and o.value == self.value

    class FakeBar:
        def __init__(self, close=100.0, volume=1000.0):
            self.close = close; self.volume = volume

    class FakeBars:
        def __init__(self, d): self._d = d
        def get(self, sym): return self._d.get(sym)

    class FakeSlice:
        def __init__(self, bars): self.bars = bars

    class FakeIntradayState(dict):
        pass

    spy = FakeSym("SPY")
    aapl = FakeSym("AAPL")

    def _algo():
        a = BctEngineAlgorithm()
        a.engine = FakeEngine()
        a.time = _dt(2025, 6, 2)
        a.is_warming_up = False
        a.spy = type("S", (), {"symbol": spy})()
        # AAPL has a live intraday subscription with a minimal state dict
        a._intraday = {aapl: {"intraday_tenkan": type("I", (), {"update": lambda s, b: None})(),
                              "vol_window": type("W", (), {"add": lambda s, v: None})(),
                              "last_close": None, "last_bar": None}}
        # #275b-fix: on_data's daily path reconciles intraday subs → stub _active/_ranked_today/
        # _intraday_active (+ portfolio for the held-keeps-feed check). _ranked_today=[aapl-ish]
        # empty-resolvable → the sync keeps the existing AAPL sub (it's already active), no churn.
        a._active = {aapl}
        a._intraday_active = {aapl}
        a._ranked_today = ["aapl"]
        a.portfolio = type("P", (), {"__getitem__": lambda s, k: type("H", (), {"invested": False})()})()
        return a

    # (a) 5-min bar present, NO SPY daily bar → intraday clock fires, daily clock SKIPPED
    a = _algo()
    a.on_data(FakeSlice(FakeBars({aapl: FakeBar()})))
    assert a.engine.intraday == 1 and a.engine.daily == 0, "5-min slice should fire intraday only"

    # (b) SPY daily bar present (+ intraday subs) → daily clock fires
    a = _algo()
    a.on_data(FakeSlice(FakeBars({spy: FakeBar()})))
    assert a.engine.daily == 1, "SPY daily bar must fire the daily decision clock"

    # (c) both present → both clocks fire
    a = _algo()
    a.on_data(FakeSlice(FakeBars({spy: FakeBar(), aapl: FakeBar()})))
    assert a.engine.daily == 1 and a.engine.intraday == 1, "both bars present → both clocks"


# --------------------------------------------------------------------------------------
# _coarse_selection — the rewired SELECTION GATE (incremental-DV scaling fix). The metric
# source is now the MAINTAINED rolling-DV windows, NOT a per-day history() call. These tests
# stub the QC Symbol factory (None in the dev venv) and assert: rolling-window maintenance,
# bar_metrics built FROM the windows, NO history() in the selection path, prefilter + floors.
# --------------------------------------------------------------------------------------
class _FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _FakeSymbol) and o.value == self.value


class _FakeSymbolFactory:
    @staticmethod
    def create(ticker, _sectype, _market):  # mimics Symbol.create(ticker, EQUITY, USA)
        return _FakeSymbol(ticker)


def _make_selection_algo(monkeypatch) -> BctEngineAlgorithm:
    """A BctEngineAlgorithm with just enough state to run _coarse_selection locally: the live
    universe state + a stubbed Symbol factory + a history() that EXPLODES (proving the
    selection path never calls it — the whole point of the scaling fix)."""
    monkeypatch.setattr(lean_entry, "Symbol", _FakeSymbolFactory)
    monkeypatch.setattr(lean_entry, "SecurityType", type("ST", (), {"EQUITY": 1}))
    monkeypatch.setattr(lean_entry, "Market", type("MK", (), {"USA": "usa"}))

    from datetime import datetime as _dt

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo._dv_windows = {}
    algo._dv_day_index = -1
    algo._ranked_today = []
    algo._trailing_dv = {}
    algo._bar_metrics = {}
    algo.time = _dt(2025, 6, 2)
    # #275b: these tests exercise the SELECTION mechanics only — warming-up skips the downstream
    # intraday-subscription sync (a live-clock concern, tested separately in test_intraday_lifecycle).
    algo.is_warming_up = True
    algo.logged: list[str] = []
    algo.log = lambda m: algo.logged.append(m)  # type: ignore[method-assign,assignment]

    def _explode_history(*_a, **_k):  # the selection path must NEVER call history()
        raise AssertionError("history() called in the selection path — scaling fix violated")

    algo.history = _explode_history  # type: ignore[method-assign,assignment]
    return algo


def test_coarse_selection_maintains_rolling_windows_no_history(monkeypatch) -> None:
    algo = _make_selection_algo(monkeypatch)
    # Two liquid names above the prefilter + floors; one thin name below the prefilter.
    coarse = [
        FakeCoarse("AAPL", 5.0e9, price=240.0),
        FakeCoarse("MSFT", 4.0e9, price=400.0),
        FakeCoarse("THIN", 1.0e6, price=5.0),  # below PREFILTER_DV -> no metric built
    ]
    ranked = algo._coarse_selection(coarse)
    # windows maintained for ALL coarse names (the rolling DV accumulates for every name)
    assert set(algo._dv_windows) == {"aapl", "msft", "thin"}
    assert rolling_dv_mean(algo._dv_windows["aapl"].dv) == 5.0e9
    # bar_metrics built FROM the windows for prefilter survivors only (THIN excluded)
    assert set(algo._bar_metrics) == {"aapl", "msft"}
    assert algo._bar_metrics["aapl"] == (240.0, 5.0e9)
    # both pass floors (price>=10, trailing dv>=100M) -> ranked DV-desc
    assert [s.value for s in ranked] == ["AAPL", "MSFT"]
    assert algo._ranked_today == ["aapl", "msft"]
    assert any(m.startswith("ACTIVE_SET|") for m in algo.logged)


def test_coarse_selection_trailing_dv_is_rolling_mean_over_days(monkeypatch) -> None:
    # The trailing DV that feeds the floor is the ROLLING MEAN across days, not a single day.
    # Day 1: AAPL DV=50M (below the 100M floor) -> NOT eligible. Day 2: DV=200M -> mean over the
    # two days = 125M -> now eligible. Proves the maintained window drives the floor decision.
    algo = _make_selection_algo(monkeypatch)
    algo.time = algo.time.replace(day=2)
    r1 = algo._coarse_selection([FakeCoarse("AAPL", 50_000_000.0, price=200.0)])
    assert [s.value for s in r1] == []  # 50M < 100M floor
    assert algo._bar_metrics["aapl"] == (200.0, 50_000_000.0)
    r2 = algo._coarse_selection([FakeCoarse("AAPL", 200_000_000.0, price=210.0)])
    # rolling mean = (50M + 200M)/2 = 125M >= 100M -> eligible now
    assert algo._bar_metrics["aapl"] == (210.0, 125_000_000.0)
    assert [s.value for s in r2] == ["AAPL"]


def test_coarse_selection_window_warm_by_warmup_days(monkeypatch) -> None:
    # WARM-BY-WARMUP: the callback runs each (warmup) day, so after ADV_WINDOW days the window
    # is full — no startup history() seed. Feed ADV_WINDOW days of identical DV; the window
    # holds exactly ADV_WINDOW entries and the mean equals that DV.
    algo = _make_selection_algo(monkeypatch)
    for _ in range(BctEngineAlgorithm.ADV_WINDOW + 5):  # more than a full window
        algo._coarse_selection([FakeCoarse("AAPL", 3.0e9, price=100.0)])
    assert len(algo._dv_windows["aapl"].dv) == BctEngineAlgorithm.ADV_WINDOW
    assert rolling_dv_mean(algo._dv_windows["aapl"].dv) == 3.0e9
    assert algo._dv_day_index == BctEngineAlgorithm.ADV_WINDOW + 5 - 1


def test_coarse_selection_zero_candidate_day_sets_empty_list(monkeypatch) -> None:
    # A day where nothing clears the prefilter -> _ranked_today = [] (NOT None — the universe
    # phase distinguishes empty-day from a wiring bug). Still maintains windows + logs.
    algo = _make_selection_algo(monkeypatch)
    algo._coarse_selection([FakeCoarse("THIN", 1.0e6, price=5.0)])
    assert algo._ranked_today == []
    assert algo._bar_metrics == {}
    assert "thin" in algo._dv_windows  # window still maintained


def test_active_set_hash_deterministic_order_independent() -> None:
    c1, h1 = active_set_hash(["GOOG", "AAPL", "MSFT"])
    c2, h2 = active_set_hash(["MSFT", "GOOG", "AAPL"])  # different order, same set
    assert (c1, h1) == (c2, h2)
    assert c1 == 3 and len(h1) == 64


def test_active_set_hash_changes_on_membership() -> None:
    _, h1 = active_set_hash(["AAPL", "MSFT"])
    _, h2 = active_set_hash(["AAPL", "MSFT", "NVDA"])
    assert h1 != h2
