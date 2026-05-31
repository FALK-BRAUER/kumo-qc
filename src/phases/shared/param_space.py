"""Sweep + overfitting-defense primitives shared by every phase (the #228 template).

Two conventions, established here by the signal phase (#228) and followed by every later
phase kind (entry_timing, stops, trail, ...):

  1. ParamSpace — the typed return shape of a phase's `space()` classmethod (ADR D2). It
     enumerates the SWEEPABLE axes of a phase's `.Params`: each axis is a `(name, values)`
     pair where `values` is an explicit, finite `Sequence` of candidate settings the runner
     may grid/random-search over. NO string registry, NO free-form dict[str, Any] — a typed
     mapping of param-name -> candidate sequence, mypy --strict clean. The sweep runner reads
     `axes` to build the grid; the cardinality (product of len(values)) feeds the complexity
     penalty below.

  2. ComplexityDecl — the per-phase OVERFITTING-DEFENSE declaration (ADR D5). A phase declares
     how many FREE PARAMETERS it exposes to a sweep (`free_params`) plus an optional human note.
     The runner sums `free_params` across the active phase stack into a strategy-level
     complexity score and applies a deflation penalty (DSR / PBO style) so a strategy that wins
     by burning more tunable knobs is penalised vs a simpler one with the same raw Sharpe. This
     is a DECLARATION, not an enforcement: the phase states its surface honestly; the runner
     does the math. `free_params` MUST equal the number of axes in `space()` (a phase cannot
     hide a swept knob from the penalty) — `validate()` asserts this.

Design choices (these are the template — later phases copy them verbatim):
  - Sequences, not ranges: a range hides its cardinality and tempts continuous over-search; an
    explicit Sequence makes the grid cardinality (and thus the complexity cost) visible at the
    call site. A param the author does NOT want swept simply does not appear in `axes`.
  - `space()` is a CLASSMETHOD on the `.Params` class (not the phase): the param surface belongs
    to the params, is available without constructing the phase, and sits next to the fields it
    describes.
  - Frozen + slotted: these are immutable value objects, hot in neither path; frozen makes them
    safe to share across a sweep grid build.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParamSpace:
    """Typed sweep space for a phase's `.Params` (the `space()` return shape).

    `axes` maps a `.Params` field name to the explicit, finite sequence of candidate values a
    sweep may try for it. A field absent from `axes` is held at its `.Params` default (not
    swept). `grid_size` is the full-grid cardinality = product of the per-axis lengths.
    """

    axes: dict[str, Sequence[object]]

    @property
    def grid_size(self) -> int:
        """Full-grid cardinality (product of per-axis candidate counts). 1 if no axes."""
        size = 1
        for values in self.axes.values():
            size *= len(values)
        return size

    @property
    def free_param_count(self) -> int:
        """Number of swept axes = the count of free parameters this space exposes."""
        return len(self.axes)


@dataclass(frozen=True, slots=True)
class ComplexityDecl:
    """A phase's overfitting-defense declaration (ADR D5).

    `free_params` = the number of tunable knobs the phase exposes to a sweep (MUST equal the
    number of axes in `space()`). `note` is an optional human rationale. The sweep runner sums
    `free_params` across the active stack and deflates the Sharpe by a complexity penalty.
    """

    free_params: int
    note: str = ""

    def validate(self, space: ParamSpace) -> None:
        """Assert the declared free-param count matches the actual sweep surface.

        A phase cannot understate its complexity: a knob present in `space().axes` but not
        counted in `free_params` would dodge the penalty. Fail loud at the seam.
        """
        if self.free_params != space.free_param_count:
            raise ValueError(
                f"ComplexityDecl.free_params={self.free_params} != "
                f"space().free_param_count={space.free_param_count} — every swept axis "
                "must be counted in the complexity declaration (no hidden knobs)."
            )
