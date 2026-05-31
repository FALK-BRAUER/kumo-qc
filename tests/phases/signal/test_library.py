"""Tests for the signal-phase catalog (phases.signal.library, ADR D3 — the template catalog).

Asserts the enumeration pattern every later kind copies: a typed tuple of DIRECT CLASS REFS
(not strings), each member protocol-conforming and exposing space()/COMPLEXITY for the sweep
runner, and the teaching fixture (sample_bct) deliberately excluded.
"""
from __future__ import annotations

from engine.base import PhaseInterface
from phases.shared.param_space import ComplexityDecl, ParamSpace
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.signal.library import SIGNAL_PHASES


def test_catalog_is_a_tuple_of_classes_not_strings() -> None:
    assert isinstance(SIGNAL_PHASES, tuple)
    for impl in SIGNAL_PHASES:
        assert isinstance(impl, type), "catalog holds class refs, never name strings"


def test_bct_score_full_is_catalogued() -> None:
    assert BctScoreFull in SIGNAL_PHASES


def test_sample_bct_teaching_fixture_excluded() -> None:
    names = {impl.__name__ for impl in SIGNAL_PHASES}
    assert "SampleBct" not in names, "config-only teaching fixture must not be sweep-selectable"


def test_every_catalogued_phase_declares_signal_kind() -> None:
    for impl in SIGNAL_PHASES:
        assert impl.PHASE_KIND == "signal"


def test_every_catalogued_phase_conforms_to_protocol() -> None:
    for impl in SIGNAL_PHASES:
        inst = impl(impl.Params(), logger=None)  # type: ignore[attr-defined]
        assert isinstance(inst, PhaseInterface)


def test_every_catalogued_phase_exposes_space_and_complexity() -> None:
    """The sweep contract: each catalogued phase has Params.space() -> ParamSpace and a
    COMPLEXITY ComplexityDecl whose free_params matches the space (no hidden knobs)."""
    for impl in SIGNAL_PHASES:
        space = impl.Params.space()  # type: ignore[attr-defined]
        assert isinstance(space, ParamSpace)
        complexity = impl.COMPLEXITY  # type: ignore[attr-defined]
        assert isinstance(complexity, ComplexityDecl)
        complexity.validate(space)  # free_params == swept axes, else ValueError


def test_bct_score_full_space_shape() -> None:
    space = BctScoreFull.Params.space()
    assert set(space.axes) == {"min_score", "parabolic_threshold"}
    assert 7 in space.axes["min_score"]  # champion default is in the sweep
    assert 0.25 in space.axes["parabolic_threshold"]
    assert space.grid_size == 12
    assert "enabled" not in space.axes, "wiring toggle is not a strategy axis"
