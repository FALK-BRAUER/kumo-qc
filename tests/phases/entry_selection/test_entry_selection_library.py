"""Tests for the entry_selection catalog (phases.entry_selection.library, ADR D3).

Mirrors tests/phases/signal/test_library.py: a typed tuple of DIRECT CLASS REFS (not strings),
each member protocol-conforming and exposing space()/COMPLEXITY for the #214 sweep runner.
"""
from __future__ import annotations

from engine.base import PhaseInterface
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm
from phases.entry_selection.library import ENTRY_SELECTION_PHASES
from phases.shared.param_space import ComplexityDecl, ParamSpace


def test_catalog_is_a_tuple_of_classes_not_strings() -> None:
    assert isinstance(ENTRY_SELECTION_PHASES, tuple)
    for impl in ENTRY_SELECTION_PHASES:
        assert isinstance(impl, type), "catalog holds class refs, never name strings"


def test_bct_entry_confirm_is_catalogued() -> None:
    assert BctEntryConfirm in ENTRY_SELECTION_PHASES


def test_every_catalogued_phase_declares_entry_selection_kind() -> None:
    for impl in ENTRY_SELECTION_PHASES:
        assert impl.PHASE_KIND == "entry_selection"


def test_every_catalogued_phase_conforms_to_protocol() -> None:
    for impl in ENTRY_SELECTION_PHASES:
        inst = impl(impl.Params(), logger=None)  # type: ignore[attr-defined]
        assert isinstance(inst, PhaseInterface)


def test_every_catalogued_phase_exposes_space_and_complexity() -> None:
    for impl in ENTRY_SELECTION_PHASES:
        space = impl.Params.space()  # type: ignore[attr-defined]
        assert isinstance(space, ParamSpace)
        complexity = impl.COMPLEXITY  # type: ignore[attr-defined]
        assert isinstance(complexity, ComplexityDecl)
        complexity.validate(space)  # free_params == swept axes, else ValueError


def test_bct_entry_confirm_space_shape() -> None:
    space = BctEntryConfirm.Params.space()
    assert set(space.axes) == {"tenkan_pullback_tol", "volume_gate_mult", "macd_signal", "min_confirm"}
    assert 1.0 in space.axes["volume_gate_mult"]   # canonical gate is in the sweep
    assert 9 in space.axes["macd_signal"]          # canonical signal period
    assert 2 in space.axes["min_confirm"]          # canonical qualify floor
    assert space.grid_size == 81                   # 3x3x3x3
    assert "macd_fast" not in space.axes, "canonical 12/26 NOT swept (no per-ticker MACD opt)"
    assert "macd_slow" not in space.axes
    assert "enabled" not in space.axes
