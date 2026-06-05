"""Exit phase: ProverGatedLoserExit — the #339-RUN1 exit-model lever (fix the realized loser tail
WITHOUT touching the winners).

Kind: exit_hard · Clock: DAILY (EOD) · Marker: prover_gated_loser_exit_<variant>_v1

#339 target: S1's realized -15.2% tail is ALL closed losers (CEG/TSM/BITX/EBAY/HPE/MRVL/...); the
monsters (HOOD/KGC) are NEVER closed (open paper +27.7%). Cut the LOSERS earlier, leave the monsters
fully alone.

THE PROVER-GATE (the discriminator #374's plain hard-stop LACKED → why it clipped runners): a position
that has PROVED — gone >= +`prove_pct` (default +5%) above entry at any point — is a potential monster
→ EXEMPT from this loser-exit → it keeps the champion's full cloud-bottom let-run. A NEVER-PROVED
position (bought → straight down, never +5%) that's losing → cut it EARLIER (smaller loss). The
monsters prove early (HOOD/KGC ran before any dip) → exempt → run free; the 19 losers mostly never
prove → cut. Runner-SURVIVAL by construction (#374 lesson: measure runner-survival, not just loser-cut).

Cut-MECHANIC varies by variant (NO time-based exits — charter); the prover-gate SPINE is identical:
  E1 fixed-%      : never-proved AND close <= entry × (1-stop_pct)  [default -8%]
  E2 weekly-Kijun : never-proved AND close < weekly Kijun
  E3 weekly-cloud : never-proved AND close < weekly-cloud TOP (max senkou; vs the champion's cloud
                    BOTTOM = an EARLIER loser-cut)

Composes WITH CloudAdherenceTrail (the champion's cloud-bottom exit handles the proved monsters); this
phase only adds the earlier never-proved-loser cut. FULL-exit (FIRE_EXITS cancels the protective stop).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.prover_state import is_proved, update_prover_state


class ProverGatedLoserExit(BasePhase):
    PHASE_KIND = "exit_hard"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        variant: str = "E1"        # E1 fixed-% / E2 weekly-Kijun / E3 weekly-cloud-top
        prove_pct: float = 0.05    # +5% above entry (ever) → PROVED → exempt (the discriminator)
        stop_pct: float = 0.08     # E1: cut a never-proved loser at -8% from entry
        enabled: bool = True

    def __init__(self, params: "ProverGatedLoserExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        update_prover_state(qc, self.p.prove_pct)   # SHARED prover state (MFE, survive-cold, GC) — the
        #                                              SINGLE source both this phase + PgProfitTake read.
        pf = qc.portfolio
        meta = getattr(qc, "_position_meta", {})
        indicators = getattr(qc, "_indicators", {})
        cut: list[str] = []

        for sym, holding in list(pf.items()):
            if not getattr(holding, "invested", False):
                continue
            if is_proved(qc, sym):
                continue  # PROVED = potential monster → EXEMPT (the teeth; cloud-bottom lets it run)
            m = meta.get(sym)
            ind = indicators.get(sym)
            if m is None or ind is None or "entry_price" not in m:
                continue  # no entry context / cold indicators → don't force a cut (cloud-bottom guards it)
            try:
                close = float(qc.securities[sym].close)
                entry = float(m["entry_price"])
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            if entry <= 0.0 or close <= 0.0:
                continue

            # never-proved loser → apply the variant cut mechanic
            if self._should_cut(close, entry, ind):
                cut.append(sym.value)
                ctx.bar_state.exit_intents.append(OrderIntent(
                    ticker=sym.value, qty=-holding.quantity, price=close, stop=0.0,
                    module="exit.prover_gated_loser_exit", risk_dollars=0.0,
                ))
                log = getattr(qc, "log", None)
                if callable(log):
                    log(f"LOSER_EXIT_{self.p.variant}|{date_str}|{sym.value}|never-proved|"
                        f"close={close:.2f} entry={entry:.2f} ({(close/entry-1)*100:+.1f}%)")

        return PhaseResult(decision=cut, blocked=False, reason=f"{len(cut)} prover-gated loser-cut(s) [{self.p.variant}]",
                           facts={"loser_cuts": len(cut)}, metrics={})

    def _should_cut(self, close: float, entry: float, ind: dict) -> bool:
        v = self.p.variant
        if v == "E1":
            return close <= entry * (1.0 - self.p.stop_pct)
        w = ind.get("w_ichi")
        if w is None or not getattr(w, "is_ready", False):
            return False  # no warm weekly → can't assess E2/E3 → don't cut (cloud-bottom guards)
        try:
            if v == "E2":
                return close < float(w.kijun.current.value)
            if v == "E3":
                return close < max(float(w.senkou_a.current.value), float(w.senkou_b.current.value))
        except (AttributeError, TypeError, ValueError):
            return False
        return False

    @property
    def version_marker(self) -> str:
        return f"prover_gated_loser_exit_{self.p.variant}_v1"
