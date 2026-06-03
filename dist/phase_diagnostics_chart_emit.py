from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from symbol_key import canonical_symbol_key
from context import PhaseContext
from shared_oracle_helpers import score_symbol_native

_SCORE_PROBES = ("DRI", "CME", "AMZN", "COST", "CRWD", "KGC")


class ChartEmit(BasePhase):
    PHASE_KIND = "diagnostics"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = True
        chart_name: str = "Universe"

    def __init__(self, params: "ChartEmit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc

        active_set = len(getattr(qc, "_ranked_today", None) or [])
        ranked = len(ctx.bar_state.ranked_candidates)

        plot = getattr(qc, "plot", None)
        if callable(plot):
            plot(self.p.chart_name, "active_set", active_set)
            plot(self.p.chart_name, "ranked", ranked)

        n_qualifying = -1
        regime_charted = False
        probe_scores: dict[str, float] = {}
        if callable(plot):
            spy = getattr(qc, "spy", None)
            spy_sma200 = getattr(qc, "spy_sma200", None)
            if spy is not None and spy_sma200 is not None and getattr(spy_sma200, "is_ready", False):
                try:
                    spy_close = float(qc.securities[spy].price)
                    spy_ma200 = float(spy_sma200.current.value)
                except (KeyError, AttributeError, TypeError, ValueError):
                    pass
                else:
                    plot("Regime", "spy_close", spy_close)
                    plot("Regime", "spy_ma200", spy_ma200)
                    regime_charted = True

            n_qualifying = len(ctx.bar_state.sized_orders)
            plot("Signal", "n_qualifying", n_qualifying)

            active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
            indicators = getattr(qc, "_indicators", {})
            for ticker in _SCORE_PROBES:
                score = -1.0
                symbol = active_by_key.get(canonical_symbol_key(ticker))
                if symbol is not None:
                    ind = indicators.get(symbol)
                    if ind is not None:
                        try:
                            result = score_symbol_native(qc, symbol, ind)
                        except (KeyError, AttributeError, TypeError, ValueError):
                            result = None
                        if result is not None:
                            score = float(result["score"])
                plot("Score", ticker, score)
                probe_scores[ticker] = score

        return PhaseResult(
            decision="charted",
            blocked=False,
            reason="universe counts + regime + signal breadth + probe scores emitted as chart series",
            facts={
                "active_set": active_set,
                "ranked": ranked,
                "n_qualifying": n_qualifying,
                "regime_charted": regime_charted,
                "probe_scores": probe_scores,
            },
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "chart_emit_v1"
