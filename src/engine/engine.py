"""StrategyEngine — config-driven phase orchestration.

Ports the parity-proven v1 arch-a loop (@ 3705cd3):
- canonical PHASE_ORDER with FIRE_* sentinels
- ENTRY_ONLY block-scoping: regime/cash block halts NEW EXPOSURE only; exits + tail always run
- BarState.apply keyed by (kind, module)
- fail-loud init validations: charter invariants (incl explicit-exposure), dependency,
  single-adds, required-phases, per-phase marker logging

v2-delta: consumes a typed StrategyConfig (direct class refs), instantiates phases from
Slots, depends on the PhaseInterface Protocol.
"""
from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from engine.base import (
    BasePhase,
    CharterViolation,
    ConfigError,
    DependencyError,
    PhaseInterface,
)
from engine.config import Slot, StrategyConfig
from engine.context import PhaseContext
from engine.logger import ComponentLogger


class FireSentinel:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"FireSentinel({self.name!r})"


FIRE_ENTRIES = FireSentinel("FIRE_ENTRIES")
FIRE_EXITS = FireSentinel("FIRE_EXITS")
FIRE_ADDS = FireSentinel("FIRE_ADDS")
FIRE_TRIMS = FireSentinel("FIRE_TRIMS")

PHASE_ORDER: list[str | FireSentinel] = [
    "rebalance", "filter", "universe", "signal", "regime", "ranking",
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

# Suppressed when bar_blocked (entry-side). Exit-side + tail run regardless.
ENTRY_ONLY_PHASES: frozenset[str] = frozenset({
    "entry_selection", "entry_timing", "sizing", "reentry",
    "eligibility", "portfolio_risk", "cash", "adds",
})
ENTRY_ONLY_SENTINELS: frozenset[FireSentinel] = frozenset({FIRE_ENTRIES, FIRE_ADDS})
ALWAYS_RUN: frozenset[str] = frozenset({"diagnostics", "circuit_breaker"})

FORBIDDEN_PARAMS: frozenset[str] = frozenset({
    # count caps
    "max_positions", "max_lots", "max_entries_per_day",
    "max_adds", "max_pyramid_lots", "max_position_adds",
    "max_concurrent_positions", "position_limit", "max_slots",
    # time-based exits
    "max_hold_days", "exit_if_flat_after_days",
    "max_days_held", "max_bars_held", "time_stop_days",
    "exit_after_days", "holding_period_limit",
})

REQUIRED_PHASES: tuple[str, ...] = ("filter", "universe", "signal", "sizing")

# Every schedulable phase kind = the string items of PHASE_ORDER. A config keyed by any
# kind NOT in here would instantiate but never be scheduled in the per-bar loop (it reads
# self.phases.get(item) only for items IN PHASE_ORDER) → a SILENT no-op. The engine refuses
# such a config at init instead (fail-loud charter). Sentinels (FireSentinel) are not kinds.
KNOWN_KINDS: frozenset[str] = frozenset(
    item for item in PHASE_ORDER if isinstance(item, str)
)


def _slots(value: Slot[object] | list[Slot[object]]) -> list[Slot[object]]:
    return value if isinstance(value, list) else [value]


def _kind_enabled(config: StrategyConfig, kind: str) -> bool:
    v = config.phases.get(kind)
    if v is None:
        return False
    return any(s.enabled for s in _slots(v))


def validate_invariants(config: StrategyConfig) -> None:
    """Charter: no count caps / time exits (scan typed-param field names); explicit-exposure."""
    for kind, value in config.phases.items():
        for slot in _slots(value):
            for f in dataclasses.fields(slot.params):  # type: ignore[arg-type]
                if f.name in FORBIDDEN_PARAMS:
                    raise CharterViolation(
                        f"'{f.name}' is a forbidden count-cap/time-exit param in phase '{kind}'"
                    )
    if _kind_enabled(config, "adds") and not _kind_enabled(config, "portfolio_risk"):
        raise CharterViolation(
            "adds enabled without portfolio_risk (gross_exposure_cap) — "
            "implicit exposure forbidden; amplifying adds require an explicit cap"
        )


def _config_hash(config: StrategyConfig) -> str:
    parts: list[str] = [config.name, config.version]
    for kind in sorted(config.phases):
        for slot in _slots(config.phases[kind]):
            parts.append(f"{kind}:{slot.impl.__name__}:{slot.enabled}:{slot.params!r}")
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


class StrategyEngine:
    def __init__(self, config: StrategyConfig, qc: Any) -> None:
        self.config = config
        self.qc = qc
        self.logger = ComponentLogger(qc)
        self._fired_entries = 0
        self._fired_exits = 0
        self._fired_adds = 0

        validate_invariants(config)
        self._validate_known_kinds(config)
        self.phases: dict[str, list[PhaseInterface]] = self._instantiate(config)
        self._validate_required_phases()
        self._validate_single_adds()
        self._validate_dependencies()
        self._log_phase_markers()
        self.logger.log_strategy_init(_config_hash(config), config.name, config.version)

    def _instantiate(self, config: StrategyConfig) -> dict[str, list[PhaseInterface]]:
        out: dict[str, list[PhaseInterface]] = {}
        for kind, value in config.phases.items():
            instances: list[PhaseInterface] = []
            for slot in _slots(value):
                if not slot.enabled:
                    continue
                phase: BasePhase = slot.impl(slot.params, self.logger)
                instances.append(phase)
            if instances:
                out[kind] = instances
        return out

    # ---- init validations (fail loud) ----
    def _validate_known_kinds(self, config: StrategyConfig) -> None:
        """Every configured kind must be schedulable (present in PHASE_ORDER). A kind absent
        from PHASE_ORDER would instantiate but never run (silent no-op) — refuse it loudly."""
        unknown = sorted(k for k in config.phases if k not in KNOWN_KINDS)
        if unknown:
            raise ConfigError(
                f"unknown phase kind(s) {unknown} not in PHASE_ORDER — would never be "
                f"scheduled (silent no-op). Known kinds: {sorted(KNOWN_KINDS)}"
            )

    def _validate_required_phases(self) -> None:
        for kind in REQUIRED_PHASES:
            if not self.phases.get(kind):
                raise ConfigError(f"required phase '{kind}' missing or disabled")

    def _validate_single_adds(self) -> None:
        if len(self.phases.get("adds", [])) > 1:
            raise CharterViolation("multiple adds phases enabled — mutually exclusive")

    def _validate_dependencies(self) -> None:
        order_idx: dict[str, int] = {
            item: i for i, item in enumerate(PHASE_ORDER) if isinstance(item, str)
        }
        enabled_kinds = set(self.phases)
        for kind, instances in self.phases.items():
            for phase in instances:
                for req in phase.REQUIRES_UPSTREAM:
                    if req not in enabled_kinds:
                        raise DependencyError(
                            f"phase '{kind}' requires upstream '{req}' (missing/disabled)"
                        )
                    if order_idx.get(req, 99) >= order_idx.get(kind, -1):
                        raise DependencyError(
                            f"phase '{kind}' upstream '{req}' not earlier in PHASE_ORDER"
                        )

    def _log_phase_markers(self) -> None:
        for kind, instances in self.phases.items():
            for phase in instances:
                self.logger.log_phase_loaded(kind, phase.version_marker)

    # ---- per-bar ----
    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        bar_blocked = False
        phases_run: list[str] = []
        self._fired_entries = self._fired_exits = self._fired_adds = 0

        for item in PHASE_ORDER:
            if isinstance(item, FireSentinel):
                if bar_blocked and item in ENTRY_ONLY_SENTINELS:
                    continue
                self._fire(item, ctx)
                continue

            for phase in self.phases.get(item, []):
                if not phase.enabled:
                    continue
                if bar_blocked and item in ENTRY_ONLY_PHASES:
                    continue
                result = phase.evaluate(ctx)
                self.logger.log_phase(item, phase, result)
                ctx.bar_state.apply(item, result, module=phase.version_marker)
                phases_run.append(item)
                if result.blocked and item in ("regime", "cash"):
                    bar_blocked = True

        self.logger.log_tick(
            chain=phases_run,
            entries=self._fired_entries,
            exits=self._fired_exits,
            adds=self._fired_adds,
        )

    def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
        qc = self.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        active_by_value: dict[str, Any] = {s.value: s for s in getattr(qc, "_active", set())}

        if sentinel is FIRE_ENTRIES:
            for intent in ctx.bar_state.sized_orders:
                sym = active_by_value.get(intent.ticker)
                if sym is None or intent.qty <= 0:
                    continue
                qc.market_on_open_order(sym, intent.qty)
                price = float(qc.securities[sym].price)
                if not hasattr(qc, "_position_meta"):
                    qc._position_meta = {}
                qc._position_meta[sym] = {"entry_date": ctx.time, "entry_price": price}
                self._fired_entries += 1
                qc.log(f"ENTRY|{date_str}|{intent.ticker}|qty={intent.qty}|price~{price:.2f}")
        elif sentinel is FIRE_EXITS:
            for intent in ctx.bar_state.exit_intents:
                sym = active_by_value.get(intent.ticker)
                if sym is None:
                    continue
                qc.market_on_open_order(sym, intent.qty)  # qty negative
                getattr(qc, "_position_meta", {}).pop(sym, None)
                self._fired_exits += 1
        elif sentinel is FIRE_ADDS:
            for intent in ctx.bar_state.add_intents:
                sym = active_by_value.get(intent.ticker)
                if sym is None or intent.qty <= 0:
                    continue
                qc.market_on_open_order(sym, intent.qty)
                self._fired_adds += 1
        elif sentinel is FIRE_TRIMS:
            for intent in ctx.bar_state.trim_intents:
                sym = active_by_value.get(intent.ticker)
                if sym is None:
                    continue
                qc.market_on_open_order(sym, intent.qty)
