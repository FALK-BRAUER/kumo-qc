"""Behavioral tests for the BctEntryConfirm entry_selection phase (#253).

The pure §4-Gate-2 component logic is golden-mastered in test_methodology_golden_master.py; this
file tests the PHASE behavior over the bar_state.sized_orders gate: a CONFIRMED candidate passes,
an UNCONFIRMED one is dropped, each sub-gate failure declines, edge/null states (no indicators /
not ready / no candidates) decline safely, the X/4 score is published, and the phase never blocks.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm


# --- QC-shaped fakes: the exact accessors _score_candidate reads. ---


class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, tenkan: float, kijun: float, sa: float, sb: float, ready: bool = True) -> None:
        self.tenkan = _Ind(tenkan)
        self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa)
        self.senkou_b = _Ind(sb)
        self.is_ready = ready


class _Window:
    def __init__(self, vals: list[float]) -> None:
        self._v = vals  # index 0 = most recent

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


class _Macd:
    def __init__(self, ready: bool = True) -> None:
        self.is_ready = ready


class _TBounce:
    def __init__(self, sessions: int = 0, gap: float = 0.0) -> None:
        self.sessions_below_tenkan = sessions
        self.gap_up_frac = gap


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: Any) -> bool:
        return self.value == other.value


class _Sec:
    def __init__(self, price: float, volume: float) -> None:
        self.price = price
        self.volume = volume


class _QC:
    def __init__(self) -> None:
        self._active: set[Any] = set()
        self.securities: dict[Any, _Sec] = {}
        self._indicators: dict[Any, dict[str, Any]] = {}


def _confirmed_ind() -> dict[str, Any]:
    """A fully-CONFIRMING (4/4) maintained-indicator state for price=100, volume=200k."""
    return {
        "d_ichi": _Ichi(tenkan=99.7, kijun=95.0, sa=90.0, sb=80.0),
        "macd": _Macd(ready=True),
        "macd_hist_window": _Window([0.5, 0.2]),  # positive, turning up
        "vol_sma20": _Ind(100_000.0),
        "tbounce": _TBounce(sessions=0, gap=0.0),
    }


def _add(qc: _QC, name: str, price: float, volume: float, ind: dict[str, Any]) -> _Sym:
    sym = _Sym(name)
    qc._active.add(sym)
    qc.securities[sym] = _Sec(price, volume)
    qc._indicators[sym] = ind
    return sym


def _ctx(qc: _QC, tickers: list[str]) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 2), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=t, qty=0, price=0.0, stop=0.0, module="signal.stub", risk_dollars=0.0)
        for t in tickers
    ]
    return ctx


def _phase(**kw: Any) -> BctEntryConfirm:
    return BctEntryConfirm(BctEntryConfirm.Params(**kw), logger=None)


# --- FIRE: a confirmed candidate passes the gate. ---


def test_fire_confirmed_candidate_passes() -> None:
    qc = _QC()
    _add(qc, "AAPL", 100.0, 200_000.0, _confirmed_ind())
    ctx = _ctx(qc, ["AAPL"])
    res = _phase().evaluate(ctx)
    assert [o.ticker for o in ctx.bar_state.sized_orders] == ["AAPL"]
    assert res.facts["confirmed"] == 1
    assert res.facts["declined"] == 0
    assert qc._entry_confirm["AAPL"] == 4  # 4/4 published


# --- DECLINE: each sub-gate failure drops the candidate. ---


def test_decline_volume_below_gate() -> None:
    qc = _QC()
    _add(qc, "AAPL", 100.0, 90_000.0, _confirmed_ind())  # vol < 1.0x avg -> C4 fails (mandatory)
    ctx = _ctx(qc, ["AAPL"])
    res = _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
    assert res.facts["declined"] == 1
    assert qc._entry_confirm["AAPL"] == 3  # scored 3/4 but volume mandatory -> declined


def test_decline_regime_fail() -> None:
    qc = _QC()
    ind = _confirmed_ind()
    ind["d_ichi"] = _Ichi(tenkan=94.0, kijun=95.0, sa=90.0, sb=80.0)  # T<K -> C1 fails (mandatory)
    _add(qc, "AAPL", 100.0, 200_000.0, ind)
    ctx = _ctx(qc, ["AAPL"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_decline_macd_negative_turning_down() -> None:
    qc = _QC()
    ind = _confirmed_ind()
    ind["macd_hist_window"] = _Window([-0.5, -0.2])  # negative turning down -> C3 fails
    _add(qc, "AAPL", 100.0, 200_000.0, ind)
    ctx = _ctx(qc, ["AAPL"])
    res = _phase().evaluate(ctx)
    # C1+C2+C4 still pass = 3/4 with mandatory regime+volume -> still QUALIFIES at min=2.
    assert [o.ticker for o in ctx.bar_state.sized_orders] == ["AAPL"]
    assert qc._entry_confirm["AAPL"] == 3


def test_decline_min_confirm_4_requires_all() -> None:
    qc = _QC()
    ind = _confirmed_ind()
    ind["macd_hist_window"] = _Window([-0.5, -0.2])  # C3 fails -> 3/4
    _add(qc, "AAPL", 100.0, 200_000.0, ind)
    ctx = _ctx(qc, ["AAPL"])
    _phase(min_confirm=4).evaluate(ctx)  # require 4/4
    assert ctx.bar_state.sized_orders == []  # 3/4 < 4 -> declined


def test_gate_reduces_count_mixed() -> None:
    qc = _QC()
    _add(qc, "PASS", 100.0, 200_000.0, _confirmed_ind())
    bad = _confirmed_ind()
    bad["vol_sma20"] = _Ind(500_000.0)  # 200k < 1.0x*500k -> C4 fails
    _add(qc, "FAIL", 100.0, 200_000.0, bad)
    ctx = _ctx(qc, ["PASS", "FAIL"])
    res = _phase().evaluate(ctx)
    assert [o.ticker for o in ctx.bar_state.sized_orders] == ["PASS"]
    assert res.facts["confirmed"] == 1 and res.facts["declined"] == 1


# --- EDGE / NULL: missing/not-ready indicators, no candidates, inactive symbol. ---


def test_edge_no_indicators_declines() -> None:
    qc = _QC()
    sym = _Sym("AAPL")
    qc._active.add(sym)
    qc.securities[sym] = _Sec(100.0, 200_000.0)
    # no qc._indicators entry
    ctx = _ctx(qc, ["AAPL"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_edge_indicator_not_ready_declines() -> None:
    qc = _QC()
    ind = _confirmed_ind()
    ind["macd"] = _Macd(ready=False)  # not ready
    _add(qc, "AAPL", 100.0, 200_000.0, ind)
    ctx = _ctx(qc, ["AAPL"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


def test_edge_inactive_symbol_declines() -> None:
    qc = _QC()
    # candidate not in _active
    ctx = _ctx(qc, ["GHOST"])
    res = _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
    assert res.facts["declined"] == 1


def test_edge_empty_candidates() -> None:
    qc = _QC()
    ctx = _ctx(qc, [])
    res = _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []
    assert res.facts == {"confirmed": 0, "declined": 0, "scores": {}}


def test_edge_macd_window_too_short_declines() -> None:
    qc = _QC()
    ind = _confirmed_ind()
    ind["macd_hist_window"] = _Window([0.5])  # count < 2 -> can't compute turning
    _add(qc, "AAPL", 100.0, 200_000.0, ind)
    ctx = _ctx(qc, ["AAPL"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.sized_orders == []


# --- Phase contract: never blocks; deterministic. ---


def test_phase_never_blocks() -> None:
    qc = _QC()
    _add(qc, "AAPL", 100.0, 200_000.0, _confirmed_ind())
    res = _phase().evaluate(_ctx(qc, ["AAPL"]))
    assert res.blocked is False


def test_phase_deterministic() -> None:
    qc = _QC()
    _add(qc, "AAPL", 100.0, 200_000.0, _confirmed_ind())
    out1 = _phase().evaluate(_ctx(qc, ["AAPL"])).facts["confirmed"]
    out2 = _phase().evaluate(_ctx(qc, ["AAPL"])).facts["confirmed"]
    assert out1 == out2 == 1


def test_version_marker() -> None:
    assert _phase().version_marker == "bct_entry_confirm_v1"
