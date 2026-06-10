"""Tests for the sizing catalog (phases.sizing.library, ADR D3 — first sizing catalog).

Mirrors tests/phases/entry_selection/test_entry_selection_library.py: a typed tuple of DIRECT
CLASS REFS (not strings), each member protocol-conforming and exposing space()/COMPLEXITY for
the #214 sweep runner.
"""
from __future__ import annotations

from engine.base import PhaseInterface
from phases.shared.param_space import ComplexityDecl, ParamSpace
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.sizing.library import SIZING_PHASES
from phases.sizing.rank_aware_heatcap.rank_aware_heatcap import RankAwareHeatcap
from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap


def test_catalog_is_a_tuple_of_classes_not_strings() -> None:
    assert isinstance(SIZING_PHASES, tuple)
    for impl in SIZING_PHASES:
        assert isinstance(impl, type), "catalog holds class refs, never name strings"


def test_both_sizers_are_catalogued() -> None:
    assert FlatPctHeatcap in SIZING_PHASES
    assert ScoreTierHeatcap in SIZING_PHASES
    assert RankAwareHeatcap in SIZING_PHASES


def test_every_catalogued_phase_declares_sizing_kind() -> None:
    for impl in SIZING_PHASES:
        assert impl.PHASE_KIND == "sizing"


def test_every_catalogued_phase_conforms_to_protocol() -> None:
    for impl in SIZING_PHASES:
        inst = impl(impl.Params(), logger=None)  # type: ignore[attr-defined]
        assert isinstance(inst, PhaseInterface)


def test_score_tier_exposes_space_and_complexity() -> None:
    space = ScoreTierHeatcap.Params.space()
    assert isinstance(space, ParamSpace)
    complexity = ScoreTierHeatcap.COMPLEXITY
    assert isinstance(complexity, ComplexityDecl)
    complexity.validate(space)  # free_params == swept axes, else ValueError


def test_score_tier_space_shape() -> None:
    space = ScoreTierHeatcap.Params.space()
    assert set(space.axes) == {"position_pct", "full", "three_quarter", "half", "min_score"}
    assert 0.10 in space.axes["position_pct"]   # champion flat-equivalent base
    assert 1.00 in space.axes["full"]           # canonical 4/4 tier
    assert 0.75 in space.axes["three_quarter"]  # canonical 3/4 tier
    assert 0.50 in space.axes["half"]           # canonical 2/4 tier
    assert 2 in space.axes["min_score"]         # canonical entry floor
    assert space.grid_size == 243               # 3^5
    assert "enabled" not in space.axes
