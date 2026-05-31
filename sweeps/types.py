"""Typed interface shared across the mass-runner (#214).

These are the stable contracts every sweeps/ component speaks. They are deliberately
SELF-CONTAINED and phase-agnostic: the runner never imports engine.config or a concrete
phase — it consumes only the public `space()`/`COMPLEXITY` contract (via duck-typed
Protocols here) plus a catalog tuple of phase classes. This keeps the mechanics testable
on a TINY MOCK catalog with ZERO real backtest / cloud spend (ADR-0001 D5; #214 HQ
constraint: build the mechanics, mock the run-a-config primitive).

Key types:
  - PhaseChoice / SweepConfig — one enumerated strategy variant: a chosen (impl, params)
    per kind, identified by a deterministic config-hash. Phase-agnostic — `impl` is any
    object, `params` any value object; the runner never inspects their internals beyond
    `repr()` for hashing.
  - Window — one of the mandatory validation windows (a named [start, end] span).
  - ResultMetrics — the metrics trio (Sharpe / Ret% / DD%) + order count from ONE
    (config, window) backtest. The atomic output of the run-a-config primitive.
  - RunConfig — the INJECTED run-a-config primitive Protocol: `(config, window) ->
    ResultMetrics`. Tests pass a deterministic MOCK; the real impl (shells to LEAN /
    drives the engine) is a thin integration-flagged adapter, never unit-run.
  - SpaceLike / ComplexityLike / ParamsLike — structural Protocols mirroring the
    src/phases/shared contracts (ParamSpace / ComplexityDecl / a `.Params` with
    `space()`), so enumerate.py consumes the REAL phase contract without importing it.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# Structural mirrors of the src/phases/shared contracts (no import coupling).
# --------------------------------------------------------------------------- #
@runtime_checkable
class SpaceLike(Protocol):
    """Structural shape of phases.shared.param_space.ParamSpace.

    The ONLY contract enumerate.py depends on: `axes` maps a param-field name to an
    explicit finite Sequence of candidate values. `free_param_count` = number of axes.
    """

    axes: dict[str, Sequence[object]]

    @property
    def free_param_count(self) -> int: ...


@runtime_checkable
class ComplexityLike(Protocol):
    """Structural shape of phases.shared.param_space.ComplexityDecl."""

    free_params: int
    note: str


@runtime_checkable
class ParamsLike(Protocol):
    """Structural shape of a phase `.Params` class exposing `space()`."""

    @classmethod
    def space(cls) -> SpaceLike: ...


@runtime_checkable
class PhaseClassLike(Protocol):
    """Structural shape of a catalog member (a phase CLASS).

    A phase declares its kind (`PHASE_KIND`), its nested `Params` (with `space()`), and an
    optional `COMPLEXITY` declaration. The runner reads these to enumerate the grid and to
    price complexity — without constructing the phase or wiring a StrategyConfig.
    """

    PHASE_KIND: str
    Params: type[ParamsLike]


# --------------------------------------------------------------------------- #
# Enumerated config representation.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PhaseChoice:
    """One phase wired into an enumerated variant: a chosen impl + a chosen param assignment.

    `kind` = the phase kind (e.g. "signal"). `impl_name` = the phase class name.
    `params` = the resolved param assignment for THIS variant (field-name -> value), a
    single point in that phase's `space()` grid. `free_params` = the swept-axis count this
    phase contributes to the strategy DoF (from its ComplexityDecl / space()).
    """

    kind: str
    impl_name: str
    params: tuple[tuple[str, object], ...]  # sorted (field, value) pairs — hashable
    free_params: int

    def param_dict(self) -> dict[str, object]:
        return dict(self.params)


@dataclass(frozen=True, slots=True)
class SweepConfig:
    """One fully-enumerated strategy variant = a choice per kind, hashed for provenance.

    Phase-agnostic: a tuple of PhaseChoice. `config_hash` is a deterministic 12-hex digest
    over (kind, impl, sorted params) — the same shape as build/cloud_package._config_hash,
    so a sweep config-hash is comparable to a built-dist config-hash.
    """

    choices: tuple[PhaseChoice, ...]

    @property
    def total_free_params(self) -> int:
        """Strategy-level DoF = sum of swept axes across the active phase stack (ADR D5.5)."""
        return sum(c.free_params for c in self.choices)

    @property
    def config_hash(self) -> str:
        parts: list[str] = []
        for c in sorted(self.choices, key=lambda x: x.kind):
            params_repr = ",".join(f"{k}={v!r}" for k, v in c.params)
            parts.append(f"{c.kind}:{c.impl_name}:{params_repr}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Validation windows + per-run metrics.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Window:
    """One validation window — a named, ordered [start, end] date span (ISO YYYY-MM-DD)."""

    name: str
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class ResultMetrics:
    """The metrics trio + order count from ONE (config, window) backtest.

    Sharpe / Ret% / DD% are MANDATORY on every row (MEMORY: result-table-format —
    never Sharpe alone). `orders` is the fill count. This is the atomic output of the
    run-a-config primitive; aggregation builds distributions from a list of these.
    """

    sharpe: float
    ret_pct: float
    dd_pct: float
    orders: int


@dataclass(frozen=True, slots=True)
class WindowResult:
    """A ResultMetrics tagged with the window it came from (collation unit)."""

    window: Window
    metrics: ResultMetrics


@dataclass(frozen=True, slots=True)
class ConfigRun:
    """All 6-window results for one config, ready for aggregation."""

    config: SweepConfig
    window_results: tuple[WindowResult, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# The INJECTED run-a-config primitive (mock in tests, real adapter in prod).
# --------------------------------------------------------------------------- #
@runtime_checkable
class RunConfig(Protocol):
    """`(config, window) -> ResultMetrics` — the single run-a-config primitive.

    INJECTED everywhere a backtest would happen. Unit tests pass a deterministic MOCK that
    returns fake metrics (ZERO LEAN / cloud spend). The real impl — a thin adapter that
    builds the dist closure, shells to LEAN in an isolated project, parses the result — is
    integration-flagged and never unit-run. The runner mechanics NEVER call LEAN directly;
    they only call this Protocol.
    """

    def __call__(self, config: SweepConfig, window: Window) -> ResultMetrics: ...
