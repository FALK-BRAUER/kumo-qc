"""Profit-take phase: PgProfitTake — the #379 cash-lock lever (prover-gated/ASYMMETRIC partial trim).

Kind: profit · Clock: DAILY (co-clocked with exit_hard — the #379 over-sell invariant) · Marker:
pg_profit_take_<variant>_v1.

The champion is cash-locked (#340-C: ~18 names hold all the cash → new entries blocked). Free cash from
the NEVER-PROVED FADERS (took a slot, never became a monster) via a PARTIAL trim — bank the small gain,
recycle the capital — WITHOUT touching the proved monsters.

ASYMMETRIC PROVER-GATE (the only version with a chance — a symmetric profit-take trims monsters → caps
the run → dies like rotation; HOOD +175%: trim-at-+50% misses +125 = catastrophic): trim ONLY
never-proved positions (`is_proved` False, from the SHARED prover state — never a re-impl); EXEMPT every
proved position (≥+5% MFE = a potential monster → let it run). The inverse of the exit-model's gate
(that EXEMPTED monsters from a loser-cut; this EXEMPTS them from a trim).

Trim mechanic by variant (T1 first — simplest, no candidate coupling):
  T1 age-gated fader : a never-proved position held ≥ `fade_age_days` → trim `trim_pct`. (Held that long
                       without proving = a fader/slot-occupier; the monsters prove EARLY per the data.)
  T2 stalled fader   : never-proved AND below daily Tenkan (rolled over) → trim.
  T3 candidate-driven: never-proved AND a fresh higher-conviction candidate needs the cash → trim.

PARTIAL trim (keep a residual — a late bloomer isn't fully forfeited). The engine resizes the protective
stop DOWN on the trim (#379 Part A); a FULL trim is refused there (use an exit). REDEPLOY is the decisive
metric (HQ): each trim logs the cash freed — the screen checks whether a new entry filled the freed
headroom; idle freed cash = the trim is pure downside (signal-scarcity, not cash-lock).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace
from phases.shared.prover_state import is_proved, update_prover_state


class PgProfitTake(BasePhase):
    PHASE_KIND = "profit"
    PHASE_RESOLUTION = "daily"          # MUST co-clock with exit_hard (the #379 over-sell invariant)
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["trim_intents"]

    COMPLEXITY = ComplexityDecl(free_params=2, note="trim_pct + fade_age_days (T1); variant fixed per run.")

    @dataclass(slots=True)
    class Params:
        variant: str = "T1"            # T1 age-gated / T2 stalled / T3 candidate-driven
        prove_pct: float = 0.05        # +5% MFE = PROVED → EXEMPT (shared prover state)
        trim_pct: float = 0.50         # trim this fraction of a never-proved fader (keep the residual)
        fade_age_days: int = 20        # T1: never-proved held ≥ this many days → a fader → trim
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"trim_pct": (0.33, 0.50, 0.67), "fade_age_days": (15, 20, 30)})

    def __init__(self, params: "PgProfitTake.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _is_fader(self, qc: Any, sym: Any, m: dict, ctx: PhaseContext) -> bool:
        """The never-proved fader trigger, by variant (caller already checked NOT proved)."""
        v = self.p.variant
        if v == "T1":
            entry_date = m.get("entry_date")
            if entry_date is None:
                return False
            try:
                age = (ctx.time - entry_date).days
            except (TypeError, AttributeError):
                return False
            return age >= self.p.fade_age_days
        if v in ("T2", "T3"):
            ind = getattr(qc, "_indicators", {}).get(sym)
            d_ichi = ind.get("d_ichi") if ind else None
            if d_ichi is None or not getattr(d_ichi, "is_ready", False):
                return False
            try:
                stalled = float(qc.securities[sym].close) < float(d_ichi.tenkan.current.value)
            except (KeyError, AttributeError, TypeError, ValueError):
                return False
            if v == "T2":
                return stalled
            # T3: stalled AND a fresh higher-conviction candidate exists (needs the cash)
            snap = getattr(qc, "_candidate_snapshot", {})
            held = set(getattr(qc, "_position_meta", {}))
            return stalled and any(s not in held for s in snap)
        return False

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        update_prover_state(qc, self.p.prove_pct)   # SHARED prover state (MFE, survive-cold, GC)
        pf = qc.portfolio
        meta = getattr(qc, "_position_meta", {})
        trims: list[str] = []
        freed = 0.0
        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False):
                continue
            if is_proved(qc, sym):
                continue  # PROVED monster → EXEMPT (never trim a monster — the asymmetry, the teeth)
            m = meta.get(sym)
            if not m or "entry_price" not in m:
                continue
            if not self._is_fader(qc, sym, m, ctx):
                continue
            try:
                close = float(qc.securities[sym].close)
                qty = int(holding.quantity)
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            trim_qty = int(qty * self.p.trim_pct)
            if trim_qty < 1 or trim_qty >= qty:
                continue  # nothing to trim, or a full trim (that's an EXIT, not a trim — #379 Part A)
            ctx.bar_state.trim_intents.append(OrderIntent(
                ticker=sym.value, qty=-trim_qty, price=close, stop=0.0,
                module="profit.pg_profit_take", risk_dollars=0.0,
            ))
            freed += trim_qty * close
            trims.append(sym.value)
            log = getattr(qc, "log", None)
            if callable(log):
                # REDEPLOY INSTRUMENTATION (HQ #379-B flag 2): cash freed per trim → the screen checks
                # whether a new entry fills the freed headroom (idle = signal-scarcity, the trim is downside).
                log(f"PROFIT_TRIM_{self.p.variant}|{date_str}|{sym.value}|never-proved fader|"
                    f"trim {trim_qty}/{qty} @ {close:.2f} freed~${trim_qty * close:,.0f}")
        return PhaseResult(
            decision=trims, blocked=False,
            reason=f"{len(trims)} prover-gated fader-trim(s) [{self.p.variant}] freed~${freed:,.0f}",
            facts={"trims": len(trims), "freed_cash": freed}, metrics={},
        )

    @property
    def version_marker(self) -> str:
        return f"pg_profit_take_{self.p.variant}_v1"
