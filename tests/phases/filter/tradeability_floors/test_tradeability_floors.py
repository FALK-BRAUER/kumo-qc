"""Phase tests for TradeabilityFloors — the REAL filter, applied FIRST (#233 / #238 / R1).

Constructor: TradeabilityFloors(TradeabilityFloors.Params(...), logger=None). R1 un-fuse: the
floors are APPLIED HERE (apply_floors over qc._bar_metrics), no longer a re-expose of a
precomputed _ranked_today. FakeQC carries `_bar_metrics` (dict {ticker_lower: (close, dv)}) +
`_active` (set of FakeSymbol .value). Covers the floor math, the ∩active case-insensitive
canonical emit, and the #182 fail-loud / no-raise branches.
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
    def __init__(self, bar_metrics=None, active=None) -> None:
        self._bar_metrics = bar_metrics
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


def test_applies_floors_by_price_and_dv():
    # R1: the floors are FUNCTIONAL here. Names below EITHER floor are dropped.
    bm = {
        "aapl": (200.0, 5.0e8),   # passes both
        "msft": (400.0, 9.0e8),   # passes both
        "cheap": (5.0, 9.0e8),    # below price floor -> dropped
        "thin": (200.0, 5.0e7),   # below dv floor -> dropped
    }
    qc = FakeQC(bar_metrics=bm, active=["AAPL", "MSFT", "CHEAP", "THIN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert result.decision == "eligible"
    assert ctx.bar_state.eligible == ["AAPL", "MSFT"]  # sorted; cheap+thin floored out
    assert result.facts["count"] == 2


def test_intersection_with_active_excludes_unsubscribed():
    # A name that clears the floors but is NOT yet subscribed (not in _active) is excluded.
    bm = {"aapl": (200.0, 5.0e8), "nvda": (500.0, 9.0e8)}
    qc = FakeQC(bar_metrics=bm, active=["AAPL"])  # NVDA passed floors but not subscribed
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAPL"]


def test_case_insensitive_emits_canonical_uppercase():
    # bar_metrics keys lowercase (zip stems); QC _active uppercase. Match case-insensitively,
    # emit the canonical uppercase Symbol.value, sorted.
    bm = {"aaa": (50.0, 2.0e8), "msft": (300.0, 5.0e8)}
    qc = FakeQC(bar_metrics=bm, active=["AAA", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AAA", "MSFT"]


def test_boundary_inclusive_at_floors():
    bm = {"at": (10.0, 1.0e8), "belowp": (9.99, 1.0e9), "belowdv": (50.0, 99_999_999.0)}
    qc = FakeQC(bar_metrics=bm, active=["AT", "BELOWP", "BELOWDV"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == ["AT"]  # >= inclusive; the two below-floor names dropped


def test_none_bar_metrics_fails_loud():
    from engine.base import UniverseLoadError
    qc = FakeQC(bar_metrics=None, active=["AAPL"])
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(make_ctx(qc))


def test_empty_bar_metrics_returns_empty_no_raise():
    # Zero-candidate / pre-warmup day -> empty, NEVER raise. The shared upstream assigns {}.
    qc = FakeQC(bar_metrics={}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.eligible == []
    assert result.decision == "empty"


def test_all_floored_out_yields_empty_eligible():
    # Non-empty metrics but every name below a floor -> empty eligible, decision="eligible"
    # (the floors ran; there were just no survivors). NOT the empty-upstream branch.
    bm = {"cheap": (1.0, 9.0e8), "thin": (200.0, 1.0e6)}
    qc = FakeQC(bar_metrics=bm, active=["CHEAP", "THIN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert ctx.bar_state.eligible == []
    assert result.decision == "eligible"


def test_version_marker():
    assert _phase().version_marker == "tradeability_floors_v1"


def test_phase_metadata():
    assert TradeabilityFloors.PHASE_KIND == "filter"
    assert TradeabilityFloors.REQUIRES_UPSTREAM == []
    assert TradeabilityFloors.PROVIDES_DOWNSTREAM == ["eligible"]
