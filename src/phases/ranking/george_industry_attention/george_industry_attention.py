"""George-style industry attention ranker with lightweight watchlist memory.

This phase consumes signal candidates and the daily industry context. It reorders candidates before
entry confirmation, and it keeps a small per-ticker watchlist state so good finds can persist.
The selection-gate subscription hook is still a separate concern: this phase can only rank symbols
that are already present and warmed in the current candidate set.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace


def _lookup(mapping: dict[Any, Any], ticker: str, default: Any = None) -> Any:
    return mapping.get(ticker, mapping.get(ticker.lower(), default))


class GeorgeIndustryAttention(BasePhase):
    PHASE_KIND = "ranking"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders", "watchlist_state"]

    COMPLEXITY = ComplexityDecl(
        free_params=5,
        note="industry_weight + watchlist_weight + ticker_attention_weight + watchlist_ttl + min_industry_score.",
    )

    @dataclass(slots=True)
    class Params:
        industry_weight: float = 1.0
        watchlist_weight: float = 0.5
        ticker_attention_weight: float = 0.5
        watchlist_add_min_industry_score: float = 2.0
        watchlist_remove_min_industry_score: float = 0.5
        watchlist_ttl_days: int = 10
        min_industry_score: float = -999.0
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(
                axes={
                    "industry_weight": (0.0, 1.0, 2.0),
                    "watchlist_weight": (0.0, 0.5, 1.0),
                    "ticker_attention_weight": (0.0, 0.5, 1.0),
                    "watchlist_ttl_days": (5, 10, 20),
                    "min_industry_score": (-999.0, 0.5, 1.0),
                }
            )

    def __init__(self, params: "GeorgeIndustryAttention.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        intents = list(ctx.bar_state.sized_orders)
        if not intents:
            self._age_watchlist(qc)
            self._remove_invalid_watchlist(qc)
            return PhaseResult(
                decision=[],
                blocked=False,
                reason="0 candidates ranked",
                facts={"ranked": 0, "dropped": 0, "watchlist_size": len(getattr(qc, "_george_watchlist", {}))},
                metrics={},
            )

        industry_by_ticker = getattr(qc, "_industry_by_ticker", {})
        industry_context = getattr(qc, "_industry_context", {})
        ticker_attention = getattr(qc, "_george_attention_ticker", {})
        watchlist = self._watchlist(qc)

        self._age_watchlist(qc)

        scored: list[tuple[float, int, OrderIntent, dict[str, Any]]] = []
        dropped = 0
        n = len(intents)
        for index, intent in enumerate(intents):
            ticker = intent.ticker
            industry = str(_lookup(industry_by_ticker, ticker, "unknown"))
            industry_score = float(industry_context.get(industry, {}).get("score", 0.0))
            if industry_score < self.p.min_industry_score:
                dropped += 1
                continue

            attention_score = float(_lookup(ticker_attention, ticker, 0.0))
            watch_state = watchlist.get(ticker) or watchlist.get(ticker.lower())
            watch_score = float(watch_state.get("score", 1.0)) if isinstance(watch_state, dict) else 0.0
            base_rank = (n - index) / n
            final_score = (
                base_rank
                + self.p.industry_weight * industry_score
                + self.p.watchlist_weight * watch_score
                + self.p.ticker_attention_weight * attention_score
            )
            feature = {
                "ticker": ticker,
                "industry": industry,
                "base_rank": base_rank,
                "industry_score": industry_score,
                "watch_score": watch_score,
                "attention_score": attention_score,
                "final_score": final_score,
            }
            scored.append((final_score, -index, intent, feature))
            self._maybe_add_or_refresh_watchlist(qc, ticker, industry, industry_score, attention_score)

        self._remove_invalid_watchlist(qc)
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        reranked = [intent for _score, _idx, intent, _feature in scored]
        features = [feature for _score, _idx, _intent, feature in scored]
        ctx.bar_state.sized_orders = reranked
        qc._george_rank_features = {feature["ticker"]: feature for feature in features}

        return PhaseResult(
            decision=reranked,
            blocked=False,
            reason=f"{len(reranked)} candidates ranked, {dropped} dropped by industry floor",
            facts={
                "ranked": len(reranked),
                "dropped": dropped,
                "watchlist_size": len(getattr(qc, "_george_watchlist", {})),
                "top": [intent.ticker for intent in reranked[:5]],
            },
            metrics={"rank_features": features},
        )

    def _watchlist(self, qc: Any) -> dict[str, Any]:
        existing = getattr(qc, "_george_watchlist", None)
        if not isinstance(existing, dict):
            existing = {}
            qc._george_watchlist = existing
        return existing

    def _age_watchlist(self, qc: Any) -> None:
        watchlist = self._watchlist(qc)
        for item in watchlist.values():
            if isinstance(item, dict):
                item["age_days"] = int(item.get("age_days", 0)) + 1

    def _maybe_add_or_refresh_watchlist(
        self,
        qc: Any,
        ticker: str,
        industry: str,
        industry_score: float,
        attention_score: float,
    ) -> None:
        watchlist = self._watchlist(qc)
        if industry_score < self.p.watchlist_add_min_industry_score and attention_score <= 0.0:
            return
        current = watchlist.get(ticker, {})
        score = max(float(current.get("score", 0.0)) if isinstance(current, dict) else 0.0, 1.0 + attention_score)
        watchlist[ticker] = {
            "industry": industry,
            "score": score,
            "age_days": 0,
            "last_industry_score": industry_score,
            "last_attention_score": attention_score,
        }

    def _remove_invalid_watchlist(self, qc: Any) -> None:
        watchlist = self._watchlist(qc)
        stale: list[str] = []
        for ticker, item in watchlist.items():
            if not isinstance(item, dict):
                stale.append(ticker)
                continue
            age = int(item.get("age_days", 0))
            industry_score = float(item.get("last_industry_score", 0.0))
            attention_score = float(item.get("last_attention_score", 0.0))
            invalidated = industry_score < self.p.watchlist_remove_min_industry_score and attention_score <= 0.0
            if age > self.p.watchlist_ttl_days or invalidated:
                stale.append(ticker)
        for ticker in stale:
            watchlist.pop(ticker, None)

    @property
    def version_marker(self) -> str:
        return "george_industry_attention_v1"
