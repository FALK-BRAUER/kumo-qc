"""Phase tests for DvRankCap — the rank+cap consumer of the filter's eligible set (#220/#238/R1).

Constructor: DvRankCap(DvRankCap.Params(...), logger=None). R1 un-fuse: this phase reads
`ctx.bar_state.eligible` (emitted by the filter phase), ranks DV-desc (ticker-asc tiebreak)
via `qc._trailing_dv`, caps to `qc.COARSE_MAX`, and emits `ranked_candidates` in rank order.
FakeQC carries `_trailing_dv` (dict, lowercase keys) + `COARSE_MAX` (int). The wiring
fail-loud (None → raise) moved to the FILTER phase; this phase consumes a bounded list, so it
only has the empty-no-raise branch.
"""
from datetime import datetime

from engine.context import BarState, PhaseContext
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap


class FakeQC:
    def __init__(self, trailing_dv=None, coarse_max=9999) -> None:
        self._trailing_dv = trailing_dv or {}
        self.COARSE_MAX = coarse_max


def make_ctx(qc, eligible, when=datetime(2025, 1, 2)):
    ctx = PhaseContext(qc=qc, time=when, data=None, bar_state=BarState())
    ctx.bar_state.eligible = eligible
    return ctx


def _phase():
    return DvRankCap(DvRankCap.Params(), logger=None)


def test_params_defaults():
    p = DvRankCap.Params()
    assert p.enabled is True
    # #238 dedup: NO coarse_max here — the cap (scan breadth) lives in lean_entry.COARSE_MAX
    # → read off qc (single source). A second coarse_max here was dead/drift-prone.
    assert not hasattr(p, "coarse_max")
    # Floors live in the filter phase; no floor/count params here.
    assert not hasattr(p, "min_price")
    assert not hasattr(p, "min_avg_dollar_volume")
    assert not hasattr(p, "max_positions")
    assert not hasattr(p, "max_slots")


def test_ranks_dv_desc():
    qc = FakeQC(trailing_dv={"aapl": 5.0e8, "msft": 9.0e8, "goog": 2.0e8})
    ctx = make_ctx(qc, eligible=["AAPL", "MSFT", "GOOG"])
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert result.decision == "ranked"
    assert ctx.bar_state.ranked_candidates == ["MSFT", "AAPL", "GOOG"]  # DV-desc
    assert result.facts["count"] == 3


def test_ticker_asc_tiebreak():
    qc = FakeQC(trailing_dv={"b": 5.0e8, "a": 5.0e8, "c": 9.0e8})  # a,b tie
    ctx = make_ctx(qc, eligible=["B", "A", "C"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["C", "A", "B"]  # c highest; a before b


def test_caps_at_coarse_max():
    qc = FakeQC(trailing_dv={"big": 1.0e9, "mid": 5.0e8, "small": 2.0e8}, coarse_max=2)
    ctx = make_ctx(qc, eligible=["BIG", "MID", "SMALL"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["BIG", "MID"]  # truncated to COARSE_MAX=2


def test_case_insensitive_dv_lookup():
    # eligible canonical UPPERCASE (from filter); _trailing_dv keys LOWERCASE. Lookup matches.
    qc = FakeQC(trailing_dv={"zzz": 1.0e9, "aaa": 2.0e8, "mmm": 5.0e8})
    ctx = make_ctx(qc, eligible=["ZZZ", "AAA", "MMM"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["ZZZ", "MMM", "AAA"]  # rank order, uppercase kept


def test_empty_eligible_returns_empty_no_raise():
    # Zero-candidate / pre-warmup day -> empty, NEVER raise.
    qc = FakeQC(trailing_dv={"aapl": 5.0e8})
    ctx = make_ctx(qc, eligible=[])
    result = _phase().evaluate(ctx)
    assert result.blocked is False
    assert ctx.bar_state.ranked_candidates == []
    assert result.decision == "empty"


def test_coarse_max_default_when_absent_on_qc():
    # qc without a COARSE_MAX attr -> getattr default 9999 (no truncation for a small set).
    class BareQC:
        def __init__(self): self._trailing_dv = {"a": 2.0, "b": 1.0}
    ctx = make_ctx(BareQC(), eligible=["A", "B"])
    _phase().evaluate(ctx)
    assert ctx.bar_state.ranked_candidates == ["A", "B"]


def test_version_marker():
    assert _phase().version_marker == "dv_rank_cap_v1"


def test_phase_metadata():
    assert DvRankCap.PHASE_KIND == "universe"
    # R1: depends on the FILTER kind (which PROVIDES "eligible"). The engine validates
    # REQUIRES_UPSTREAM against phase KINDS, not provides-strings (see test_champion_asis +
    # engine._validate_dependencies); "filter" precedes "universe" in PHASE_ORDER → valid.
    assert DvRankCap.REQUIRES_UPSTREAM == ["filter"]
    assert DvRankCap.PROVIDES_DOWNSTREAM == ["ranked_candidates"]
