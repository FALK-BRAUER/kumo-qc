"""Phase tests for TradeabilityFloors — the filter consumer (#233).

Constructor: TradeabilityFloors(TradeabilityFloors.Params(...), logger=None). Reads the
precomputed `qc._eligible` (date -> {ticker: dv}) and emits bar_state.eligible = eligible
∩ active. Floor math lives in build_filter; these cover the consumer contract + #182
fail-loud / no-raise branches.
"""
from datetime import datetime

import pytest

from engine.context import PhaseContext
from phases.filter.tradeability_floors.tradeability_floors import TradeabilityFloors


class FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeSymbol) and self.value == other.value


class FakeQC:
    def __init__(self, eligible=None, active=None) -> None:
        self._eligible = eligible
        self._active = {FakeSymbol(s) for s in (active or [])}


def make_ctx(qc, when=datetime(2025, 1, 2)):
    return PhaseContext(qc=qc, time=when, data=None)


# Filter artifact form: date -> {ticker: dv}.
SAMPLE = {
    "2025-01-02": {"AAPL": 9e8, "MSFT": 8e8, "GOOG": 7e8},
    "2025-01-03": {"AAPL": 9e8, "TSLA": 6e8},
    "2025-01-06": {"MSFT": 8e8, "AMZN": 5e8},
}


def _phase():
    return TradeabilityFloors(TradeabilityFloors.Params(), logger=None)


def test_params_defaults():
    p = TradeabilityFloors.Params()
    assert p.min_price == 10.0
    assert p.min_avg_dollar_volume == 5_000_000.0
    assert p.adv_window == 20
    assert p.enabled is True


def test_sets_eligible_intersected_with_active_sorted():
    qc = FakeQC(eligible=SAMPLE, active=["AAPL", "MSFT", "GOOG", "TSLA"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert result.decision == "eligible"
    # eligible has no rank -> sorted for determinism; GOOG/MSFT/AAPL all active.
    assert ctx.bar_state.eligible == ["AAPL", "GOOG", "MSFT"]
    assert result.facts["count"] == 3


def test_active_intersection_excludes_inactive():
    qc = FakeQC(eligible={"2025-01-02": {"AAPL": 1.0, "MSFT": 1.0, "NVDA": 1.0}}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAPL", "MSFT"]  # NVDA eligible but not active


def test_accepts_list_form_too():
    # Robust to a list-valued artifact (membership only), not just the {ticker: dv} dict.
    qc = FakeQC(eligible={"2025-01-02": ["MSFT", "AAPL"]}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAPL", "MSFT"]


def test_none_eligible_fails_loud():
    from engine.base import UniverseLoadError
    qc = FakeQC(eligible=None, active=["AAPL"])
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(make_ctx(qc))


def test_missing_date_returns_empty_no_raise():
    # 2025-01-04 within range but absent (weekend/holiday) -> empty, NEVER raise (#182).
    qc = FakeQC(eligible=SAMPLE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2025, 1, 4))
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.eligible == []
    assert result.decision == "empty"


def test_below_range_returns_empty():
    qc = FakeQC(eligible=SAMPLE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2024, 12, 1))
    result = _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == []
    assert result.decision == "empty"


def test_zero_eligible_day_is_empty_not_blocked():
    qc = FakeQC(eligible={"2025-01-02": {}}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.eligible == []


def test_version_marker():
    assert _phase().version_marker == "tradeability_floors_v1"


def test_phase_metadata():
    assert TradeabilityFloors.PHASE_KIND == "filter"
    assert TradeabilityFloors.REQUIRES_UPSTREAM == []
    assert TradeabilityFloors.PROVIDES_DOWNSTREAM == ["eligible"]
