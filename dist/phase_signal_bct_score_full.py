"""Signal phase: BCT 8-condition score + pre-filter + parabolic block + dollar-vol tiebreak.

Kind: signal
Marker: bct_score_full_v1
Tested params: min_score=7, parabolic_threshold=0.25 (champion-asis-v1)
Charter: single code path, no count caps, no time exits. Faithful carve of oracle
_rebalance L527-590 (baseline-oracle-v0). Reads ranked_candidates from universe phase,
writes sized_orders (qty=0 stubs for the sizing phase).
DO NOT modify evaluate() logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from context import OrderIntent, PhaseContext
from shared_oracle_helpers import score_symbol_native


class BctScoreFull(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    @dataclass(slots=True)
    class Params:
        min_score: int = 7
        parabolic_threshold: float = 0.25
        enabled: bool = True

    def __init__(self, params: "BctScoreFull.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        min_score = self.p.min_score
        parabolic_threshold = self.p.parabolic_threshold

        # Resolve candidates from universe phase (list of ticker strings)
        candidates_raw = ctx.bar_state.ranked_candidates  # list of str symbol values

        # Build symbol lookup from qc._active
        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}

        # #238: dollar-volume tiebreak from the LIVE per-ticker trailing-mean DV
        # (qc._trailing_dv, computed once-daily by lean_entry._coarse_selection), NOT the
        # retired qc._eligible artifact and NOT a per-bar qc.history(20) — keeps on_data
        # history-free. Keys are lowercase (zip stems / coarse value lowered); candidate
        # tickers are canonical (upper).
        trailing_dv = getattr(qc, "_trailing_dv", {})

        candidates: list[tuple[Any, int, float]] = []  # (symbol, score, dollar_volume)
        blocked_log: list[str] = []

        for ticker in candidates_raw:
            symbol = active_by_value.get(ticker)
            if symbol is None:
                continue
            if qc.portfolio[symbol].invested:
                continue
            if qc.transactions.get_open_orders(symbol):
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue

            # PRE-FILTER: skip symbols that cannot reach MIN_SCORE=7
            # Mirrors oracle L538-551 exactly
            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready:
                price = float(qc.securities[symbol].price)
                if price <= 0:
                    continue
                if price < sma200_ind.current.value:
                    continue  # condition 8 fails → max score 6 → skip
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue  # condition 5 fails → max score 6 → skip

            # BCT score
            result = score_symbol_native(qc, symbol, ind)
            if result is None or result["score"] < min_score:
                continue

            # E51: Parabolic entry block — skip if the maintained 13-day ROC exceeds the
            # threshold. #213f: roc13 (maintained) replaces the per-bar qc.history(14).
            # roc(13) = (price - price[13-back])/price[13-back] == legacy parabolic, by
            # construction (a decimal fraction, comparable to parabolic_threshold).
            roc13 = ind.get("roc13")
            if roc13 is not None and roc13.is_ready and roc13.current.value > parabolic_threshold:
                blocked_log.append(ticker)
                continue

            # Dollar-volume tiebreak from the live trailing DV (no per-bar history). 0.0 if absent.
            dollar_volume = float(trailing_dv.get(ticker.lower(), 0.0))

            candidates.append((symbol, result["score"], dollar_volume))

        # Sort: score DESC, dollar_vol DESC — matches oracle L589-590
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

        # Write as OrderIntent stubs (qty=0, sizing phase sets qty)
        ctx.bar_state.sized_orders = [
            OrderIntent(
                ticker=sym.value,
                qty=0,
                price=float(qc.securities[sym].price),
                stop=0.0,
                module="signal.bct_score_full",
                risk_dollars=0.0,
            )
            for sym, score, _dv in candidates
        ]

        return PhaseResult(
            decision=candidates,
            blocked=False,
            reason=f"{len(candidates)} candidates scored ≥{min_score}, {len(blocked_log)} parabolic blocks",
            facts={"candidate_count": len(candidates), "parabolic_blocked": len(blocked_log)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "bct_score_full_v1"
