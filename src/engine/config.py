"""Typed strategy config — DIRECT CLASS REFERENCES, no runtime registry, no stringly dict.

`Slot(impl=SomePhase, params=SomePhase.Params(...))`. The construction site is where
mypy --strict validates the params dataclass (names/types). One ACTIVE StrategyConfig
per build; rebuild+redeploy to switch.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from typing import Generic, TypeVar

from engine.base import BasePhase

P = TypeVar("P")


@dataclass(slots=True)
class Slot(Generic[P]):
    """One phase wired into a strategy: a direct class ref + its typed params instance.

    `impl` is the phase class (instantiable via impl(params, logger)); `params` is an
    instance of that phase's nested `.Params` dataclass. enabled toggles it in-config.
    """
    impl: type[BasePhase]
    params: P
    enabled: bool = True


@dataclass(slots=True)
class RuntimeConfig:
    """Typed LEAN-runtime knobs emitted onto the generated `BCTAlgorithm` subclass.

    Defaults mirror `runtime.lean_entry.BctEngineAlgorithm`. Non-default values are behavioral
    provenance and therefore enter the config hash. The George watchlist/profile fields are
    default-off placeholders for the next framework PR; this PR only makes them typed/hashable.
    """

    start_date: tuple[int, int, int] = (2025, 1, 1)
    end_date: tuple[int, int, int] = (2025, 12, 31)
    cash: int = 100_000
    prefilter_dv: float = 25_000_000.0
    min_price: float = 10.0
    min_avg_dollar_volume: float = 100_000_000.0
    coarse_max: int = 9999
    adv_window: int = 20
    broken_zero_min_feed: int = 100
    warmup_days: int = 560
    weekly_floor_days: int = 560
    continuous_weekly: bool = False
    warmup_weekly_cache_fp: str | None = None
    decision_trace: bool = False
    after_close_min: int = 10
    intraday_subscribe_cap: int = 50
    intraday_tenkan: int = 9
    intraday_vol_window: int = 20
    slippage_percent: float = 0.0005
    entry_tag_max: int = 200
    watchlist_carry_max: int = 0
    watchlist_carry_min_price: float = 10.0
    watchlist_carry_min_avg_dollar_volume: float = 100_000_000.0
    security_profile_source: str | None = None
    george_attention_source: str | None = None
    scanner_ranker_enabled: bool = False
    scanner_ranker_model_path: str | None = None
    scanner_ranker_top_x: int = 0
    scanner_ranker_min_score: float | None = None
    scanner_ranker_fallback: str = "raise"


@dataclass(slots=True)
class StrategyConfig:
    name: str
    version: str
    # kind -> a single Slot or a list of Slots (regime/exit_*/diagnostics are list-kinds)
    phases: dict[str, "Slot[object] | list[Slot[object]]"] = field(default_factory=dict)
    # #270/#272 fail-loud phase-stack gate: a CHAMPION must wire an entry-confirm phase
    # (entry_selection | entry_timing) AND an exit phase (exit_*) — there is no implicit
    # market-on-open default. A config WITHOUT them must explicitly opt in as a FIXTURE
    # (regression/parity scaffolding) or the engine raises DegradedConfigError at init.
    # is_fixture=True is the ONLY way to run an incomplete (blind-entry) stack — never silent.
    is_fixture: bool = False
    # Runtime settings for the generated LEAN subclass. Defaults match BctEngineAlgorithm so legacy
    # configs stay hash-compatible and dist-compatible unless they explicitly opt in.
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    # Backward-compatible shim for pre-RuntimeConfig configs. New configs should prefer
    # `runtime=RuntimeConfig(continuous_weekly=True)`, but existing strategy modules keep working.
    # The effective runtime treats either flag as ON, and the hash still uses `continuous_weekly:1`.
    continuous_weekly: bool = False


def effective_runtime(config: StrategyConfig) -> RuntimeConfig:
    """RuntimeConfig after applying legacy top-level shims."""
    runtime = config.runtime
    if config.continuous_weekly and not runtime.continuous_weekly:
        return replace(runtime, continuous_weekly=True)
    return runtime


def runtime_overrides(runtime: RuntimeConfig) -> dict[str, object]:
    """Non-default runtime fields in stable field order."""
    default = RuntimeConfig()
    return {
        f.name: getattr(runtime, f.name)
        for f in fields(runtime)
        if getattr(runtime, f.name) != getattr(default, f.name)
    }
