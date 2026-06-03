from __future__ import annotations

import hashlib
from dataclasses import fields, is_dataclass
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
from symbol_key import canonical_symbol_key


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
    "reentry", "eligibility", "portfolio_risk", "cash", "protective_stop",
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

ENTRY_ONLY_PHASES: frozenset[str] = frozenset({
    "entry_selection", "entry_timing", "sizing", "reentry",
    "eligibility", "portfolio_risk", "cash", "protective_stop", "adds",
})
ENTRY_ONLY_SENTINELS: frozenset[FireSentinel] = frozenset({FIRE_ENTRIES, FIRE_ADDS})
ALWAYS_RUN: frozenset[str] = frozenset({"diagnostics", "circuit_breaker"})

REQUIRED_PHASES: tuple[str, ...] = ("universe", "signal", "sizing")

ENTRY_PHASE_KINDS: frozenset[str] = frozenset({"entry_selection", "entry_timing"})
EXIT_PHASE_KINDS: frozenset[str] = frozenset(
    {"exit_hard", "exit_target", "exit_regime", "exit_rotation"}
)

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
    if _kind_enabled(config, "adds") and not _kind_enabled(config, "portfolio_risk"):
        raise CharterViolation(
            "adds enabled without portfolio_risk (gross_exposure_cap) — "
            "implicit exposure forbidden; amplifying adds require an explicit cap"
        )


def _params_canonical(params: Any) -> str:
    exclude: frozenset[str] = getattr(type(params), "_HASH_EXCLUDE", frozenset())
    if not exclude or not is_dataclass(params):
        return repr(params)
    inner = ", ".join(
        f"{f.name}={getattr(params, f.name)!r}"
        for f in fields(params) if f.name not in exclude
    )
    return f"{type(params).__qualname__}({inner})"


def _config_hash(config: StrategyConfig) -> str:
    parts: list[str] = [config.name, config.version]
    for kind in sorted(config.phases):
        for slot in _slots(config.phases[kind]):
            parts.append(f"{kind}:{slot.impl.__name__}:{slot.enabled}:{_params_canonical(slot.params)}")
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
        self._tick_entry_value = 0.0

        validate_invariants(config)
        self._validate_known_kinds(config)
        self.phases: dict[str, list[PhaseInterface]] = self._instantiate(config)
        self._validate_required_phases()
        self._validate_execution_stack(config)
        self._validate_single_adds()
        self._validate_dependencies()
        self._daily_order, self._intraday_order = self._partition_clocks()
        self._validate_entry_chain_clock()
        self._log_phase_markers()
        self.logger.log_strategy_init(_config_hash(config), config.name, config.version)

    def _validate_entry_chain_clock(self) -> None:
        if not (self.phases.get("entry_timing") or self.phases.get("entry_selection")):
            return
        fire_clock = (self._phase_clock("entry_timing") if self.phases.get("entry_timing")
                      else self._phase_clock("entry_selection"))
        start = PHASE_ORDER.index("entry_selection")
        end = PHASE_ORDER.index(FIRE_ENTRIES)
        chain_kinds = [k for k in PHASE_ORDER[start:end] if isinstance(k, str)]
        mismatched = [
            f"{k}={self._phase_clock(k)}" for k in chain_kinds
            if self.phases.get(k) and self._phase_clock(k) != fire_clock
        ]
        if mismatched:
            raise ConfigError(
                f"entry-execution chain mixed clocks: {', '.join(mismatched)} but "
                f"FIRE_ENTRIES={fire_clock} — the chain (entry_selection..FIRE_ENTRIES) is one atomic "
                f"sequence and MUST share one clock; a mismatched kind leaves stubs unsized/unfloored "
                f"at the fire seam (silent 0 orders). Set PHASE_RESOLUTION (the resolution param) "
                f"consistently across the entry-execution chain (#276b-1)."
            )

    def _phase_clock(self, kind: str) -> str:
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

    def _validate_known_kinds(self, config: StrategyConfig) -> None:
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

    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        self._run_clock(self._daily_order, ctx)

    def on_intraday_bar(self, ctx: PhaseContext) -> None:
        if not self._intraday_order:
            return
        self._run_clock(self._intraday_order, ctx)

    def _run_clock(self, order: list[str | FireSentinel], ctx: PhaseContext) -> None:
        bar_blocked = False
        phases_run: list[str] = []
        self._fired_entries = self._fired_exits = self._fired_adds = 0
        self._tick_entry_value = 0.0

        for item in order:
            if isinstance(item, FireSentinel):
                if bar_blocked and item in ENTRY_ONLY_SENTINELS:
                    continue
                if item is FIRE_ADDS:
                    self._bound_adds_to_gross_cap(ctx)
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
                    ctx.bar_state.bar_blocked = True

        self.logger.log_tick(
            chain=phases_run,
            entries=self._fired_entries,
            exits=self._fired_exits,
            adds=self._fired_adds,
        )

    def _submit(self, qc: Any, sym: Any, intent: Any, tag: str = "") -> Any:
        ot = getattr(intent, "order_type", "market_on_open")
        if ot == "market_on_open":
            return qc.market_on_open_order(sym, intent.qty, tag=tag)
        if ot == "market":
            return qc.market_order(sym, intent.qty, tag=tag)
        if ot == "stop_market":
            return qc.stop_market_order(sym, intent.qty, intent.stop, tag=tag)
        if ot == "limit":
            return qc.limit_order(sym, intent.qty, intent.price, tag=tag)
        raise ConfigError(
            f"unknown OrderIntent.order_type {ot!r} for {intent.ticker} — the fire seam dispatches "
            f"market_on_open|market|stop_market|limit only (#276a)"
        )

    def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
        qc = self.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        active_by_key: dict[str, Any] = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}

        if sentinel is FIRE_ENTRIES:
            for intent in ctx.bar_state.sized_orders:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None or intent.qty <= 0:
                    continue
                _prior = getattr(qc, "_position_meta", {}).get(sym)
                if _prior and _prior.get("protective_stop_ticket") is not None \
                        and getattr(intent, "protective_stop", 0.0) > 0.0:
                    raise DegradedConfigError(
                        f"re-entry on {intent.ticker} with a LIVE protective stop already tracked "
                        f"— would orphan the prior GTC stop (over-sell risk). The cancel-replace "
                        f"lifecycle (#276b) must handle re-entry before this combo is allowed (#276a)"
                    )
                _build_tag = getattr(qc, "_build_entry_tag", None)
                tag = _build_tag(sym) if callable(_build_tag) else ""
                self._submit(qc, sym, intent, tag=tag)
                _mark_pending = getattr(qc, "_mark_entry_pending", None)
                if callable(_mark_pending):
                    _mark_pending(sym)
                price = float(qc.securities[sym].price)
                if not hasattr(qc, "_position_meta"):
                    qc._position_meta = {}
                meta: dict[str, Any] = {"entry_date": ctx.time, "entry_price": price}
                _score_hook = getattr(qc, "_decision_score_for", None)
                if callable(_score_hook):
                    meta["decision_score"] = _score_hook(sym)
                if getattr(intent, "protective_stop", 0.0) > 0.0:
                    stop_ticket = qc.stop_market_order(sym, -intent.qty, intent.protective_stop)
                    meta["protective_stop_ticket"] = stop_ticket
                    meta["protective_stop_price"] = float(intent.protective_stop)
                    qc.log(
                        f"PROTECTIVE_STOP|{date_str}|{intent.ticker}|qty={-intent.qty}|"
                        f"stop={intent.protective_stop:.2f} (GTC catastrophic floor #290)"
                    )
                qc._position_meta[sym] = meta
                self._fired_entries += 1
                self._tick_entry_value += abs(intent.qty) * price
                qc.log(f"ENTRY|{date_str}|{intent.ticker}|qty={intent.qty}|price~{price:.2f}")
        elif sentinel is FIRE_EXITS:
            for intent in ctx.bar_state.exit_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None:
                    continue
                self._cancel_protective_stop(qc, sym, date_str)
                self._submit(qc, sym, intent)
                getattr(qc, "_position_meta", {}).pop(sym, None)
                self._fired_exits += 1
        elif sentinel is FIRE_ADDS:
            for intent in ctx.bar_state.add_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None or intent.qty <= 0:
                    continue
                self._guard_position_change_vs_protective_stop(qc, sym, "add")
                self._submit(qc, sym, intent)
                self._fired_adds += 1
        elif sentinel is FIRE_TRIMS:
            for intent in ctx.bar_state.trim_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None:
                    continue
                self._guard_position_change_vs_protective_stop(qc, sym, "trim")
                self._submit(qc, sym, intent)

    def _bound_adds_to_gross_cap(self, ctx: PhaseContext) -> None:
        for cap in self.phases.get("portfolio_risk", []):
            if getattr(cap, "enabled", True) and hasattr(cap, "bound_adds"):
                cap.bound_adds(ctx, self._tick_entry_value)

    def _guard_position_change_vs_protective_stop(self, qc: Any, sym: Any, op: str) -> None:
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if meta and meta.get("protective_stop_ticket") is not None:
            raise DegradedConfigError(
                f"{op} on {sym.value} with a LIVE protective stop — the resting GTC stop is sized "
                f"to the original qty, so a {op} leaves it "
                f"{'over-sized (over-sell long→short risk)' if op == 'trim' else 'under-sized (added shares unprotected)'}"
                f". The cancel-replace lifecycle (#276b) must resize the stop on {op} before this "
                f"combo is allowed (#276a guard)"
            )

    def _cancel_protective_stop(self, qc: Any, sym: Any, date_str: str) -> None:
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if not meta:
            return
        ticket = meta.get("protective_stop_ticket")
        if ticket is None:
            return
        cancel = getattr(ticket, "cancel", None)
        if callable(cancel):
            cancel()
        qc.log(f"PROTECTIVE_STOP_CANCEL|{date_str}|{sym.value}|runtime exit → cancel resting GTC (#290)")
