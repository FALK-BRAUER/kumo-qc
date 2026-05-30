"""Phase tests for LiquidSubstrate — the floors-only universe consumer.

Constructor: LiquidSubstrate(LiquidSubstrate.Params(...), logger=None). The phase reads
the precomputed `qc._universe` (date -> eligible-set) and intersects with `qc._active`.
The floors live in the precompute (build_universe.py); the phase only consumes + filters,
so these tests cover the consumer contract: today-filter, active-intersection, and the
three #182 fail-loud / no-raise branches.
"""
from datetime import datetime

import pytest

from engine.context import PhaseContext
from phases.universe.liquid_substrate.liquid_substrate import LiquidSubstrate


class FakeSymbol:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeSymbol) and self.value == other.value


class FakeQC:
    def __init__(self, universe=None, active=None) -> None:
        self._universe = universe
        self._active = {FakeSymbol(s) for s in (active or [])}


def make_ctx(qc, when=datetime(2025, 1, 2)):
    return PhaseContext(qc=qc, time=when, data=None)


SAMPLE_UNIVERSE = {
    "2025-01-02": ["AAPL", "MSFT", "GOOG"],
    "2025-01-03": ["AAPL", "TSLA"],
    "2025-01-06": ["MSFT", "AMZN"],
}


def _phase():
    return LiquidSubstrate(LiquidSubstrate.Params(), logger=None)


def test_params_defaults_are_the_floors():
    p = LiquidSubstrate.Params()
    assert p.min_price == 5.0
    assert p.min_avg_dollar_volume == 5_000_000.0
    assert p.adv_window == 20
    assert p.enabled is True
    # No count cap of any kind on the params (model is floors-only).
    assert not hasattr(p, "n")
    assert not hasattr(p, "max_positions")


def test_filters_to_today_tickers():
    qc = FakeQC(universe=SAMPLE_UNIVERSE, active=["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT", "GOOG"}
    assert result.facts["count"] == 3
    assert result.decision == "liquid"


def test_filters_to_active_intersection():
    qc = FakeQC(universe={"2025-01-02": ["AAPL", "MSFT", "NVDA"]}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    # NVDA is in today's set but not active -> excluded.
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT"}
    assert "NVDA" not in ctx.bar_state.ranked_candidates


def test_none_universe_fails_loud_never_passes_through():
    # #182 fall-through trap: None universe must RAISE, never trade-the-whole-substrate (~19k).
    from engine.base import UniverseLoadError
    qc = FakeQC(universe=None, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(ctx)


def test_date_below_range_returns_empty_no_raise():
    qc = FakeQC(universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2024, 12, 1))  # before min key
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_date_above_range_returns_empty_no_raise():
    qc = FakeQC(universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2026, 1, 2))  # after max key
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []


def test_in_range_missing_date_returns_empty_no_raise():
    # 2025-01-04 (Saturday) is within [2025-01-02, 2025-01-06] but absent.
    # #182 weekend trap: missing date (weekend/holiday/zero-eligible) = empty, NEVER raise.
    qc = FakeQC(universe=SAMPLE_UNIVERSE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2025, 1, 4))
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_empty_today_set_is_empty_not_blocked():
    # A precomputed zero-eligible day (present key, empty list) -> empty candidates, no block.
    qc = FakeQC(universe={"2025-01-02": []}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []


def test_never_blocks_on_normal_path():
    qc = FakeQC(universe=SAMPLE_UNIVERSE, active=["AAPL"])
    result = _phase().evaluate(make_ctx(qc))
    assert result.blocked is False


def test_version_marker():
    assert _phase().version_marker == "liquid_substrate_v1"


def test_phase_metadata():
    assert LiquidSubstrate.PHASE_KIND == "universe"
    assert LiquidSubstrate.REQUIRES_UPSTREAM == []
    assert LiquidSubstrate.PROVIDES_DOWNSTREAM == ["ranked_candidates"]
