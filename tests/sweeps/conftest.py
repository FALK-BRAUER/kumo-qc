"""Shared fixtures for the mass-runner tests (#214) — TINY MOCK catalog + fake runner.

CRITICAL (#214 HQ constraint): every test runs on a MOCK. There is NO real LEAN, NO cloud,
ZERO compute spend. The run-a-config primitive is a deterministic fake returning
hand-computed metrics so aggregation / scoring / ranking can be asserted exactly.

Provides:
  - TwoAxisPhase / OneAxisPhase / NoAxisPhase — fake phase classes with `PHASE_KIND`, a
    nested `Params` exposing `space()`, and a `COMPLEXITY` decl, mirroring the real
    src/phases contract WITHOUT importing engine code (proves phase-agnosticism).
  - MOCK_CATALOG — a `*_PHASES`-shaped tuple of those fakes.
  - make_runner(table) — build a deterministic RunConfig from a {(config_hash, window_name):
    ResultMetrics} table (or a callable), for exact-value assertions.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sweeps.types import ResultMetrics, SweepConfig, Window

# --- ParamSpace / ComplexityDecl stand-ins (structural — match SpaceLike/ComplexityLike) --- #


@dataclass(frozen=True, slots=True)
class FakeSpace:
    axes: dict[str, Sequence[object]]

    @property
    def free_param_count(self) -> int:
        return len(self.axes)


@dataclass(frozen=True, slots=True)
class FakeComplexity:
    free_params: int
    note: str = ""


# --- Fake phase classes (the mock catalog members) --- #


class TwoAxisPhase:
    PHASE_KIND = "signal"
    COMPLEXITY = FakeComplexity(free_params=2, note="two-axis mock")

    class Params:
        alpha: int = 1
        beta: float = 0.1

        @classmethod
        def space(cls) -> FakeSpace:
            # grid = 2 x 3 = 6 points
            return FakeSpace(axes={"alpha": (1, 2), "beta": (0.1, 0.2, 0.3)})


class OneAxisPhase:
    PHASE_KIND = "signal"
    COMPLEXITY = FakeComplexity(free_params=1, note="one-axis mock")

    class Params:
        gamma: int = 5

        @classmethod
        def space(cls) -> FakeSpace:
            return FakeSpace(axes={"gamma": (5, 6, 7)})  # 3 points


class NoAxisPhase:
    PHASE_KIND = "sizing"
    COMPLEXITY = FakeComplexity(free_params=0, note="fixed, no swept axis")

    class Params:
        @classmethod
        def space(cls) -> FakeSpace:
            return FakeSpace(axes={})  # 1 point (defaults only)


class BigDoFPhase:
    """A phase with many swept axes — used to exercise the DoF budget."""

    PHASE_KIND = "exit"
    COMPLEXITY = FakeComplexity(free_params=5, note="deliberately over a tight budget")

    class Params:
        @classmethod
        def space(cls) -> FakeSpace:
            return FakeSpace(
                axes={
                    "a": (1, 2),
                    "b": (1, 2),
                    "c": (1, 2),
                    "d": (1, 2),
                    "e": (1, 2),
                }
            )


MOCK_CATALOG: tuple[type, ...] = (TwoAxisPhase, OneAxisPhase)


# --- Deterministic fake run-a-config primitive --- #


def make_runner(
    table: Mapping[tuple[str, str], ResultMetrics] | Callable[[SweepConfig, Window], ResultMetrics],
) -> Callable[[SweepConfig, Window], ResultMetrics]:
    """Build a deterministic RunConfig.

    `table` is either a {(config_hash, window_name): ResultMetrics} mapping (exact control) or
    a callable. ZERO real backtest — purely returns the table value. A missing key raises so a
    test cannot silently get a wrong/zero metric.
    """
    if callable(table):
        return table

    def _run(config: SweepConfig, window: Window) -> ResultMetrics:
        key = (config.config_hash, window.name)
        if key not in table:
            raise KeyError(f"mock runner has no metrics for {key}")
        return table[key]

    return _run


def constant_runner(metrics: ResultMetrics) -> Callable[[SweepConfig, Window], ResultMetrics]:
    """A RunConfig returning the same metrics for every (config, window). For pool/isolation
    tests where exact per-cell values are not the focus."""

    def _run(config: SweepConfig, window: Window) -> ResultMetrics:
        return metrics

    return _run
