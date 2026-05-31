"""Phase tests for DvRankCap — the exposer of the live-selected ranked order (#220/#238/Y).

Constructor: DvRankCap(DvRankCap.Params(...), logger=None). Under Y the floors+rank+cap happen
at the SELECTION GATE (lean_entry._coarse_selection); this phase reads the live-selected order
`qc._ranked_today` (list[str], lowercase, DV-desc rank) and emits ranked_candidates preserving
rank order ∩ active. FakeQC carries `_ranked_today` + `_active` (+ a `log` capture for the
diff-ladder rung). These cover the consumer contract, RANK-ORDER PRESERVATION (the #182 fix),
and the fail-loud / no-raise branches.
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
    def __init__(self, ranked_today=None, active=None) -> None:
        self._ranked_today = ranked_today
        self._active = {FakeSymbol(s) for s in (active or [])}
        self.logged: list[str] = []

    def log(self, msg: str) -> None:
        self.logged.append(msg)


def make_ctx(qc, when=datetime(2025, 1, 2)):
    return PhaseContext(qc=qc, time=when, data=None)


def _phase():
    return DvRankCap(DvRankCap.Params(), logger=None)


def test_params_defaults():
    p = DvRankCap.Params()
    assert p.enabled is True
    # The cap (scan breadth) lives at the selection gate (lean_entry.COARSE_MAX, single
    # source); a second coarse_max here was dead/drift-prone.
    assert not hasattr(p, "coarse_max")
    # Floors live at the selection gate; no floor/count params here.
    assert not hasattr(p, "min_price")
    assert not hasattr(p, "min_avg_dollar_volume")
    assert not hasattr(p, "max_positions")
    assert not hasattr(p, "max_slots")


def test_filters_to_today_tickers():
    # ranked_today is the LIVE-selected DV-desc list (uppercase or lowercase tolerated).
    qc = FakeQC(ranked_today=["MSFT", "AAPL", "GOOG"],
                active=["AAPL", "MSFT", "GOOG", "TSLA", "AMZN"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert set(ctx.bar_state.ranked_candidates) == {"AAPL", "MSFT", "GOOG"}
    assert result.facts["count"] == 3
    assert result.decision == "ranked"


def test_preserves_rank_order_not_active_set_order():
    # THE #182 fix at the consumer: output follows the LIVE RANK ORDER (_ranked_today),
    # NOT the iteration order of qc._active. ranked = [MSFT, AAPL, GOOG]; active in a
    # different order must NOT reorder the result.
    qc = FakeQC(ranked_today=["MSFT", "AAPL", "GOOG"], active=["GOOG", "AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["MSFT", "AAPL", "GOOG"]


def test_case_insensitive_lowercase_ranked_uppercase_active():
    # REAL-RUN case: ranked tickers are lowercase (zip stems / coarse value lowered); QC
    # Symbol.value is uppercase. The intersection must still match, and ranked_candidates
    # must carry the canonical _active value (uppercase) so signal's active_by_value hits.
    qc = FakeQC(ranked_today=["zzz", "aaa", "mmm"], active=["AAA", "MMM", "ZZZ"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["ZZZ", "AAA", "MMM"]  # rank order, uppercase


def test_active_subset_keeps_rank_order():
    qc = FakeQC(ranked_today=["ZZZ", "MMM", "AAA"], active=["AAA", "ZZZ"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["ZZZ", "AAA"]  # MMM dropped, order kept


def test_none_ranked_today_fails_loud():
    from engine.base import UniverseLoadError
    qc = FakeQC(ranked_today=None, active=["AAPL", "MSFT"])
    with pytest.raises(UniverseLoadError):
        _phase().evaluate(make_ctx(qc))


def test_empty_ranked_today_returns_empty_no_raise():
    # Zero-candidate / pre-warmup day -> empty, NEVER raise. The selection gate assigns [].
    qc = FakeQC(ranked_today=[], active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_emits_tracked_candidates_diff_ladder_rung():
    # Per-bar diff-ladder rung: count + sha256 of the emitted ranked_candidates (distinct from
    # the once-daily ACTIVE_SET selection rung in lean_entry).
    qc = FakeQC(ranked_today=["MSFT", "AAPL"], active=["AAPL", "MSFT"])
    ctx = make_ctx(qc)
    _phase().evaluate(ctx)
    assert any("TRACKED_CANDIDATES" in msg and "count=2" in msg for msg in qc.logged)


def test_version_marker():
    assert _phase().version_marker == "dv_rank_cap_v1"


def test_phase_metadata():
    assert DvRankCap.PHASE_KIND == "universe"
    assert DvRankCap.REQUIRES_UPSTREAM == []
    assert DvRankCap.PROVIDES_DOWNSTREAM == ["ranked_candidates"]
