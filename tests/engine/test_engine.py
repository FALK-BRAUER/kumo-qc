from datetime import datetime
from typing import Any

import pytest

from engine.base import ConfigError
from engine.config import StrategyConfig
from engine.context import PhaseContext
from engine.engine import (
    FIRE_ADDS, FIRE_ENTRIES, FIRE_EXITS, FIRE_TRIMS,
    KNOWN_KINDS, PHASE_ORDER, FireSentinel, StrategyEngine,
)
from tests.harness.stub_phases import slot


class FakeQC:
    def __init__(self) -> None:
        self.logged: list[str] = []
        self.orders: list[tuple[Any, int]] = []
        self._active: set[Any] = set()
        self.securities: dict[Any, Any] = {}
        self._position_meta: dict[Any, Any] = {}

    def Log(self, msg: str) -> None:
        self.logged.append(msg)

    def log(self, msg: str) -> None:
        self.logged.append(msg)

    def market_on_open_order(self, symbol: Any, qty: int) -> None:
        self.orders.append((symbol, qty))


def base_phases(**extra: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "filter": slot("filter"),
        "universe": slot("universe"),
        "signal": slot("signal"),
        "sizing": slot("sizing"),
    }
    p.update(extra)
    return p


def make_engine(qc: FakeQC, **extra: Any) -> StrategyEngine:
    cfg = StrategyConfig(name="t", version="1.0.0", phases=base_phases(**extra))
    return StrategyEngine(config=cfg, qc=qc)


def ctx() -> PhaseContext:
    return PhaseContext(qc=object(), time=datetime(2025, 1, 2), data=None)


def test_phase_order_has_sentinels() -> None:
    for s in (FIRE_ENTRIES, FIRE_EXITS, FIRE_ADDS, FIRE_TRIMS):
        assert s in PHASE_ORDER


def test_phase_order_diagnostics_then_circuit_breaker_last() -> None:
    strs = [p for p in PHASE_ORDER if isinstance(p, str)]
    assert strs[-2:] == ["diagnostics", "circuit_breaker"]


def test_fire_entries_after_cash() -> None:
    order = [str(p) for p in PHASE_ORDER]
    assert order.index("FIRE_ENTRIES") > order.index("cash")


def test_engine_runs_enabled_phases() -> None:
    qc = FakeQC()
    eng = make_engine(qc)
    eng.on_data_with_ctx(ctx())
    assert eng.phases["signal"][0].called  # type: ignore[attr-defined]


def test_strategy_init_logged() -> None:
    qc = FakeQC()
    make_engine(qc)
    assert any("STRATEGY_INIT" in m for m in qc.logged)
    assert any("PHASE_LOADED" in m for m in qc.logged)


def test_blocked_bar_runs_exits() -> None:
    # THE carve-critical fixed-blocker test: regime block halts entries; exits still run.
    qc = FakeQC()
    eng = make_engine(qc, regime=slot("regime", blocked=True), trail=slot("trail"), exit_hard=slot("exit_hard"))
    eng.on_data_with_ctx(ctx())
    assert eng.phases["regime"][0].called      # type: ignore[attr-defined]
    assert eng.phases["trail"][0].called       # type: ignore[attr-defined] exit-side runs on blocked bar
    assert eng.phases["exit_hard"][0].called   # type: ignore[attr-defined]
    assert eng.phases["sizing"][0].called is False  # type: ignore[attr-defined] entry-side suppressed


def test_blocked_bar_runs_diagnostics_tail() -> None:
    qc = FakeQC()
    eng = make_engine(qc, regime=slot("regime", blocked=True),
                      diagnostics=slot("diagnostics"), circuit_breaker=slot("circuit_breaker"))
    eng.on_data_with_ctx(ctx())
    assert eng.phases["diagnostics"][0].called      # type: ignore[attr-defined]
    assert eng.phases["circuit_breaker"][0].called  # type: ignore[attr-defined]


def test_unblocked_bar_runs_entry_phases() -> None:
    qc = FakeQC()
    eng = make_engine(qc)
    eng.on_data_with_ctx(ctx())
    assert eng.phases["sizing"][0].called  # type: ignore[attr-defined]


# ---- #234: filter kind wiring + fail-loud on unknown kinds ----

def test_filter_kind_in_phase_order_before_universe() -> None:
    order = [p for p in PHASE_ORDER if isinstance(p, str)]
    assert "filter" in order
    assert order.index("filter") < order.index("universe")
    assert "filter" in KNOWN_KINDS


def test_unknown_kind_raises_configerror() -> None:
    # A configured kind absent from PHASE_ORDER would instantiate but never be scheduled
    # (silent no-op). Engine must refuse it at init — fail-loud charter (#234 finding 2).
    qc = FakeQC()
    with pytest.raises(ConfigError, match="unknown phase kind"):
        make_engine(qc, bogus_kind=slot("bogus_kind"))


def test_filter_phase_scheduled_and_runs() -> None:
    # With "filter" now in PHASE_ORDER, a configured filter phase actually executes
    # (the #234 finding 1 fix — previously a silent no-op).
    qc = FakeQC()
    eng = make_engine(qc, filter=slot("filter"))
    eng.on_data_with_ctx(ctx())
    assert eng.phases["filter"][0].called  # type: ignore[attr-defined]


def test_filter_runs_before_universe_at_runtime() -> None:
    # Filter must execute before universe in the per-bar loop, not just in the constant.
    qc = FakeQC()
    seen: list[str] = []
    eng = make_engine(qc, filter=slot("filter"))
    for kind in ("filter", "universe"):
        eng.phases[kind][0].evaluate = _recorder(eng.phases[kind][0], kind, seen)  # type: ignore[attr-defined]
    eng.on_data_with_ctx(ctx())
    assert seen == ["filter", "universe"]


def test_filter_runs_on_blocked_bar_not_entry_only() -> None:
    # Filter gates tradeability (like universe) — it runs regardless of an entry block.
    qc = FakeQC()
    eng = make_engine(qc, filter=slot("filter"), regime=slot("regime", blocked=True))
    eng.on_data_with_ctx(ctx())
    assert eng.phases["filter"][0].called  # type: ignore[attr-defined]
    assert eng.phases["sizing"][0].called is False  # type: ignore[attr-defined] entry-side suppressed


def _recorder(phase: object, kind: str, sink: list[str]):
    orig = phase.evaluate  # type: ignore[attr-defined]

    def wrapped(ctx: PhaseContext):
        sink.append(kind)
        return orig(ctx)

    return wrapped
