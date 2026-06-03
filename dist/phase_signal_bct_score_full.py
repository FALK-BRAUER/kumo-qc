from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from symbol_key import canonical_symbol_key
from context import OrderIntent, PhaseContext
from shared_oracle_helpers import score_symbol_cached, score_symbol_native
from shared_param_space import ComplexityDecl, ParamSpace


class BctScoreFull(BasePhase):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = ["universe"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=2,
        note="min_score (qualify threshold) + parabolic_threshold (overextension block).",
    )

    @dataclass(slots=True)
    class Params:
        min_score: int = 7
        parabolic_threshold: float = 0.25
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(
                axes={
                    "min_score": (6, 7, 8),
                    "parabolic_threshold": (0.20, 0.25, 0.30, 0.35),
                }
            )

    def __init__(self, params: "BctScoreFull.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        min_score = self.p.min_score
        parabolic_threshold = self.p.parabolic_threshold

        candidates_raw = ctx.bar_state.ranked_candidates

        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}

        trailing_dv = getattr(qc, "_trailing_dv", {})

        candidates: list[tuple[Any, int, float]] = []
        blocked_log: list[str] = []

        cache = getattr(qc, "_warmup_cache", None)
        cur_date = ctx.time.date() if cache is not None else None

        for ticker in candidates_raw:
            symbol = active_by_key.get(canonical_symbol_key(ticker))
            if symbol is None:
                continue
            if qc.portfolio[symbol].invested:
                continue
            if qc.transactions.get_open_orders(symbol):
                continue

            if cache is not None:
                scalars = cache.get(symbol.value, {}).get(cur_date)
                if scalars is None:
                    continue
                price = scalars["d_price"]
                if price <= 0 or price < scalars["ma200"] or price < scalars["d_cloud_top"]:
                    continue
                result = score_symbol_cached(scalars)
                if result["score"] < min_score:
                    continue
                if scalars["roc13"] > parabolic_threshold:
                    blocked_log.append(ticker)
                    continue
                candidates.append((symbol, result["score"], float(trailing_dv.get(ticker.lower(), 0.0))))
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue

            sma200_ind = ind.get("sma200")
            d_ichi_ind = ind.get("d_ichi")
            if sma200_ind and sma200_ind.is_ready and d_ichi_ind and d_ichi_ind.is_ready:
                price = float(qc.securities[symbol].price)
                if price <= 0:
                    continue
                if price < sma200_ind.current.value:
                    continue
                cloud_top = max(d_ichi_ind.senkou_a.current.value, d_ichi_ind.senkou_b.current.value)
                if price < cloud_top:
                    continue

            result = score_symbol_native(qc, symbol, ind)
            if result is None or result["score"] < min_score:
                continue

            roc13 = ind.get("roc13")
            if roc13 is not None and roc13.is_ready and roc13.current.value > parabolic_threshold:
                blocked_log.append(ticker)
                continue

            dollar_volume = float(trailing_dv.get(ticker.lower(), 0.0))

            candidates.append((symbol, result["score"], dollar_volume))

        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

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
