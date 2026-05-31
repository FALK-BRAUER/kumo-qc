"""Sweep-guard: every phase-library catalog is enumerable without crash (#246).

Parametrized across ALL phase-kind catalogs. The REAL behavioral contract: a sweep runner
(#214) iterates the catalog, reads .Params.space() and .COMPLEXITY on each member, and builds
a config grid. If ANY member is malformed (missing .space(), COMPLEXITY/space mismatch,
cannot be instantiated with default params), the sweep crashes hours in.

This test catches that at CI time — behavioral because it exercises the same code path
a sweep runner would, not structural isinstance checks.
"""
from __future__ import annotations

from typing import Any

import pytest

from engine.base import PhaseInterface
from phases.entry_selection.library import ENTRY_SELECTION_PHASES
from phases.entry_timing.library import ENTRY_TIMING_PHASES
from phases.shared.param_space import ComplexityDecl, ParamSpace
from phases.signal.library import SIGNAL_PHASES
from phases.sizing.library import SIZING_PHASES

# All ADR D3 catalogs — extend when new kinds graduate.
CATALOGS: list[tuple[str, tuple[type[Any], ...]]] = [
    ("signal", SIGNAL_PHASES),
    ("sizing", SIZING_PHASES),
    ("entry_selection", ENTRY_SELECTION_PHASES),
    ("entry_timing", ENTRY_TIMING_PHASES),
]


@pytest.mark.parametrize("kind_name,catalog", CATALOGS)
def test_catalog_is_non_empty(kind_name: str, catalog: tuple[type[Any], ...]) -> None:
    """A sweep runner enumerating an empty catalog is a no-op — flag it."""
    assert len(catalog) >= 1, f"{kind_name} catalog is empty — sweep would find nothing"


@pytest.mark.parametrize("kind_name,catalog", CATALOGS)
def test_every_member_instantiable_with_defaults(kind_name: str, catalog: tuple[type[Any], ...]) -> None:
    """Behavioral: sweep runner constructs each phase with default params to read space()/COMPLEXITY.
    If a member can't be instantiated (missing default ctor, broken params), the sweep dies here."""
    for impl in catalog:
        inst = impl(impl.Params(), logger=None)
        assert isinstance(inst, PhaseInterface), f"{impl.__name__} does not satisfy PhaseInterface"


@pytest.mark.parametrize("kind_name,catalog", CATALOGS)
def test_every_member_exposes_sweep_surface(kind_name: str, catalog: tuple[type[Any], ...]) -> None:
    """Behavioral: the sweep reads .Params.space() for grid axes and .COMPLEXITY for penalty.
    A mismatch (free_params != len(axes)) means the penalty under- or over-counts swept knobs —
    a silent overfitting bug. ComplexityDecl.validate() raises ValueError on mismatch."""
    for impl in catalog:
        space = impl.Params.space()
        assert isinstance(space, ParamSpace), f"{impl.__name__}.Params.space() must return ParamSpace"
        complexity = impl.COMPLEXITY
        assert isinstance(complexity, ComplexityDecl), f"{impl.__name__}.COMPLEXITY must be ComplexityDecl"
        complexity.validate(space)  # raises ValueError if free_params != len(axes)


@pytest.mark.parametrize("kind_name,catalog", CATALOGS)
def test_every_member_declares_correct_phase_kind(kind_name: str, catalog: tuple[type[Any], ...]) -> None:
    """Behavioral: the sweep runner groups by PHASE_KIND. A mismatched kind means the phase
    lands in the wrong bucket and the StrategyEngine dependency validation fails."""
    for impl in catalog:
        assert impl.PHASE_KIND == kind_name, (
            f"{impl.__name__} declares PHASE_KIND={impl.PHASE_KIND!r} but catalog is {kind_name!r}"
        )


def test_union_of_all_catalogs_has_no_duplicate_class_refs() -> None:
    """Behavioral: a sweep runner that enumerates multiple catalogs must not double-count
    the same implementation (would duplicate grid points, waste compute, bias complexity)."""
    all_members: list[type[Any]] = []
    for _kind, catalog in CATALOGS:
        for impl in catalog:
            all_members.append(impl)
    assert len(all_members) == len(set(all_members)), "duplicate class ref across catalogs"
