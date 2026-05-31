"""#264 — `is_warming_up` GATING of the #259 post-warmup seed (the no-double-warm guard).

#259 history-seeds a name's indicators ONLY when it is subscribed AFTER warmup ends:

    src/runtime/lean_entry.py:406-410
      if not self.is_warming_up:
          self._seed_weekly(sym, w_ichi, w_close)
          self._seed_daily(sym, d_ichi, sma200, adx, adx_window, roc13, macd, vol_sma20, tbounce)

DURING warmup QC auto-warms the subscribed indicators independently, so seeding then would
DOUBLE-WARM (replay history into indicators QC is already feeding) — a forward-only-violation /
polluted-state risk. AFTER warmup a fresh entrant gets NO auto-warm, so the seed is the only way
it reaches is_ready the day it is subscribed (the #173 "wakes up in October" fix). These tests
pin the GATE DECISION: warmup-era register -> NO seed; post-warmup register -> BOTH seeds fire.

_register_indicators constructs QC-native indicators (self.ichimoku/sma/adx/roc/macd,
IchimokuKinkoHyo, RollingWindow, TradeBarConsolidator) that are unavailable in the dev venv. We
stub those constructors to inert objects so the REAL _register_indicators body runs to its
`if not self.is_warming_up:` branch, and we record whether _seed_weekly/_seed_daily were called.
This tests the ACTUAL gating control-flow in lean_entry, not a reimplementation.
"""
from __future__ import annotations

from typing import Any

import runtime.lean_entry as lean_entry
from runtime.lean_entry import BctEngineAlgorithm


class _StubIndicator:
    """Inert QC-indicator stand-in. `.updated` is an event supporting `+= handler` (the adx/macd
    cascade wiring), `.is_ready` False, `.current.value`/`.histogram`/`.tenkan` resolvable."""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.is_ready = False
        self.current = type("C", (), {"value": 0.0})()
        self.histogram = type("H", (), {"current": type("C", (), {"value": 0.0})()})()
        self.tenkan = type("T", (), {"current": type("C", (), {"value": 0.0})()})()
        self.updated = _StubEvent()


class _StubEvent:
    def __iadd__(self, _handler: Any) -> "_StubEvent":
        return self


class _StubRollingWindowFactory:
    """RollingWindow[float](n) -> RollingWindow[float] is subscripted THEN called. Mimic both."""

    def __getitem__(self, _t: Any) -> "_StubRollingWindowFactory":
        return self

    def __call__(self, _n: int) -> Any:
        return type("W", (), {"add": lambda self, v: None})()


class _StubConsolidator:
    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.data_consolidated = _StubEvent()


class _StubSubMgr:
    def add_consolidator(self, *_a: Any, **_k: Any) -> None:
        pass


def _make_register_algo(monkeypatch, *, warming_up: bool) -> tuple[BctEngineAlgorithm, dict[str, int]]:
    # Stub every QC-native constructor _register_indicators touches.
    monkeypatch.setattr(lean_entry, "IchimokuKinkoHyo", _StubIndicator)
    monkeypatch.setattr(lean_entry, "RollingWindow", _StubRollingWindowFactory())
    monkeypatch.setattr(lean_entry, "TradeBarConsolidator", _StubConsolidator)
    monkeypatch.setattr(lean_entry, "Calendar", type("Cal", (), {"WEEKLY": "w"}))
    monkeypatch.setattr(lean_entry, "Resolution", type("R", (), {"DAILY": "d"}))
    monkeypatch.setattr(lean_entry, "Field", type("F", (), {"VOLUME": "vol"}))
    monkeypatch.setattr(lean_entry, "MovingAverageType", type("M", (), {"EXPONENTIAL": "ema"}))
    monkeypatch.setattr(lean_entry, "TBounceTracker", _StubIndicator)

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally
    algo._indicators = {}
    algo.is_warming_up = warming_up
    algo.subscription_manager = _StubSubMgr()

    # The self.ichimoku/sma/adx/roc/macd helper methods (QCAlgorithm provides them on cloud).
    algo.ichimoku = lambda *_a, **_k: _StubIndicator()  # type: ignore[method-assign,assignment]
    algo.sma = lambda *_a, **_k: _StubIndicator()        # type: ignore[method-assign,assignment]
    algo.adx = lambda *_a, **_k: _StubIndicator()        # type: ignore[method-assign,assignment]
    algo.roc = lambda *_a, **_k: _StubIndicator()        # type: ignore[method-assign,assignment]
    algo.macd = lambda *_a, **_k: _StubIndicator()       # type: ignore[method-assign,assignment]

    calls = {"weekly": 0, "daily": 0}
    algo._seed_weekly = lambda *_a, **_k: calls.__setitem__("weekly", calls["weekly"] + 1)  # type: ignore[method-assign,assignment]
    algo._seed_daily = lambda *_a, **_k: calls.__setitem__("daily", calls["daily"] + 1)     # type: ignore[method-assign,assignment]
    return algo, calls


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


def test_register_during_warmup_does_NOT_seed(monkeypatch) -> None:
    # WARMUP-era subscription: QC auto-warms it -> the seed must NOT fire (no double-warm).
    algo, calls = _make_register_algo(monkeypatch, warming_up=True)
    algo._register_indicators(_Sym("FOO"))
    assert calls == {"weekly": 0, "daily": 0}
    # the indicator contract was still populated (the name IS tracked, just not seeded).
    assert _Sym("FOO") in algo._indicators


def test_register_after_warmup_DOES_seed_both(monkeypatch) -> None:
    # POST-WARMUP entrant (the #259 mid-FY case): NO auto-warm -> BOTH the weekly + daily seed
    # fire so the suite is ready the day it is first subscribed (not 9-10 months later).
    algo, calls = _make_register_algo(monkeypatch, warming_up=False)
    algo._register_indicators(_Sym("BAR"))
    assert calls == {"weekly": 1, "daily": 1}
    assert _Sym("BAR") in algo._indicators


def test_register_populates_full_indicator_contract(monkeypatch) -> None:
    # The contract guard (`assert set(...) == set(INDICATOR_KEYS)`) inside _register_indicators
    # must hold — every keyed indicator is wired regardless of the warmup gate.
    from runtime.indicators import INDICATOR_KEYS

    algo, _calls = _make_register_algo(monkeypatch, warming_up=False)
    algo._register_indicators(_Sym("BAZ"))
    assert set(algo._indicators[_Sym("BAZ")]) == set(INDICATOR_KEYS)
