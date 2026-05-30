from __future__ import annotations
import hashlib
import json
from typing import Any
from engine.base import PhaseInterface, CharterViolation, DependencyError, ConfigError
from engine.context import PhaseContext
from engine.logger import ComponentLogger


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


def _phase_enabled(config: dict, kind: str) -> bool:
    """True if any sub-phase of `kind` is enabled in config."""
    phase_cfg = config.get("phases", {}).get(kind)
    if phase_cfg is None:
        return False
    cfgs = phase_cfg if isinstance(phase_cfg, list) else [phase_cfg]
    return any(c.get("enabled", True) for c in cfgs)


def validate_invariants(config: dict) -> None:
    for kind, phase_cfg in config.get("phases", {}).items():
        cfgs = phase_cfg if isinstance(phase_cfg, list) else [phase_cfg]
        for cfg in cfgs:
            for param_key in cfg.get("params", {}):
                if param_key in FORBIDDEN_PARAMS:
                    raise CharterViolation(
                        f"'{param_key}' is a forbidden param (count cap / time exit) in phase '{kind}'"
                    )

    # C1: explicit-exposure invariant — amplifying adds REQUIRE an explicit exposure cap.
    # An uncapped pyramid over margin is the Pe -0.055 cloud blowup. No implicit caps.
    if _phase_enabled(config, "adds") and not _phase_enabled(config, "portfolio_risk"):
        raise CharterViolation(
            "adds enabled without portfolio_risk (gross_exposure_cap) — "
            "implicit exposure forbidden; amplifying adds require explicit cap"
        )


def _config_hash(config: dict) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _phase_order_index() -> dict[str, int]:
    """Map each phase kind string to its first index in PHASE_ORDER (ignores FireSentinels)."""
    idx = {}
    for i, item in enumerate(PHASE_ORDER):
        if isinstance(item, str) and item not in idx:
            idx[item] = i
    return idx


def _count_enabled_subphases(phase_cfg) -> int:
    cfgs = phase_cfg if isinstance(phase_cfg, list) else [phase_cfg]
    return sum(1 for c in cfgs if c.get("enabled", True))


class StrategyEngine:
    REQUIRED_PHASES = {"universe", "signal", "sizing"}

    def __init__(self, config: dict, qc: Any, phase_instances: dict[str, list[PhaseInterface]]):
        self.config = config
        self.qc = qc
        self.phases = phase_instances
        self.logger = ComponentLogger(qc)
        self._fired_entries = 0
        self._fired_exits = 0
        self._fired_adds = 0

        # ── Validate invariants (C1 + forbidden params) ──
        validate_invariants(config)

        # ── 1. Required-phases check ──
        phases = config.get("phases", {})
        for required in self.REQUIRED_PHASES:
            cfg = phases.get(required)
            if cfg is None:
                raise ConfigError(f"Missing required phase: '{required}'")
            cfgs = cfg if isinstance(cfg, list) else [cfg]
            if not any(c.get("enabled", True) for c in cfgs):
                raise ConfigError(f"Required phase '{required}' is present but all instances are disabled")

        # ── 2. Single-adds enforcement ──
        adds_cfg = phases.get("adds")
        if adds_cfg is not None and _count_enabled_subphases(adds_cfg) > 1:
            raise CharterViolation(
                "Only one adds phase may be enabled at a time (adds implementations are mutually exclusive)"
            )

        # ── 3. Dependency check ──
        order_idx = _phase_order_index()
        for kind, instances in phase_instances.items():
            for inst in instances:
                if not inst.enabled:
                    continue
                for upstream in inst.REQUIRES_UPSTREAM:
                    upstream_cfg = phases.get(upstream)
                    if upstream_cfg is None:
                        raise DependencyError(
                            f"Phase '{kind}' requires upstream '{upstream}' but it is not configured"
                        )
                    upstream_cfgs = upstream_cfg if isinstance(upstream_cfg, list) else [upstream_cfg]
                    if not any(c.get("enabled", True) for c in upstream_cfgs):
                        raise DependencyError(
                            f"Phase '{kind}' requires upstream '{upstream}' but all instances are disabled"
                        )
                    if upstream not in order_idx or kind not in order_idx:
                        continue  # safety: should not happen
                    if order_idx[upstream] >= order_idx[kind]:
                        raise DependencyError(
                            f"Phase '{kind}' requires upstream '{upstream}' but '{upstream}' appears "
                            f"after '{kind}' in PHASE_ORDER"
                        )

        # ── 4. Version-marker logging ──
        for kind, instances in phase_instances.items():
            for inst in instances:
                if not inst.enabled:
                    continue
                self.logger.log_phase_loaded(
                    kind=kind,
                    module=inst.__class__.__module__,
                    marker=inst.version_marker,
                )

        self.logger.log_strategy_init(
            config_hash=_config_hash(config),
            name=config.get("name", "unknown"),
            version=config.get("version", "0.0.0"),
        )

    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        bar_blocked = False
        phases_run: list[str] = []
        self._fired_entries = self._fired_exits = self._fired_adds = 0

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
            entries=self._fired_entries,
            exits=self._fired_exits,
            adds=self._fired_adds,
        )

    def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
        qc = self.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        active_by_value: dict = {s.value: s for s in getattr(qc, "_active", set())}

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
                qc.market_on_open_order(sym, intent.qty)  # qty is negative
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
