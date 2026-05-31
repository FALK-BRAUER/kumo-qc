"""Tests for runtime.lean_entry — the #182 site, now LIVE-coarse (#238).

The pure, extractable logic is unit-tested here:
  - coarse_to_dollar_volume: coarse feed → {ticker: single-day DV}, lowercased (the
    prefilter input to select_live_universe).
  - active_set_hash: determinism + order-independence (the diff-ladder rung).
  - on_securities_changed: indicator-lifecycle bookkeeping (register/dispose).
  - on_data warmup guard.

The QC-runtime glue (the _coarse_selection history() fan-out, add_universe, Symbol
construction) is integration-verified on a LEAN run — pragma:no cover, not unit-testable
without QC.
"""
from __future__ import annotations

from runtime.lean_entry import active_set_hash, coarse_to_dollar_volume


class FakeSymbolValue:
    """Mimics QC Symbol exposing `.value` (the ticker)."""

    def __init__(self, value: str) -> None:
        self.value = value


class FakeCoarse:
    """Mimics a CoarseFundamental / Fundamental row: `.symbol.value` + `.dollar_volume`."""

    def __init__(self, ticker: str, dollar_volume: float) -> None:
        self.symbol = FakeSymbolValue(ticker)
        self.dollar_volume = dollar_volume


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
        algo._indicators[sym] = {"consolidator": f"cons_{sym.value}"}
    algo._register_indicators = fake_register  # type: ignore[method-assign]

    aapl, msft = FakeSym("AAPL"), FakeSym("MSFT")
    # add both
    algo.on_securities_changed(FakeChanges([FakeSec(aapl), FakeSec(msft)], []))
    assert algo._active == {aapl, msft}
    assert registered == [aapl, msft]
    assert set(algo._indicators) == {aapl, msft}
    # remove one
    algo.on_securities_changed(FakeChanges([], [FakeSec(aapl)]))
    assert algo._active == {msft}
    assert aapl not in algo._indicators
    assert algo.subscription_manager.removed == [(aapl, "cons_AAPL")]


def test_on_data_skips_engine_during_warmup() -> None:
    # WARMUP GUARD (#213d): the engine must NOT run while warming up — LEAN rejects orders
    # during warm-up, and running the pipeline over the 750d warmup is wrong + far too slow.
    from datetime import datetime as _dt

    from runtime.lean_entry import BctEngineAlgorithm

    class FakeEngine:
        def __init__(self): self.calls = 0
        def on_data_with_ctx(self, ctx): self.calls += 1

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo.engine = FakeEngine()
    algo.time = _dt(2025, 6, 2)

    algo.is_warming_up = True
    algo.on_data(None)
    assert algo.engine.calls == 0  # skipped during warmup

    algo.is_warming_up = False
    algo.on_data(None)
    assert algo.engine.calls == 1  # runs once warmup finishes


def test_active_set_hash_deterministic_order_independent() -> None:
    c1, h1 = active_set_hash(["GOOG", "AAPL", "MSFT"])
    c2, h2 = active_set_hash(["MSFT", "GOOG", "AAPL"])  # different order, same set
    assert (c1, h1) == (c2, h2)
    assert c1 == 3 and len(h1) == 64


def test_active_set_hash_changes_on_membership() -> None:
    _, h1 = active_set_hash(["AAPL", "MSFT"])
    _, h2 = active_set_hash(["AAPL", "MSFT", "NVDA"])
    assert h1 != h2
