"""Config enumeration (#214 component 1) — catalog x space() -> the config grid.

Phase-agnostic: given a catalog (a `*_PHASES` tuple of phase classes) the enumerator reads
each impl's `Params.space()` (the STABLE contract — `space().axes`, a field->candidate-
sequence map) and produces the cartesian product of those axes as fully-resolved
SweepConfigs. It is generic over ANY catalog (signal / sizing / exit / ...): the only thing
it touches is the public `space()` / `COMPLEXITY` contract, never a phase's internals.

Two enumeration modes:
  - enumerate_phase(impl)      -> the grid for ONE phase kind (one impl's space()).
  - enumerate_catalog(catalog) -> the grid across a heterogeneous catalog (each impl's own
                                  grid, flattened — one SweepConfig per (impl, point)).
  - enumerate_product(catalogs)-> the cross-kind cartesian (one choice per kind), for a
                                  multi-phase strategy sweep.

DoF budget (ADR-0001 D5.5): a soft cap on total swept params (free_param_count) per config.
Over-budget configs are FLAGGED + dropped from the enumerated set (and reported), never
silently run. The budget is on the SWEEP SURFACE (axis count), enforced here at enumeration
time so an explosive grid is caught before any backtest spends compute.
"""
from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sweeps.types import PhaseChoice, PhaseClassLike, SweepConfig

DEFAULT_DOF_BUDGET = 8
"""Default soft cap on total swept free params per strategy config (ADR D5.5). Tunable."""


@dataclass(frozen=True, slots=True)
class EnumerationResult:
    """The outcome of an enumeration: the kept grid + the over-budget configs it dropped.

    `configs` = the in-budget SweepConfigs to run. `over_budget` = configs whose
    total_free_params exceeded the DoF budget (dropped, but surfaced for the loud log
    ADR D5.5 mandates). `grid_size` = configs kept; `dropped` = configs dropped.
    """

    configs: tuple[SweepConfig, ...]
    over_budget: tuple[SweepConfig, ...]
    dof_budget: int

    @property
    def grid_size(self) -> int:
        return len(self.configs)

    @property
    def dropped(self) -> int:
        return len(self.over_budget)


def _free_params(impl: PhaseClassLike) -> int:
    """Swept-axis count for a phase = its space() free_param_count.

    Cross-checked against an optional COMPLEXITY declaration if present (the phase's own
    overfitting-defense honesty check, ComplexityDecl.validate). The space() axes are the
    authoritative count for the DoF math here.
    """
    space = impl.Params.space()
    return space.free_param_count


def _phase_points(impl: PhaseClassLike) -> list[PhaseChoice]:
    """All grid points for ONE phase = cartesian product of its space() axes.

    Each point is a PhaseChoice (kind + impl name + a resolved field->value assignment +
    the phase's free-param count). Axis order is sorted by field name for determinism, so a
    given (impl, point) always hashes identically regardless of dict insertion order.
    """
    space = impl.Params.space()
    fields = sorted(space.axes.keys())
    free = space.free_param_count
    kind = impl.PHASE_KIND
    name = impl.__name__  # type: ignore[attr-defined]  # phase classes have __name__

    if not fields:
        # A phase with no swept axes contributes exactly one point (its defaults).
        return [PhaseChoice(kind=kind, impl_name=name, params=(), free_params=0)]

    value_lists: list[Sequence[object]] = [space.axes[f] for f in fields]
    points: list[PhaseChoice] = []
    for combo in itertools.product(*value_lists):
        params = tuple(zip(fields, combo, strict=True))
        points.append(PhaseChoice(kind=kind, impl_name=name, params=params, free_params=free))
    return points


def enumerate_phase(impl: PhaseClassLike) -> list[SweepConfig]:
    """The grid for ONE phase impl — one single-choice SweepConfig per space() point."""
    return [SweepConfig(choices=(p,)) for p in _phase_points(impl)]


def enumerate_catalog(catalog: Iterable[PhaseClassLike]) -> list[SweepConfig]:
    """Flatten a catalog's grids: every impl x every point in that impl's space().

    One SweepConfig per (impl, grid-point). This is the single-kind sweep: try each impl of
    a kind across all of its swept settings. Generic over any `*_PHASES` tuple.
    """
    configs: list[SweepConfig] = []
    for impl in catalog:
        configs.extend(enumerate_phase(impl))
    return configs


def enumerate_product(catalogs: Iterable[Iterable[PhaseClassLike]]) -> list[SweepConfig]:
    """Cross-kind cartesian: one chosen (impl, point) per kind, all combinations.

    Given e.g. [SIGNAL_PHASES, SIZING_PHASES], produce every strategy that picks one signal
    point AND one sizing point. The per-kind point lists are the flattened impl-grids from
    enumerate_catalog (so it spans impl choice AND param choice within each kind).
    """
    per_kind_points: list[list[PhaseChoice]] = []
    for catalog in catalogs:
        points: list[PhaseChoice] = []
        for impl in catalog:
            points.extend(_phase_points(impl))
        per_kind_points.append(points)

    if not per_kind_points:
        return []

    configs: list[SweepConfig] = []
    for combo in itertools.product(*per_kind_points):
        configs.append(SweepConfig(choices=tuple(combo)))
    return configs


def apply_dof_budget(
    configs: Iterable[SweepConfig], *, dof_budget: int = DEFAULT_DOF_BUDGET
) -> EnumerationResult:
    """Split an enumerated grid into in-budget vs over-budget (ADR D5.5).

    A config whose `total_free_params` exceeds `dof_budget` is dropped from the run set and
    collected in `over_budget` (the loud-log surface). The DoF budget bounds the SWEEP
    SURFACE — the count of free knobs a single strategy variant exposes — independent of the
    grid cardinality. Soft cap: it flags + drops, it does not raise.
    """
    kept: list[SweepConfig] = []
    over: list[SweepConfig] = []
    for cfg in configs:
        if cfg.total_free_params > dof_budget:
            over.append(cfg)
        else:
            kept.append(cfg)
    return EnumerationResult(
        configs=tuple(kept), over_budget=tuple(over), dof_budget=dof_budget
    )
