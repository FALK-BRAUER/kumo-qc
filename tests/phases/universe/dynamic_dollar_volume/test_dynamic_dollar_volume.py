"""v2-delta: constructor is DynamicDollarVolume(DynamicDollarVolume.Params(...), logger=None).

Mirrors v1 polygon_local test style, adapted to _dynamic_universe.
"""
from datetime import datetime

import pytest


from engine.context import PhaseContext
from phases.universe.dynamic_dollar_volume.dynamic_dollar_volume import DynamicDollarVolume


class FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeSymbol) and self.value == other.value


class FakeQC:
    def __init__(self, dynamic_universe=None, active=None) -> None:
        self._dynamic_universe = dynamic_universe
        self._active = {FakeSymbol(s) for s in (active or [])}


class RecordingLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def make_ctx(qc, when=datetime(2025, 1, 2)):
    return PhaseContext(qc=qc, time=when, data=None)


SAMPLE_UNIVERSE = {
    "2025-01-02": ["AAPL", "MSFT", "GOOG"],
    "2025-01-03": ["AAPL", "TSLA"],
    "2025-01-06": ["MSFT", "AMZN"],
}


def _phase():
    return DynamicDollarVolume(DynamicDollarVolume.Params(), logger=None)


def test_filters_to_today_tickers():
    qc = FakeQC(dynamic_universe=SAMPLE_UNIVERSE, active=["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT", "GOOG"}
    assert result.facts["count"] == 3


def test_filters_to_active_intersection():
    qc = FakeQC(dynamic_universe={"2025-01-02": ["AAPL", "MSFT", "NVDA"]}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    # NVDA is in today's set but not active -> excluded.
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT"}
    assert "NVDA" not in ctx.bar_state.ranked_candidates


def test_none_universe_fails_loud_never_passes_through():
    # #182 fall-through trap: None universe must RAISE, never trade-the-whole-substrate (~19k).
    from engine.base import UniverseLoadError
    qc = FakeQC(dynamic_universe=None, active=["AAPL", "MSFT"])
    phase = DynamicDollarVolume(DynamicDollarVolume.Params(), logger=None)
    ctx = make_ctx(qc)
    with pytest.raises(UniverseLoadError):
        phase.evaluate(ctx)


def test_date_below_range_returns_empty_no_raise():
    qc = FakeQC(dynamic_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2024, 12, 1))  # before min key
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_date_above_range_returns_empty_no_raise():
    qc = FakeQC(dynamic_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2026, 1, 2))  # after max key
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []


def test_in_range_missing_date_returns_empty_no_raise():
    # 2025-01-04 (Saturday) is within [2025-01-02, 2025-01-06] but absent.
    # #182 lesson: missing date (weekend/holiday/zero-eligible) = empty, NEVER raise.
    qc = FakeQC(dynamic_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2025, 1, 4))
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_never_blocks_on_normal_path():
    qc = FakeQC(dynamic_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    result = _phase().evaluate(make_ctx(qc))
    assert result.blocked is False


def test_version_marker():
    assert _phase().version_marker == "dynamic_dollar_volume_v1"


def test_phase_metadata():
    assert DynamicDollarVolume.PHASE_KIND == "universe"
    assert DynamicDollarVolume.REQUIRES_UPSTREAM == []
    assert DynamicDollarVolume.PROVIDES_DOWNSTREAM == ["ranked_candidates"]
