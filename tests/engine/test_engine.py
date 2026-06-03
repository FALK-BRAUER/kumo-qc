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

    def market_on_open_order(self, symbol: Any, qty: int, tag: str = "") -> None:
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
    # is_fixture=True: these are engine-MECHANICS unit tests on minimal stacks (no entry/exit
    # phase wired) — they exercise the tick loop / fire seam / suppression, NOT champion
    # completeness. The #272 fail-loud entry+exit gate is tested directly in test_invariants.py.
    cfg = StrategyConfig(name="t", version="1.0.0", phases=base_phases(**extra), is_fixture=True)
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


def test_blocked_regime_bar_exposes_bar_blocked() -> None:
    # #277 regime→intraday gate: a regime block must set ctx.bar_state.bar_blocked so the
    # daily decision (lean_entry) captures an EMPTY candidate snapshot → no intraday entries
    # that session. Previously the block was confined to the daily clock; intraday gap+loud
    # entries ignored it (over-traded bad regimes). The engine must expose the block.
    qc = FakeQC()
    eng = make_engine(qc, regime=slot("regime", blocked=True))
    c = ctx()
    eng.on_data_with_ctx(c)
    assert c.bar_state.bar_blocked is True


def test_unblocked_bar_leaves_bar_blocked_false() -> None:
    # The mirror: an unblocked bar must NOT raise the gate (else every session is gated).
    qc = FakeQC()
    eng = make_engine(qc)
    c = ctx()
    eng.on_data_with_ctx(c)
    assert c.bar_state.bar_blocked is False


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


# ---------------------------------------------------------------------------
# #245 — _fire order-submission assertions. The stub phases never populate the
# typed intent lists, so the engine's _fire methods (src ~:225-263) were never
# asserted: this is the unit cousin of the liveness gate. Here we populate a
# BarState directly and drive _fire, asserting the broker order + _position_meta.
# ---------------------------------------------------------------------------
from engine.context import BarState, OrderIntent  # noqa: E402


class _Sym:
    """Minimal LEAN-symbol stand-in: hashable, has `.value` (what _fire keys on)."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _FireSecurity:
    def __init__(self, price: float) -> None:
        self.price = price


def _fire_qc(*symbols: tuple[str, float]) -> FakeQC:
    """A FakeQC primed with active symbols + priced securities for _fire."""
    qc = FakeQC()
    for value, price in symbols:
        sym = _Sym(value)
        qc._active.add(sym)
        qc.securities[sym] = _FireSecurity(price)
    return qc


def _sym_in(qc: FakeQC, value: str) -> Any:
    return next(s for s in qc._active if s.value == value)


def _intent(ticker: str, qty: int, price: float = 0.0) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=qty, price=price, stop=0.0, module="t", risk_dollars=0.0)


def _ctx_with(qc: FakeQC, bar: BarState) -> PhaseContext:
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None, bar_state=bar)


def test_fire_entries_submits_order_and_records_meta() -> None:
    qc = _fire_qc(("AAPL", 150.0))
    eng = make_engine(qc)
    bar = BarState(sized_orders=[_intent("AAPL", 10)])
    eng._fire(FIRE_ENTRIES, _ctx_with(qc, bar))

    sym = _sym_in(qc, "AAPL")
    assert qc.orders == [(sym, 10)]               # market-on-open submitted with the sized qty
    assert eng._fired_entries == 1
    assert sym in qc._position_meta
    assert qc._position_meta[sym]["entry_price"] == 150.0
    assert qc._position_meta[sym]["entry_date"] == datetime(2025, 1, 2)


def test_fire_entries_skips_nonpositive_qty() -> None:
    qc = _fire_qc(("AAPL", 150.0))
    eng = make_engine(qc)
    bar = BarState(sized_orders=[_intent("AAPL", 0)])  # qty<=0 → not submitted
    eng._fire(FIRE_ENTRIES, _ctx_with(qc, bar))
    assert qc.orders == []
    assert eng._fired_entries == 0


def test_fire_exits_submits_and_pops_meta() -> None:
    qc = _fire_qc(("MSFT", 300.0))
    eng = make_engine(qc)
    sym = _sym_in(qc, "MSFT")
    qc._position_meta[sym] = {"entry_date": datetime(2025, 1, 1), "entry_price": 290.0}
    bar = BarState(exit_intents=[_intent("MSFT", -5)])  # negative qty = sell
    eng._fire(FIRE_EXITS, _ctx_with(qc, bar))

    assert qc.orders == [(sym, -5)]
    assert eng._fired_exits == 1
    assert sym not in qc._position_meta  # meta popped on exit


def test_fire_adds_submits_positive_qty() -> None:
    qc = _fire_qc(("GOOG", 200.0))
    eng = make_engine(qc)
    sym = _sym_in(qc, "GOOG")
    bar = BarState(add_intents=[_intent("GOOG", 3)])
    eng._fire(FIRE_ADDS, _ctx_with(qc, bar))
    assert qc.orders == [(sym, 3)]
    assert eng._fired_adds == 1


def test_blocked_bar_suppresses_entries_and_adds_but_runs_exits() -> None:
    # Integration of the block-scope + _fire submission: on a regime-blocked bar the engine
    # skips FIRE_ENTRIES/FIRE_ADDS sentinels but still runs FIRE_EXITS. We populate the bar
    # via custom signal/exit/adds stub wrappers so the typed lists are non-empty, then assert
    # ONLY the exit order reaches the broker.
    qc = _fire_qc(("AAPL", 150.0), ("MSFT", 300.0), ("GOOG", 200.0))
    sym_msft = _sym_in(qc, "MSFT")
    qc._position_meta[sym_msft] = {"entry_date": datetime(2025, 1, 1), "entry_price": 290.0}

    eng = make_engine(
        qc,
        regime=slot("regime", blocked=True),
        portfolio_risk=slot("portfolio_risk"),
        adds=slot("adds"),
        exit_hard=slot("exit_hard"),
    )

    # Inject intents the way upstream phases would, by wrapping the relevant stubs' evaluate.
    def _populate(kind: str) -> None:
        phase = eng.phases[kind][0]
        orig = phase.evaluate

        def wrapped(ctx: PhaseContext):
            if kind == "signal":
                ctx.bar_state.sized_orders = [_intent("AAPL", 10)]
            elif kind == "adds":
                ctx.bar_state.add_intents = [_intent("GOOG", 4)]
            elif kind == "exit_hard":
                ctx.bar_state.exit_intents = [_intent("MSFT", -5)]
            return orig(ctx)

        phase.evaluate = wrapped  # type: ignore[method-assign]

    for k in ("signal", "adds", "exit_hard"):
        _populate(k)

    eng.on_data_with_ctx(_ctx_with(qc, BarState()))

    # Only the exit reached the broker; entries + adds were suppressed by the block.
    assert qc.orders == [(sym_msft, -5)]
    assert eng._fired_exits == 1
    assert eng._fired_entries == 0
    assert eng._fired_adds == 0
