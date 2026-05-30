"""Phase tests for DvRankCap — the rank+cap universe consumer (#220).

Constructor: DvRankCap(DvRankCap.Params(...), logger=None). Reads the precomputed
`qc._universe` (date -> [ranked tickers]) and emits ranked_candidates preserving rank
order ∩ active. Rank/cap math lives in build_universe; these cover the consumer contract,
RANK-ORDER PRESERVATION (the #182 fix), and the fail-loud / no-raise branches.
"""
from datetime import datetime

import pytest

from engine.context import PhaseContext
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


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


# Lists are DV-desc RANK ORDER as emitted by build_universe (not alphabetical).
SAMPLE = {
    "2025-01-02": ["MSFT", "AAPL", "GOOG"],
    "2025-01-03": ["AAPL", "TSLA"],
    "2025-01-06": ["MSFT", "AMZN"],
}


def _phase():
    return DvRankCap(DvRankCap.Params(), logger=None)


def test_params_defaults():
    p = DvRankCap.Params()
    assert p.coarse_max == 9999  # scan-breadth cap, unbounded baseline
    assert p.enabled is True
    # Floors moved OUT to the filter phase; no floor params here.
    assert not hasattr(p, "min_price")
    assert not hasattr(p, "min_avg_dollar_volume")
    # coarse_max is scan breadth, NOT a position/slot count cap.
    assert not hasattr(p, "max_positions")
    assert not hasattr(p, "max_slots")


def test_filters_to_today_tickers():
    qc = FakeQC(universe=SAMPLE, active=["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT", "GOOG"}
    assert result.facts["count"] == 3
    assert result.decision == "ranked"


def test_preserves_rank_order_not_active_set_order():
    # THE #182 fix at the consumer: output follows the precomputed RANK ORDER (today_list),
    # NOT the iteration order of qc._active. today_list = [MSFT, AAPL, GOOG]; active in a
    # different order must NOT reorder the result.
    qc = FakeQC(universe=SAMPLE, active=["GOOG", "AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["MSFT", "AAPL", "GOOG"]


def test_case_insensitive_lowercase_artifact_uppercase_active():
    # REAL-RUN case: artifact tickers are lowercase (zip stems); QC Symbol.value is
    # uppercase. The intersection must still match, and ranked_candidates must carry the
    # canonical _active value (uppercase) so the signal phase's active_by_value[ticker] hits.
    qc = FakeQC(universe={"2025-01-02": ["zzz", "aaa", "mmm"]}, active=["AAA", "MMM", "ZZZ"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["ZZZ", "AAA", "MMM"]  # rank order, uppercase


def test_active_subset_keeps_rank_order():
    qc = FakeQC(universe={"2025-01-02": ["ZZZ", "MMM", "AAA"]}, active=["AAA", "ZZZ"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["ZZZ", "AAA"]  # MMM dropped, order kept


def test_none_universe_fails_loud():
    from engine.base import UniverseLoadError
    qc = FakeQC(universe=None, active=["AAPL", "MSFT"])
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(make_ctx(qc))


def test_missing_date_returns_empty_no_raise():
    # 2025-01-04 within range but absent -> empty, NEVER raise (#182 weekend trap).
    qc = FakeQC(universe=SAMPLE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2025, 1, 4))
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_below_range_returns_empty():
    qc = FakeQC(universe=SAMPLE, active=["AAPL"])
    ctx = make_ctx(qc, when=datetime(2024, 12, 1))
    result = _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == []


def test_zero_candidate_day_is_empty_not_blocked():
    qc = FakeQC(universe={"2025-01-02": []}, active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []


def test_version_marker():
    assert _phase().version_marker == "dv_rank_cap_v1"


def test_phase_metadata():
    assert DvRankCap.PHASE_KIND == "universe"
    assert DvRankCap.REQUIRES_UPSTREAM == []
    assert DvRankCap.PROVIDES_DOWNSTREAM == ["ranked_candidates"]
