from __future__ import annotations
import hashlib
import json
from typing import Any
from base import PhaseInterface, CharterViolation
from context import PhaseContext
from logger import ComponentLogger


class FireSentinel:
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"FireSentinel({self.name!r})"


FIRE_ENTRIES = FireSentinel("FIRE_ENTRIES")
FIRE_EXITS   = FireSentinel("FIRE_EXITS")
FIRE_ADDS    = FireSentinel("FIRE_ADDS")
FIRE_TRIMS   = FireSentinel("FIRE_TRIMS")

PHASE_ORDER: list = [
    "rebalance", "universe", "signal", "regime", "ranking",
    "entry_selection", "entry_timing", "sizing",
    "reentry", "eligibility", "portfolio_risk", "cash",
    FIRE_ENTRIES,
    "stops_initial", "trail",
    "exit_hard", "exit_target", "exit_regime", "exit_rotation",
    FIRE_EXITS,
    "adds",
    FIRE_ADDS,
    "profit",
    FIRE_TRIMS,
    "diagnostics", "circuit_breaker",
]

# Phases that are suppressed when bar_blocked (entry-side only).
# Exit-side (stops_initial, trail, exit_*, profit) ALWAYS runs — oracle behaviour.
ENTRY_ONLY_PHASES = {
    "entry_selection", "entry_timing", "sizing", "reentry",
    "eligibility", "portfolio_risk", "cash", "adds",
}
ENTRY_ONLY_SENTINELS = {FIRE_ENTRIES, FIRE_ADDS}

# Always runs regardless of block state.
ALWAYS_RUN = {"diagnostics", "circuit_breaker"}

FORBIDDEN_PARAMS = {
    # count caps
    "max_positions", "max_lots", "max_entries_per_day",
    "max_adds", "max_pyramid_lots", "max_position_adds",
    "max_concurrent_positions", "position_limit", "max_slots",
    # time-based exits
    "max_hold_days", "exit_if_flat_after_days",
    "max_days_held", "max_bars_held", "time_stop_days",
    "exit_after_days", "holding_period_limit",
}


def validate_invariants(config: dict) -> None:
    for kind, phase_cfg in config.get("phases", {}).items():
        cfgs = phase_cfg if isinstance(phase_cfg, list) else [phase_cfg]
        for cfg in cfgs:
            for param_key in cfg.get("params", {}):
                if param_key in FORBIDDEN_PARAMS:
                    raise CharterViolation(
                        f"'{param_key}' is a forbidden param (count cap / time exit) in phase '{kind}'"
                    )


def _config_hash(config: dict) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


class StrategyEngine:
    def __init__(self, config: dict, qc: Any, phase_instances: dict[str, list[PhaseInterface]]):
        self.config = config
        self.qc = qc
        self.phases = phase_instances
        self.logger = ComponentLogger(qc)
        validate_invariants(config)
        self.logger.log_strategy_init(
            config_hash=_config_hash(config),
            name=config.get("name", "unknown"),
            version=config.get("version", "0.0.0"),
        )

    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        bar_blocked = False
        phases_run: list[str] = []
        fired_entries = fired_exits = fired_adds = 0

        for item in PHASE_ORDER:
            if isinstance(item, FireSentinel):
                # Entry-side sentinels suppressed on blocked bar; exit-side always fire.
                if bar_blocked and item in ENTRY_ONLY_SENTINELS:
                    continue
                self._fire(item, ctx)
                continue

            kind = item
            for phase in self.phases.get(kind, []):
                if not phase.enabled:
                    continue
                # On blocked bar: suppress entry-side phases; always run exit-side + tail.
                if bar_blocked and kind in ENTRY_ONLY_PHASES and kind not in ALWAYS_RUN:
                    continue

                result = phase.evaluate(ctx)
                self.logger.log_phase(kind, phase, result)
                ctx.bar_state.apply(kind, result, module=phase.version_marker)
                phases_run.append(kind)

                if result.blocked and kind in {"regime", "cash"}:
                    bar_blocked = True

        self.logger.log_tick(
            chain=phases_run,
            entries=fired_entries,
            exits=fired_exits,
            adds=fired_adds,
        )

    def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
        # Order submission wired in ARCH-C when LEAN integration lands
        pass
