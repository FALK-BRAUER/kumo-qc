import pytest
from datetime import datetime
from engine.context import PhaseContext
from engine.base import UniverseLoadError
from phases.universe.polygon_local.polygon_local import PolygonLocal


class FakeSymbol:
    def __init__(self, value):
        self.value = value
    def __hash__(self):
        return hash(self.value)
    def __eq__(self, other):
        return self.value == other.value


class FakeQC:
    def __init__(self, polygon_universe=None, active=None):
        self._polygon_universe = polygon_universe
        self._active = {FakeSymbol(s) for s in (active or [])}


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


SAMPLE_UNIVERSE = {
    "2025-01-02": ["AAPL", "MSFT", "GOOG"],
    "2025-01-03": ["AAPL", "TSLA"],
    "2025-01-06": ["MSFT", "AMZN"],
}


def test_filters_to_today_tickers():
    qc = FakeQC(
        polygon_universe=SAMPLE_UNIVERSE,
        active=["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"],
    )
    phase = PolygonLocal(params={}, logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)

    assert result.blocked is False
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT", "GOOG"}


def test_filters_out_non_active_symbols():
    qc = FakeQC(
        polygon_universe={"2025-01-02": ["AAPL", "MSFT", "NVDA"]},
        active=["AAPL", "MSFT"],  # NVDA not active
    )
    phase = PolygonLocal(params={}, logger=None)
    ctx = make_ctx(qc)
    phase.evaluate(ctx)
    assert "NVDA" not in ctx.bar_state.ranked_candidates


def test_no_universe_returns_all_active():
    qc = FakeQC(polygon_universe=None, active=["AAPL", "MSFT"])
    phase = PolygonLocal(params={}, logger=None)
    ctx = make_ctx(qc)
    result = phase.evaluate(ctx)
    assert result.blocked is False
    assert len(ctx.bar_state.ranked_candidates) == 2


def test_date_outside_range_returns_empty():
    qc = FakeQC(polygon_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    # Use 2026-01-02 which is outside max(keys)="2025-01-06"
    ctx = PhaseContext(qc=qc, time=datetime(2026, 1, 2), data=None)
    phase = PolygonLocal(params={}, logger=None)
    result = phase.evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == []
    assert result.blocked is False


def test_date_in_range_but_missing_raises_universe_error():
    universe = {"2025-01-02": ["AAPL"], "2025-01-06": ["MSFT"]}
    qc = FakeQC(polygon_universe=universe, active=["AAPL", "MSFT"])
    # 2025-01-03 is within range (between 01-02 and 01-06) but not a key
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 3), data=None)
    phase = PolygonLocal(params={}, logger=None)
    with pytest.raises(UniverseLoadError, match="date-key mismatch"):
        phase.evaluate(ctx)


def test_universe_never_blocks():
    qc = FakeQC(polygon_universe=SAMPLE_UNIVERSE, active=["AAPL"])
    phase = PolygonLocal(params={}, logger=None)
    result = phase.evaluate(make_ctx(qc))
    assert result.blocked is False
