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

import hashlib
from typing import Any

from base import (
    BasePhase,
    CharterViolation,
    ConfigError,
    DegradedConfigError,
    DependencyError,
    PhaseInterface,
)
from config import Slot, StrategyConfig
from context import PhaseContext
from logger import ComponentLogger


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

# "filter" is INTENTIONALLY not required (Y, Falk): the champion applies its floors at the
# selection gate (lean_entry._coarse_selection), so there is no per-bar filter phase. "filter"
# stays a KNOWN_KIND (in PHASE_ORDER) — a future strategy MAY add a real per-bar filter phase.
REQUIRED_PHASES: tuple[str, ...] = ("universe", "signal", "sizing")

# #270/#272 fail-loud phase-stack gate. A CHAMPION (a config that actually trades) MUST wire an
# entry-confirm phase AND an exit phase — there is no implicit market-on-open default. The
# families (any one member satisfies the requirement):
ENTRY_PHASE_KINDS: frozenset[str] = frozenset({"entry_selection", "entry_timing"})
EXIT_PHASE_KINDS: frozenset[str] = frozenset(
    {"exit_hard", "exit_target", "exit_regime", "exit_rotation"}
)

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
    """Charter STRUCTURAL check: explicit-exposure (adds require portfolio_risk).

    The no-count-caps / no-time-exits rules are NOT enforced here anymore (Falk directive):
    a hardcoded param-name blocklist is brittle (misses novel names, gives false safety). Those
    rules live in CONVENTIONS §Charter + code-review. This keeps only the structural invariant
    that can't be a naming game — amplifying adds MUST pair with an explicit gross_exposure_cap.
    """
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
        self._validate_execution_stack(config)
        self._validate_single_adds()
        self._validate_dependencies()
        # #270/#274 two-clock: PRECOMPUTE the daily/intraday PHASE_ORDER subsets at init (not a
        # per-tick filter). on_data_with_ctx replays the daily subset, on_intraday_bar the intraday
        # subset. A FireSentinel is assigned to the clock of the phases it fires for (entries/
        # exits/adds/trims are execution → intraday once an intraday phase exists; with NO intraday
        # phase wired the intraday subset is EMPTY and on_data_with_ctx replays the FULL order →
        # behaviour IDENTICAL to the pre-#274 single-clock engine).
        self._daily_order, self._intraday_order = self._partition_clocks()
        self._log_phase_markers()
        self.logger.log_strategy_init(_config_hash(config), config.name, config.version)

    def _phase_clock(self, kind: str) -> str:
        """The clock a configured phase-kind runs on = the PHASE_RESOLUTION of its instances
        (all instances of a kind share a clock; mixed → ConfigError). Unconfigured kind → daily."""
        instances = self.phases.get(kind, [])
        if not instances:
            return "daily"
        clocks = {getattr(p, "PHASE_RESOLUTION", "daily") for p in instances}
        if len(clocks) > 1:
            raise ConfigError(
                f"phase kind '{kind}' has instances on MIXED clocks {sorted(clocks)} — "
                f"all instances of a kind must share one PHASE_RESOLUTION"
            )
        clock = clocks.pop()
        if clock not in ("daily", "intraday"):
            raise ConfigError(f"phase kind '{kind}' has invalid PHASE_RESOLUTION {clock!r}")
        return clock

    def _partition_clocks(self) -> tuple[list[str | FireSentinel], list[str | FireSentinel]]:
        """Split PHASE_ORDER into the daily-subset and intraday-subset, preserving order. A
        configured phase-kind goes to its clock; an UNCONFIGURED kind defaults daily (harmless —
        the loop skips kinds with no instances). A FireSentinel follows the clock of the phases it
        fires: FIRE_ENTRIES/FIRE_ADDS with the entry/adds clock, FIRE_EXITS/FIRE_TRIMS with the
        exit/profit clock; if those phases aren't wired the sentinel stays daily (fires nothing)."""
        sentinel_clock = {
            FIRE_ENTRIES: self._phase_clock("entry_timing") if self.phases.get("entry_timing")
            else self._phase_clock("entry_selection"),
            FIRE_EXITS: self._phase_clock("exit_hard"),
            FIRE_ADDS: self._phase_clock("adds"),
            FIRE_TRIMS: self._phase_clock("profit"),
        }
        daily: list[str | FireSentinel] = []
        intraday: list[str | FireSentinel] = []
        for item in PHASE_ORDER:
            if isinstance(item, FireSentinel):
                (intraday if sentinel_clock.get(item, "daily") == "intraday" else daily).append(item)
            else:
                (intraday if self._phase_clock(item) == "intraday" else daily).append(item)
        return daily, intraday

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

    def _validate_execution_stack(self, config: StrategyConfig) -> None:
        """#270/#272 fail-loud phase-stack gate: a CHAMPION must wire an entry-confirm phase
        (entry_selection|entry_timing) AND an exit phase (exit_*). No implicit market-on-open
        default — a config that would fire without them is the phantom blind-entry model and must
        crash at init, NOT silently blind-fill the open. A FIXTURE (config.is_fixture=True) is the
        only way to run an incomplete stack (regression/parity scaffolding), and is logged as such."""
        if config.is_fixture:
            qc_log = getattr(self.qc, "log", None)
            if callable(qc_log):
                qc_log(
                    f"FIXTURE_CONFIG|{config.name}|incomplete execution stack ALLOWED "
                    f"(is_fixture=True) — NOT a champion, never deploy as one (#272)"
                )
            return
        has_entry = any(self.phases.get(k) for k in ENTRY_PHASE_KINDS)
        has_exit = any(self.phases.get(k) for k in EXIT_PHASE_KINDS)
        missing: list[str] = []
        if not has_entry:
            missing.append(f"an ENTRY-confirm phase ({'|'.join(sorted(ENTRY_PHASE_KINDS))})")
        if not has_exit:
            missing.append(f"an EXIT phase ({'|'.join(sorted(EXIT_PHASE_KINDS))})")
        if missing:
            raise DegradedConfigError(
                f"champion config '{config.name}' is missing {' and '.join(missing)} — there is "
                f"NO implicit market-on-open default (#270). A config that would fire without a "
                f"wired entry-confirm + exit phase trades a phantom blind-entry model. Wire the "
                f"phases, or declare it a FIXTURE (StrategyConfig(is_fixture=True)) if it is "
                f"regression/parity scaffolding — never a silent champion (#272)."
            )

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

    # ---- per-bar (two-clock, #270/#274) ----
    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        """The DAILY decision clock (back-compat entry point — lean_entry calls this each daily
        bar). Replays the daily PHASE_ORDER subset. With no intraday phase wired the daily subset
        IS the full order → identical to the pre-#274 single-clock engine."""
        self._run_clock(self._daily_order, ctx)

    def on_intraday_bar(self, ctx: PhaseContext) -> None:
        """The INTRADAY execution clock (#270). Replays the intraday PHASE_ORDER subset against a
        completed 5-min bar on T+1. EMPTY until an intraday phase (entry-confirm/exit/stops) is
        wired — a no-op today (the split is behaviour-unchanged)."""
        if not self._intraday_order:
            return
        self._run_clock(self._intraday_order, ctx)

    def _run_clock(self, order: list[str | FireSentinel], ctx: PhaseContext) -> None:
        """Run one clock's PHASE_ORDER subset. Identical loop body to the pre-#274 engine; the
        ONLY change is iterating `order` (a clock subset) instead of the full PHASE_ORDER."""
        bar_blocked = False
        phases_run: list[str] = []
        self._fired_entries = self._fired_exits = self._fired_adds = 0

        for item in order:
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
