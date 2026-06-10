from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.context import OrderIntent, PhaseContext
from phases.entry_selection.rank_aware_gap_confirm.rank_aware_gap_confirm import (
    RankAwareGapConfirm,
    rank_aware_gap_confirm_decision,
)


def _d(**kw: Any) -> tuple[bool, str, str]:
    defaults = {
        "scanner_rank": 1,
        "gap_pct": 0.03,
        "curr_vol": 90.0,
        "vol_mean": 100.0,
        "bars_elapsed": 1,
        "window_bars": 6,
        "top_rank_max": 10,
        "mid_rank_max": 20,
        "top_gap_threshold": 0.025,
        "top_vol_mult": 0.8,
        "mid_gap_threshold": 0.03,
        "mid_vol_mult": 1.0,
        "tail_gap_threshold": 0.05,
        "tail_vol_mult": 1.25,
    }
    defaults.update(kw)
    return rank_aware_gap_confirm_decision(**defaults)


def test_top_rank_can_confirm_with_looser_volume() -> None:
    assert _d(scanner_rank=3, gap_pct=0.03, curr_vol=85.0) == (True, "top_confirmed", "top")


def test_mid_rank_uses_canonical_volume_gate() -> None:
    assert _d(scanner_rank=15, gap_pct=0.03, curr_vol=90.0) == (False, "mid_quiet_open", "mid")
    assert _d(scanner_rank=15, gap_pct=0.03, curr_vol=100.0) == (True, "mid_confirmed", "mid")


def test_tail_rank_requires_stronger_gap() -> None:
    assert _d(scanner_rank=35, gap_pct=0.04, curr_vol=200.0) == (False, "tail_gap_too_small", "tail")
    assert _d(scanner_rank=35, gap_pct=0.06, curr_vol=130.0) == (True, "tail_confirmed", "tail")


def test_missing_scanner_context_declines() -> None:
    assert _d(scanner_rank=None) == (False, "no_scanner_context", "missing")


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _VolWindow:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    @property
    def count(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int) -> float:
        return self._values[index]


class _Bar:
    def __init__(self, volume: float) -> None:
        self.volume = volume


class _QC:
    def __init__(self, sym: _Sym, *, signal_price: float, scanner_rank: int | None) -> None:
        self._active = {sym}
        snap: dict[str, Any] = {"signal_price": signal_price, "daily_kijun": 95.0, "decision_date": "T"}
        if scanner_rank is not None:
            snap["scanner_rank"] = scanner_rank
            snap["scanner_score"] = 1.23
        self._snaps = {sym: snap}
        self._intraday: dict[Any, dict[str, Any]] = {}
        self._entry_confirm: dict[str, Any] = {}

    def snapshot_for_entry(self, sym: Any) -> Any:
        return self._snaps.get(sym)


def _phase(**kw: Any) -> RankAwareGapConfirm:
    return RankAwareGapConfirm(RankAwareGapConfirm.Params(**kw), logger=None)


def _ctx(qc: _QC, ticker: str) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 2, 4), data=None)
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker=ticker, qty=0, price=0.0, stop=0.0, module="signal", risk_dollars=0.0)
    ]
    return ctx


def test_phase_confirms_top_rank_with_loose_thresholds() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym, signal_price=100.0, scanner_rank=4)
    qc._intraday[sym] = {"vol_window": _VolWindow([100.0, 100.0]), "last_close": 103.0, "last_bar": _Bar(85.0)}
    ctx = _ctx(qc, "aapl")

    result = _phase().evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["aapl"]
    assert qc._entry_confirm["aapl"]["confirmed"] is True
    assert result.facts["bucket_top"] == 1


def test_phase_declines_without_scanner_rank() -> None:
    sym = _Sym("AAPL")
    qc = _QC(sym, signal_price=100.0, scanner_rank=None)
    qc._intraday[sym] = {"vol_window": _VolWindow([100.0]), "last_close": 106.0, "last_bar": _Bar(500.0)}
    ctx = _ctx(qc, "aapl")

    result = _phase().evaluate(ctx)

    assert ctx.bar_state.sized_orders == []
    assert result.facts["reason_no_scanner_context"] == 1


def test_space_and_complexity() -> None:
    assert RankAwareGapConfirm.Params.space().axes == {}
    assert RankAwareGapConfirm.COMPLEXITY.free_params == 0
