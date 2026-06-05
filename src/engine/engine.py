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
from dataclasses import fields, is_dataclass
from typing import Any

from engine.base import (
    BasePhase,
    CharterViolation,
    ConfigError,
    DegradedConfigError,
    DependencyError,
    PhaseInterface,
)
from engine.config import Slot, StrategyConfig
from engine.context import PhaseContext
from engine.logger import ComponentLogger
from engine.symbol_key import canonical_symbol_key


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

# Suppressed when bar_blocked (entry-side). Exit-side + tail run regardless.
ENTRY_ONLY_PHASES: frozenset[str] = frozenset({
    "entry_selection", "entry_timing", "sizing", "reentry",
    "eligibility", "portfolio_risk", "cash", "protective_stop", "adds",
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


def _params_canonical(params: Any) -> str:
    """Canonical params string for the config hash, EXCLUDING a phase's STRUCTURAL fields
    (`Params._HASH_EXCLUDE`). A structural field (e.g. sizing `resolution`, the clock-routing knob)
    is NOT an independent behavioral axis: it is FUNCTIONALLY DETERMINED by the entry-model phase set
    (intraday entry phases → intraday chain) and the chain-clock guard ENFORCES that coupling, so it
    is redundant for behavioral identity (the phase sets already differ in the hash) and cannot
    create a collision. Excluding it keeps the config_hash a stable BEHAVIORAL fingerprint (and keeps
    champion-asis at its e573e84b1ce1 baseline when the shared sizer gains the structural knob).
    A NON-structural param change still moves the hash (only the named structural fields are dropped)."""
    exclude = getattr(type(params), "_HASH_EXCLUDE", frozenset())
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
        self._tick_entry_value = 0.0  # #181 BUG-2 Stage 0: this tick's entry $ (commit-aware adds cap)

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
        self._validate_entry_chain_clock()
        self._log_phase_markers()
        self.logger.log_strategy_init(_config_hash(config), config.name, config.version)

    def _validate_entry_chain_clock(self) -> None:
        """#276b-1 FAIL-LOUD chain-clock guard. The entry-EXECUTION chain (the kinds from
        entry_selection up to FIRE_ENTRIES — entry_selection, entry_timing, sizing, reentry,
        eligibility, portfolio_risk, cash, protective_stop) is ONE ATOMIC sequence: a candidate stub
        is selected → timed → sized → capped → floored → FIRED, all on the SAME bar. If a WIRED chain
        kind resolves to a different clock than FIRE_ENTRIES, the stub never completes the sequence —
        e.g. sizing=daily while FIRE_ENTRIES=intraday leaves stubs UNSIZED at the fire seam → silent
        0 orders (the exact #276b-1 bug). Crash at init instead.

        Mirrors the per-kind MIXED-clocks guard, extended to the cross-kind chain. ESSENTIAL for
        programmatic configs (Epic-2 sweeps generate configs; a forgotten resolution on one chain
        phase would otherwise produce a silent-zero champion). FIRE_ENTRIES' clock = the entry clock
        (entry_timing if wired, else entry_selection); with no entry phase wired (a fixture) there is
        no chain to validate (FIRE_ENTRIES fires the daily stubs directly) → no-op."""
        if not (self.phases.get("entry_timing") or self.phases.get("entry_selection")):
            return  # no entry-confirm phase (fixture) → no entry-execution chain to enforce
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
        # #181 BUG-2 Stage 0: $-value of entry orders submitted THIS tick, for the commit-aware
        # gross cap on adds (LEAN fill-lag → total_holdings_value may not yet reflect these fills).
        self._tick_entry_value = 0.0

        for item in order:
            if isinstance(item, FireSentinel):
                if bar_blocked and item in ENTRY_ONLY_SENTINELS:
                    continue
                # #181 BUG-2 Stage 0: commit-aware second seam — bound add_intents by the gross cap
                # BEFORE firing them, counting this tick's in-flight entries (closes the leverage
                # hole where adds fired uncapped after FIRE_ENTRIES).
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
                    ctx.bar_state.bar_blocked = True  # #277: expose to lean_entry (regime→intraday gate)

        self.logger.log_tick(
            chain=phases_run,
            entries=self._fired_entries,
            exits=self._fired_exits,
            adds=self._fired_adds,
        )

    def _submit(self, qc: Any, sym: Any, intent: Any, tag: str = "") -> Any:
        """#276a fire-seam: submit ONE order, dispatching on intent.order_type. ONLY the engine's
        FIRE_* path calls the broker API — phases emit OrderIntent only. Returns the order ticket
        (for protective-stop tracking / cancel-on-exit). Unknown order_type → fail loud.

        `tag` (#archive B2): a per-order context string carried on the entry order so the results
        archive can recover the conditions-at-decision from /orders/read (the one durable channel —
        logs/charts/ObjectStore are dead). Empty for non-entry fires. Passed as a kwarg so a broker
        stub that does not accept it (older fakes) fails loud rather than mis-binding positionally."""
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
        # #276b-1 FIX3: key active symbols by the canonical key (single-source normalizer) so the
        # FIRE seam resolves intent.ticker regardless of case — kills the .value-vs-.lower() drift class.
        active_by_key: dict[str, Any] = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}

        if sentinel is FIRE_ENTRIES:
            for intent in ctx.bar_state.sized_orders:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None or intent.qty <= 0:
                    continue
                # #276a GUARD-3 (re-entry): a 2nd entry on a symbol that ALREADY has a live
                # protective stop this run would overwrite _position_meta + ORPHAN the first stop
                # ticket (FIRE_EXITS could never cancel it → it fires later against a position the
                # runtime already managed → over-sell). Fail loud until the cancel-replace
                # lifecycle (#276b) handles re-entry. Only fires when a protective stop is LIVE.
                _prior = getattr(qc, "_position_meta", {}).get(sym)
                if _prior and _prior.get("protective_stop_ticket") is not None \
                        and getattr(intent, "protective_stop", 0.0) > 0.0:
                    raise DegradedConfigError(
                        f"re-entry on {intent.ticker} with a LIVE protective stop already tracked "
                        f"— would orphan the prior GTC stop (over-sell risk). The cancel-replace "
                        f"lifecycle (#276b) must handle re-entry before this combo is allowed (#276a)"
                    )
                # #archive B2: build the per-entry context tag (the learn-substrate channel) via an
                # optional runtime hook — no-op string if the runtime doesn't emit it. Engine stays
                # generic: it doesn't know the strategy's context, the hook gathers it from qc state.
                _build_tag = getattr(qc, "_build_entry_tag", None)
                tag = _build_tag(sym) if callable(_build_tag) else ""
                self._submit(qc, sym, intent, tag=tag)  # the entry, per intent.order_type
                # #276b-1 (Gemini fix #1): mark the entry IN-FLIGHT so the runtime's intraday
                # candidate-injection won't re-inject this sym before the order resolves (double-
                # entry). Optional hook — no-op if the runtime doesn't track pending entries.
                _mark_pending = getattr(qc, "_mark_entry_pending", None)
                if callable(_mark_pending):
                    _mark_pending(sym)
                price = float(qc.securities[sym].price)
                if not hasattr(qc, "_position_meta"):
                    qc._position_meta = {}
                meta: dict[str, Any] = {"entry_date": ctx.time, "entry_price": price}
                # #339 rotation: stamp the entry's decision_score (optional runtime hook) so the
                # rotation phase can rank HELD positions by signal strength vs new candidates. No-op
                # if the runtime doesn't provide the hook (engine stays strategy-generic).
                _score_hook = getattr(qc, "_decision_score_for", None)
                if callable(_score_hook):
                    meta["decision_score"] = _score_hook(sym)
                # #290 GTC PROTECTIVE STOP — the catastrophic floor UNDER the runtime exit. A
                # resting broker-side stop_market (GTC by default) placed alongside the entry, so
                # it fires intrabar on a gap/outage/halt even when the runtime exit doesn't. We
                # track its TICKET so FIRE_EXITS cancels it on the runtime exit fill (no orphan
                # resting stop → no double-sell). qty is the NEGATIVE of the entry (sell-stop).
                if getattr(intent, "protective_stop", 0.0) > 0.0:
                    stop_ticket = qc.stop_market_order(sym, -intent.qty, intent.protective_stop)
                    meta["protective_stop_ticket"] = stop_ticket
                    meta["protective_stop_price"] = float(intent.protective_stop)
                    # #378: track the qty the resting stop covers (NEGATIVE, sell-stop) so a later add
                    # can grow it to the new total (orig+add) via _resize_protective_stop_for_add.
                    meta["protective_stop_qty"] = -int(intent.qty)
                    qc.log(
                        f"PROTECTIVE_STOP|{date_str}|{intent.ticker}|qty={-intent.qty}|"
                        f"stop={intent.protective_stop:.2f} (GTC catastrophic floor #290)"
                    )
                qc._position_meta[sym] = meta
                self._fired_entries += 1
                # #181 BUG-2 Stage 0: accumulate this tick's entry exposure so the FIRE_ADDS gross
                # cap is commit-aware (fill-lag safe — see _bound_adds_to_gross_cap).
                self._tick_entry_value += abs(intent.qty) * price
                qc.log(f"ENTRY|{date_str}|{intent.ticker}|qty={intent.qty}|price~{price:.2f}")
        elif sentinel is FIRE_EXITS:
            for intent in ctx.bar_state.exit_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None:
                    continue
                self._cancel_protective_stop(qc, sym, date_str)  # BEFORE the exit — no orphan
                self._submit(qc, sym, intent)  # the exit (qty negative), per intent.order_type
                getattr(qc, "_position_meta", {}).pop(sym, None)
                self._fired_exits += 1
        elif sentinel is FIRE_ADDS:
            for intent in ctx.bar_state.add_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None or intent.qty <= 0:
                    continue
                # #378 (was #276a GUARD-2): an add grows the position → the resting protective stop
                # must GROW to cover the new total (orig+add), else the added shares ride unprotected.
                # Resize the stop FIRST (atomic in-place, qc.update_order_quantity); only then submit
                # the add. If the resize fails (or the lifecycle is unwired) the add is refused — the
                # floor is NEVER left under-sized.
                if not self._resize_protective_stop_for_add(qc, sym, int(intent.qty), date_str):
                    continue  # resize failed → skip the add (position+stop stay at orig → no gap)
                self._submit(qc, sym, intent)
                self._fired_adds += 1
        elif sentinel is FIRE_TRIMS:
            for intent in ctx.bar_state.trim_intents:
                sym = active_by_key.get(canonical_symbol_key(intent.ticker))
                if sym is None:
                    continue
                # #276a GUARD-1 (trim + live stop): a partial trim (+10→+6) leaves the resting
                # stop at the full -10 → if it fires it over-sells, flipping long→short. The
                # catastrophic over-sell class. Fail loud until #276b's cancel-replace re-sizes the
                # stop on trim. Only fires when a protective stop is LIVE.
                self._guard_position_change_vs_protective_stop(qc, sym, "trim")
                self._submit(qc, sym, intent)

    def _bound_adds_to_gross_cap(self, ctx: PhaseContext) -> None:
        """#181 BUG-2 Stage 0: COMMIT-AWARE gross cap at the FIRE_ADDS seam. Reuses the configured
        portfolio_risk phase's OWN cap math (`bound_adds`, single-source — no duplicated ceiling
        logic) to bound `add_intents` before they fire, accounting for this tick's in-flight entry
        orders (`self._tick_entry_value`). Closes the leverage hole where adds previously fired with
        no gross check after FIRE_ENTRIES. No-op when no portfolio_risk phase is wired (e.g. the
        champion_asis fixture) — so behaviour is unchanged where the cap is absent."""
        for cap in self.phases.get("portfolio_risk", []):
            if getattr(cap, "enabled", True) and hasattr(cap, "bound_adds"):
                cap.bound_adds(ctx, self._tick_entry_value)

    def _resize_protective_stop_for_add(self, qc: Any, sym: Any, add_qty: int, date_str: str) -> bool:
        """#378 floor-safe pyramid add — atomically GROW the resting GTC protective stop to cover the
        post-add total qty (orig+add) via the `qc.update_order_quantity` hook (LEAN OrderTicket.update,
        in-place → NO cancel-replace gap), BEFORE the add is submitted.

        Returns True when the add MAY proceed:
          - no live protective stop tracked → nothing to maintain → add is unguarded (the champion's
            no-stop path, unchanged); or
          - the stop was successfully grown to cover orig+add.
        Returns False when the resize FAILED → the caller SKIPS the add, so position + stop both stay
        at orig (fully covered) — at no instant are held shares left without a covering stop.

        FAIL-LOUD when the resize lifecycle is UNWIRED (no `qc.update_order_quantity`): an add onto a
        stop-protected position is refused (the #276a guard's reason stands — a fixed-qty stop would
        be under-sized). The atomic in-place update replaces the old cancel-replace plan: there is no
        cancel-succeeds-replace-fails window — the resting order's quantity changes, or it does not."""
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if not meta or meta.get("protective_stop_ticket") is None:
            return True  # no live protective stop → no floor to maintain → add proceeds unguarded
        update_hook = getattr(qc, "update_order_quantity", None)
        if not callable(update_hook):
            raise DegradedConfigError(
                f"add on {sym.value} with a LIVE protective stop, but the stop-resize lifecycle "
                f"(qc.update_order_quantity, #378) is NOT wired — the add would leave the original-qty "
                f"stop under-sized (added shares unprotected). Wire the resize hook before allowing "
                f"adds onto stop-protected positions (#276a guard / #378 lifecycle)"
            )
        ticket = meta["protective_stop_ticket"]
        if "protective_stop_qty" not in meta:
            # invariant break: a live stop ticket MUST carry its covered qty (set at entry). Defaulting
            # to 0 here would resize the stop to cover ONLY the added shares → drop the original →
            # under-protection. Fail loud, never guess the floor (#378 review).
            raise DegradedConfigError(
                f"add on {sym.value}: protective_stop_ticket present but protective_stop_qty missing — "
                f"cannot safely resize the floor (would under-cover the original position) (#378)"
            )
        cur_qty = int(meta["protective_stop_qty"])          # NEGATIVE (sell-stop)
        new_qty = cur_qty - int(add_qty)                    # grow more-negative: -10 - 5 = -15
        ok = bool(update_hook(ticket, new_qty))
        if not ok:
            qc.log(
                f"PROTECTIVE_STOP_RESIZE_FAIL|{date_str}|{sym.value}|update {cur_qty}->{new_qty} "
                f"REJECTED → ADD SKIPPED (floor stays at {cur_qty}, no unprotected shares) #378"
            )
            return False
        meta["protective_stop_qty"] = new_qty               # the stop now covers orig+add
        qc.log(
            f"PROTECTIVE_STOP_RESIZE|{date_str}|{sym.value}|{cur_qty}->{new_qty} "
            f"(stop grown to cover orig+add — #378 floor-safe pyramid)"
        )
        return True

    def reconcile_protective_stop_to_position(self, qc: Any, sym: Any, date_str: str = "") -> None:
        """#378 reconcile — after an order resolves, ensure the resting protective stop covers EXACTLY
        the held qty. Handles the add-didn't-fill edge (HQ): the stop is pre-grown at submit (over-
        coverage, the safe direction), but if the add is REJECTED/halted/partial the stop is left
        over-sized (covers more than held → over-sell-to-short on a later trigger). Resize it back to
        -position. Called from the runtime's on_order_event on any terminal order event.

        No-op when: no live stop; the qty already matches; the position is FLAT (an exit/floor-fill —
        the cancel-on-exit / GTC-floor-fill paths own that, this must not fight them); or the resize
        lifecycle is unwired. Public (the runtime calls it)."""
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if not meta or meta.get("protective_stop_ticket") is None:
            return
        if "protective_stop_qty" not in meta:
            return  # invariant break elsewhere; don't guess the floor in a fill callback (no crash, no resize)
        holding = qc.portfolio[sym]
        if not getattr(holding, "invested", False):
            return  # flat → exit/floor-fill path owns the cancel+pop; don't fight it
        desired = -int(holding.quantity)
        cur = int(meta["protective_stop_qty"])
        if desired == cur:
            return  # stop already matches the held qty (the common path: add filled as intended)
        update_hook = getattr(qc, "update_order_quantity", None)
        if not callable(update_hook):
            return  # no resize lifecycle wired → nothing to reconcile with (the add-guard gates entry)
        if bool(update_hook(meta["protective_stop_ticket"], desired)):
            meta["protective_stop_qty"] = desired
            qc.log(
                f"PROTECTIVE_STOP_RECONCILE|{date_str}|{sym.value}|{cur}->{desired} "
                f"(stop matched to held qty — add did not fully fill; #378)"
            )

    def _guard_position_change_vs_protective_stop(self, qc: Any, sym: Any, op: str) -> None:
        """#276a GUARD-1/2: a trim/add on a position with a LIVE protective stop, without the
        cancel-replace lifecycle (#276b), is a footgun — a trim leaves the full-qty stop → over-sell
        (long→short); an add leaves added shares unprotected. Fail loud until #276b resizes the
        stop on these ops. Only triggers when a protective stop is actually tracked (no protective
        stop → no risk → no-op, so the champion's no-stop fixture path is unaffected)."""
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
        """#290/#276a cancel-on-exit: cancel the resting GTC protective stop when the position
        is being exited by the runtime — so no orphan resting stop survives to double-sell a
        position the runtime already closed. THE load-bearing safety lifecycle (HQ's #1 review
        target). Idempotent: no-op if no protective stop is tracked for this symbol."""
        meta = getattr(qc, "_position_meta", {}).get(sym)
        if not meta:
            return
        ticket = meta.get("protective_stop_ticket")
        if ticket is None:
            return
        # cancel via the ticket (LEAN OrderTicket.cancel()); guard for a fake/None in tests.
        cancel = getattr(ticket, "cancel", None)
        if callable(cancel):
            cancel()
        qc.log(f"PROTECTIVE_STOP_CANCEL|{date_str}|{sym.value}|runtime exit → cancel resting GTC (#290)")
