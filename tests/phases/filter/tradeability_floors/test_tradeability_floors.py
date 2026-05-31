"""Phase tests for TradeabilityFloors — the filter consumer (#233 / #238).

Constructor: TradeabilityFloors(TradeabilityFloors.Params(...), logger=None). The floors
are applied LIVE inside runtime.universe_select.select_live_universe (run by lean_entry);
this phase EMITS the live-selected eligible set: `qc._ranked_today` ∩ active, sorted. These
cover the consumer contract + the #182 fail-loud / no-raise branches. The Params remain as
provenance for the floor values applied live.
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
    def __init__(self, ranked_today=None, active=None) -> None:
        self._ranked_today = ranked_today
        self._active = {FakeSymbol(s) for s in (active or [])}


def make_ctx(qc, when=datetime(2025, 1, 2)):
    return PhaseContext(qc=qc, time=when, data=None)


def _phase():
    return TradeabilityFloors(TradeabilityFloors.Params(), logger=None)


def test_params_defaults():
    p = TradeabilityFloors.Params()
    assert p.min_price == 10.0
    assert p.min_avg_dollar_volume == 100_000_000.0  # liquidity threshold (fintrack ruling)
    assert p.adv_window == 20
    assert p.enabled is True


def test_sets_eligible_intersected_with_active_sorted():
    # ranked_today is the LIVE-selected set (already cleared the floors). Filter emits it ∩
    # active, sorted (rank is the universe phase's job).
    qc = FakeQC(ranked_today=["MSFT", "AAPL", "GOOG"], active=["AAPL", "MSFT", "GOOG", "TSLA"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert result.decision == "eligible"
    assert ctx.bar_state.eligible == ["AAPL", "GOOG", "MSFT"]  # sorted, TSLA not selected
    assert result.facts["count"] == 3


def test_active_intersection_excludes_inactive():
    qc = FakeQC(ranked_today=["AAPL", "MSFT", "NVDA"], active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAPL", "MSFT"]  # NVDA selected but not yet subscribed


def test_case_insensitive_lowercase_ranked_uppercase_active():
    # ranked lowercase (zip stems / coarse lowered), QC _active uppercase — match
    # case-insensitively, emit canonical value (sorted).
    qc = FakeQC(ranked_today=["aaa", "msft"], active=["AAA", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAA", "MSFT"]


def test_none_ranked_today_fails_loud():
    from engine.base import UniverseLoadError
    qc = FakeQC(ranked_today=None, active=["AAPL"])
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(make_ctx(qc))


def test_empty_ranked_today_returns_empty_no_raise():
    # Zero-candidate / pre-warmup day -> empty, NEVER raise. The live selection assigns [].
    qc = FakeQC(ranked_today=[], active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.eligible == []
    assert result.decision == "empty"


def test_version_marker():
    assert _phase().version_marker == "tradeability_floors_v1"


def test_phase_metadata():
    assert TradeabilityFloors.PHASE_KIND == "filter"
    assert TradeabilityFloors.REQUIRES_UPSTREAM == []
    assert TradeabilityFloors.PROVIDES_DOWNSTREAM == ["eligible"]
