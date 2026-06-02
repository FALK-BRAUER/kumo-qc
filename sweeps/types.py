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
from datetime import datetime
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
    over (kind, impl, sorted params). It uses the same sha256[:12] digest FORMAT/discipline
    as build/cloud_package._config_hash, but is NOT cross-matchable to it: the dist hash also
    folds in name+version+per-slot enabled, so the same logical config yields a DIFFERENT
    digest in each. Compare sweep-hash to sweep-hash and dist-hash to dist-hash, never across.
    """

    choices: tuple[PhaseChoice, ...]
    # #336/#338: the CONTINUOUS_WEEKLY correctness fix is a DIFFERENT strategy (it makes different
    # decisions on the corrected weekly), so it belongs in the config IDENTITY → its own config_hash
    # + archive. Default False = the legacy/prod strategy; it enters the hash ONLY when True (non-
    # default), so an all-default config hashes EXACTLY as before (e3b0c44298fc unchanged) — the
    # canonical archive/test/dist-pin keys never move. flag-ON → a new distinct hash.
    continuous_weekly: bool = False

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
        # non-default ONLY: append the identity dimension when the fix is ON, so the legacy
        # all-default hash is byte-identical to before (backward-compatible by construction).
        if self.continuous_weekly:
            parts.append("continuous_weekly:1")
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
# Rich per-run result (the #320/#323 objective layer needs trade-level data).
#
# DESIGN DELTA (#214 vs design-doc A.5): the design doc proposes WIDENING the
# RunConfig Protocol return type from ResultMetrics -> RunResult. Doing so would
# break the existing pool/leaderboard/provenance (all typed on ResultMetrics) and
# their passing tests. #214's scope is the DRIVER VEHICLE (enumerate -> isolated
# parallel LEAN runs -> leaderboard -> ledger); the trade-level consumers (DSR/PBO,
# #323) are a separate issue. So the RunConfig Protocol below is KEPT returning
# ResultMetrics, and the adapters ALSO expose a `run_result()` method returning the
# full RunResult — single parse, no Protocol break, #323-ready. RunResult.metrics is
# the projection the Protocol surfaces.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TradeRecord:
    """One closed trade, net of costs (#321 — costs are already in the BT).

    `ret` is the per-trade return the DSR/PBO objective consumes. `entry_dt`/`exit_dt`
    bound the holding period (CPCV purge overlap test, B.3).
    """

    symbol: str
    entry_dt: datetime
    exit_dt: datetime
    pnl: float
    ret: float


@dataclass(frozen=True, slots=True)
class RunResult:
    """The full atomic output of a backtest; ResultMetrics is its leaderboard projection.

    `is_degraded` is set when a data-outage / empty-warmup-coarse artifact is detected
    (the FY2025 +3.9% mirage). A degraded run MUST NOT be scored — the adapter raises
    rather than returning a degraded RunResult into the scoring path (G-DATA gate, #261/#270).
    """

    metrics: ResultMetrics
    trades: tuple[TradeRecord, ...] = field(default_factory=tuple)
    daily_returns: tuple[float, ...] = field(default_factory=tuple)
    is_degraded: bool = False


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


@runtime_checkable
class RichRunConfig(RunConfig, Protocol):
    """A RunConfig that ALSO exposes the full RunResult (trades + daily returns).

    The real LEAN adapters satisfy this: `__call__` returns the leaderboard-facing
    ResultMetrics (so they drop into pool.py unchanged), while `run_result()` returns
    the same backtest's full RunResult for the #323 objective layer — ONE parse, two
    views, no Protocol break (the #214 design delta above)."""

    def run_result(self, config: SweepConfig, window: Window) -> RunResult: ...


# --------------------------------------------------------------------------- #
# Adapter failure modes — fail-loud, never a mirage metric (CLAUDE.md data-integrity).
# --------------------------------------------------------------------------- #
class AdapterError(Exception):
    """Base class for run-a-config adapter failures. Adapters RAISE rather than return a
    fabricated/mirage metric — a result that can't prove which artifact produced it is
    invalid (the fabrication guard / G-DATA gate)."""


class MarkerMismatchError(AdapterError):
    """The executed-code marker readback != the config's expected marker — possible
    cross-run contamination (the 2026-05-29 e40c-ran-e40b's-code incident). Fail loud."""


class DegradedDataError(AdapterError):
    """The run hit a data outage / empty-warmup-coarse (the FY2025 +3.9% artifact). A
    degraded state CRASHES — it never yields a scored metric (#261/#270 G-DATA gate)."""


class ResultParseError(AdapterError):
    """The result artifact is missing, unreadable, or has NaN/inf metrics. Fail loud
    rather than bank a 0/NaN as a real result."""


class CloudValidationError(AdapterError):
    """A cloud BT did not run clean (error set, partial progress, or unverifiable
    liveness). Mirrors qc_v2_cloud.assert_cloud_clean's contract — NO winner is promoted
    without a clean cloud run (CONVENTIONS §Parity)."""
