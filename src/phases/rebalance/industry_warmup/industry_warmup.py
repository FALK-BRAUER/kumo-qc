"""Daily industry warm-up phase.

This is the George-style top-down context slice: score industries before ticker ranking. It uses
already-maintained/raw indicator state when available and accepts explicit feature maps so the
same phase can run before the full profile/proxy cache exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from engine.base import BasePhase, PhaseResult
from phases.shared.oracle_helpers import score_symbol_native
from phases.shared.param_space import ComplexityDecl, ParamSpace


def _ticker_map_lookup(mapping: dict[Any, Any], ticker: str, default: Any = None) -> Any:
    return mapping.get(ticker, mapping.get(ticker.lower(), default))


def _is_ready(indicator: Any) -> bool:
    return bool(getattr(indicator, "is_ready", False))


def _current_value(indicator: Any, default: float = 0.0) -> float:
    current = getattr(indicator, "current", None)
    return float(getattr(current, "value", default))


def _symbol_value(symbol: Any) -> str:
    return str(getattr(symbol, "value", symbol))


class IndustryWarmup(BasePhase):
    PHASE_KIND = "rebalance"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["industry_context"]

    COMPLEXITY = ComplexityDecl(
        free_params=4,
        note="top_n + bct_share_weight + attention_weight + etf_proxy_weight.",
    )

    @dataclass(slots=True)
    class Params:
        top_n: int = 5
        bct_score_threshold: int = 7
        bct_share_weight: float = 2.0
        cloud_weight: float = 1.0
        tk_weight: float = 1.0
        dmi_weight: float = 0.5
        roc13_weight: float = 2.0
        attention_weight: float = 1.0
        etf_proxy_weight: float = 1.0
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(
                axes={
                    "top_n": (3, 5, 8),
                    "bct_share_weight": (1.0, 2.0, 3.0),
                    "attention_weight": (0.0, 1.0, 2.0),
                    "etf_proxy_weight": (0.0, 1.0, 2.0),
                }
            )

    def __init__(self, params: "IndustryWarmup.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: Any) -> PhaseResult:
        qc = ctx.qc
        active_by_value = {_symbol_value(s): s for s in getattr(qc, "_active", set())}
        ranked_today = list(getattr(qc, "_ranked_today", []))
        tickers = ranked_today or sorted(active_by_value)
        indicators = getattr(qc, "_indicators", {})
        industry_by_ticker = getattr(qc, "_industry_by_ticker", {})
        explicit_features = getattr(qc, "_ticker_context_features", {})

        buckets: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            symbol = active_by_value.get(str(ticker))
            industry = str(_ticker_map_lookup(industry_by_ticker, str(ticker), "unknown"))
            features = self._ticker_features(qc, symbol, str(ticker), indicators.get(symbol), explicit_features)
            bucket = buckets.setdefault(
                industry,
                {
                    "symbols": [],
                    "bct_pass": 0,
                    "above_cloud": 0,
                    "tk_bull": 0,
                    "dmi_bull": 0,
                    "roc13": [],
                },
            )
            bucket["symbols"].append(str(ticker))
            bucket["bct_pass"] += int(features["bct_score"] >= self.p.bct_score_threshold)
            bucket["above_cloud"] += int(features["above_cloud"])
            bucket["tk_bull"] += int(features["tk_bull"])
            bucket["dmi_bull"] += int(features["dmi_bull"])
            bucket["roc13"].append(float(features["roc13"]))

        attention = getattr(qc, "_george_attention_industry", getattr(qc, "_industry_attention", {}))
        proxy_scores = getattr(qc, "_industry_proxy_scores", {})
        context: dict[str, dict[str, Any]] = {}
        for industry, bucket in buckets.items():
            n = max(len(bucket["symbols"]), 1)
            bct_share = bucket["bct_pass"] / n
            cloud_share = bucket["above_cloud"] / n
            tk_share = bucket["tk_bull"] / n
            dmi_share = bucket["dmi_bull"] / n
            median_roc13 = float(median(bucket["roc13"])) if bucket["roc13"] else 0.0
            attention_score = float(attention.get(industry, 0.0))
            proxy_score = float(proxy_scores.get(industry, 0.0))
            score = (
                self.p.bct_share_weight * bct_share
                + self.p.cloud_weight * cloud_share
                + self.p.tk_weight * tk_share
                + self.p.dmi_weight * dmi_share
                + self.p.roc13_weight * median_roc13
                + self.p.attention_weight * attention_score
                + self.p.etf_proxy_weight * proxy_score
            )
            context[industry] = {
                "score": score,
                "n_symbols": n,
                "symbols": list(bucket["symbols"]),
                "bct_share": bct_share,
                "pct_above_cloud": cloud_share,
                "pct_tk_bull": tk_share,
                "pct_dmi_bull": dmi_share,
                "median_roc13": median_roc13,
                "attention_score": attention_score,
                "proxy_score": proxy_score,
            }

        top = sorted(context, key=lambda industry: context[industry]["score"], reverse=True)[: self.p.top_n]
        qc._industry_context = context
        qc._top_industries = top

        return PhaseResult(
            decision=top,
            blocked=False,
            reason=f"{len(context)} industries scored; top={top[:3]}",
            facts={"top_industries": top, "industry_count": len(context)},
            metrics={"industry_scores": {k: v["score"] for k, v in context.items()}},
        )

    def _ticker_features(
        self,
        qc: Any,
        symbol: Any | None,
        ticker: str,
        indicators: dict[str, Any] | None,
        explicit_features: dict[Any, Any],
    ) -> dict[str, Any]:
        features = dict(_ticker_map_lookup(explicit_features, ticker, {}) or {})
        if "bct_score" not in features:
            features["bct_score"] = self._bct_score(qc, symbol, ticker, indicators)
        if "roc13" not in features:
            roc13 = indicators.get("roc13") if indicators else None
            features["roc13"] = _current_value(roc13) if roc13 is not None and _is_ready(roc13) else 0.0

        d_ichi = indicators.get("d_ichi") if indicators else None
        price = self._price(qc, symbol)
        if "above_cloud" not in features:
            features["above_cloud"] = False
            if d_ichi is not None and _is_ready(d_ichi) and price > 0.0:
                cloud_top = max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
                features["above_cloud"] = bool(price > cloud_top)
        if "tk_bull" not in features:
            features["tk_bull"] = bool(
                d_ichi is not None and _is_ready(d_ichi)
                and d_ichi.tenkan.current.value > d_ichi.kijun.current.value
            )
        if "dmi_bull" not in features:
            dmi_map = getattr(qc, "_dmi_bull_by_ticker", {})
            features["dmi_bull"] = bool(_ticker_map_lookup(dmi_map, ticker, False))
        return features

    def _bct_score(self, qc: Any, symbol: Any | None, ticker: str, indicators: dict[str, Any] | None) -> int:
        score_map = getattr(qc, "_bct_score_by_ticker", {})
        mapped = _ticker_map_lookup(score_map, ticker)
        if mapped is not None:
            return int(mapped)
        if symbol is None or indicators is None:
            return 0
        result = score_symbol_native(qc, symbol, indicators)
        if result is None:
            return 0
        return int(result.get("score", 0))

    def _price(self, qc: Any, symbol: Any | None) -> float:
        if symbol is None:
            return 0.0
        security = getattr(qc, "securities", {}).get(symbol)
        if security is None:
            return 0.0
        return float(getattr(security, "price", getattr(security, "close", 0.0)))

    @property
    def version_marker(self) -> str:
        return "industry_warmup_v1"
