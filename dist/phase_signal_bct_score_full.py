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
        date_str = ctx.time.strftime("%Y-%m-%d")
        min_score = self.p.min_score
        parabolic_threshold = self.p.parabolic_threshold

        # Resolve candidates from universe phase (list of ticker strings)
        candidates_raw = ctx.bar_state.ranked_candidates  # list of str symbol values

        # Build symbol lookup from qc._active
        active_by_value = {s.value: s for s in getattr(qc, "_active", set())}

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

            # E51: Parabolic entry block — skip if 13-day return exceeds threshold
            try:
                from QuantConnect import Resolution  # noqa
                hist = qc.history(symbol, 14, Resolution.DAILY)
                if hist is not None and len(hist) >= 14:
                    import pandas as pd
                    if isinstance(hist.index, pd.MultiIndex):
                        hist = hist.droplevel(0)
                    close_col = "close" if "close" in hist.columns else "Close"
                    price_13d_ago = float(hist.iloc[0][close_col])
                    current_price = float(hist.iloc[-1][close_col])
                    if price_13d_ago > 0:
                        return_13d = current_price / price_13d_ago - 1
                        if return_13d > parabolic_threshold:
                            blocked_log.append(ticker)
                            continue
            except Exception:
                pass

            # Dollar-volume tiebreak (oracle L572-587)
            dollar_volume = 0.0
            try:
                from QuantConnect import Resolution  # noqa
                import pandas as pd
                dv_hist = qc.history(symbol, 20, Resolution.DAILY)
                if dv_hist is not None and len(dv_hist) >= 1:
                    if isinstance(dv_hist.index, pd.MultiIndex):
                        dv_hist = dv_hist.droplevel(0)
                    _cc = "close" if "close" in dv_hist.columns else "Close"
                    _vc = "volume" if "volume" in dv_hist.columns else "Volume"
                    if _vc in dv_hist.columns:
                        dollar_volume = float((dv_hist[_cc] * dv_hist[_vc]).mean())
            except Exception:
                dollar_volume = 0.0

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
