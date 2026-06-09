"""Ranking phase: QC-safe George-style BCT scanner ordering.

Kind: ranking
Marker: george_style_ranking_v1
Tested params: fixed QC-safe scorer, no swept axes.
Charter: reorder already-qualified BCT signal candidates only. No new qualification, sizing,
order submission, count caps, frozen universes, file reads, generated research-data dependency,
George/BCT transcript evidence, OCR labels, or learned George scores.

The scorer implements the deployable handoff from the George/BCT scanner reverse-engineering work:
start from `BctScoreFull`, add point-in-time chart curation features from maintained raw indicators,
and sort deterministically by candidate score, trailing dollar volume, then ticker.

Changelog:
  v1 fixed QC-safe chart-curation profile for opt-in scanner-alignment validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from engine.symbol_key import canonical_symbol_key
from phases.shared.chart_features import (
    ChartCurationInputs,
    build_chart_curation_features,
    george_qc_candidate_score,
)
from phases.shared.param_space import ComplexityDecl, ParamSpace


def _canon_map(raw: dict[Any, Any]) -> dict[str, Any]:
    return {canonical_symbol_key(k): v for k, v in (raw or {}).items()}


def _lookup(raw: dict[Any, Any], key: str, symbol: Any | None) -> Any | None:
    if symbol is not None and symbol in raw:
        return raw[symbol]
    return _canon_map(raw).get(key)


def _current_value(indicator: Any) -> float | None:
    if indicator is None or not bool(getattr(indicator, "is_ready", True)):
        return None
    try:
        return float(indicator.current.value)
    except Exception:
        return None


def _line_value(ichi: Any, name: str) -> float | None:
    line = getattr(ichi, name, None)
    if line is None:
        return None
    return _current_value(line)


def _security_price(qc: Any, intent: OrderIntent, symbol: Any | None) -> float:
    securities = getattr(qc, "securities", {})
    candidates = (symbol, intent.ticker, str(intent.ticker).upper(), canonical_symbol_key(intent.ticker))
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            sec = securities[candidate]
        except Exception:
            continue
        for attr in ("price", "close"):
            value = getattr(sec, attr, None)
            if value is None:
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0.0:
                return price
    return float(intent.price) if intent.price > 0.0 else 0.0


@dataclass(frozen=True, slots=True)
class _RankedIntent:
    score: float
    dollar_volume: float
    intent: OrderIntent


class GeorgeStyleRanking(BasePhase):
    PHASE_KIND = "ranking"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders"]

    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="Fixed QC-safe chart-curation profile; no George-derived features or learned scores.",
    )

    @dataclass(slots=True)
    class Params:
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "GeorgeStyleRanking.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        ranked = [self._ranked_intent(ctx.qc, intent) for intent in ctx.bar_state.sized_orders]
        ranked.sort(
            key=lambda row: (
                -row.score,
                -row.dollar_volume,
                canonical_symbol_key(row.intent.ticker),
            )
        )
        ctx.bar_state.sized_orders = [row.intent for row in ranked]
        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"george-style ranked {len(ranked)} candidates",
            facts={
                "ranked": len(ranked),
                "top_score": ranked[0].score if ranked else None,
                "scorer": "qc_safe_chart_curation_v1",
            },
            metrics={},
        )

    def _ranked_intent(self, qc: Any, intent: OrderIntent) -> _RankedIntent:
        key = canonical_symbol_key(intent.ticker)
        active_by_key = {canonical_symbol_key(s): s for s in getattr(qc, "_active", set())}
        symbol = active_by_key.get(key)
        dollar_volume = self._trailing_dollar_volume(qc, key)
        chart_inputs = self._chart_inputs(qc, intent, key, symbol)
        features = build_chart_curation_features(chart_inputs)
        return _RankedIntent(
            score=george_qc_candidate_score(features),
            dollar_volume=dollar_volume,
            intent=intent,
        )

    def _chart_inputs(
        self,
        qc: Any,
        intent: OrderIntent,
        key: str,
        symbol: Any | None,
    ) -> ChartCurationInputs:
        indicators = _lookup(getattr(qc, "_indicators", {}), key, symbol)
        ind = indicators if isinstance(indicators, dict) else {}
        d_ichi = ind.get("d_ichi")
        d_ichi_ready = bool(getattr(d_ichi, "is_ready", False))
        tbounce = ind.get("tbounce")

        price = _security_price(qc, intent, symbol)
        daily_close = self._tbounce_float(tbounce, "last_close") or price
        cloud_a = _line_value(d_ichi, "senkou_a") if d_ichi_ready else None
        cloud_b = _line_value(d_ichi, "senkou_b") if d_ichi_ready else None
        cloud_top = max(cloud_a, cloud_b) if cloud_a is not None and cloud_b is not None else None
        cloud_bottom = min(cloud_a, cloud_b) if cloud_a is not None and cloud_b is not None else None

        adx = ind.get("adx")
        roc13 = ind.get("roc13")

        return ChartCurationInputs(
            bct_score=self._signal_score(qc, key, symbol),
            open=self._tbounce_float(tbounce, "last_open"),
            high=self._tbounce_float(tbounce, "last_high"),
            low=self._tbounce_float(tbounce, "last_low"),
            close=daily_close,
            tenkan=_line_value(d_ichi, "tenkan") if d_ichi_ready else None,
            kijun=_line_value(d_ichi, "kijun") if d_ichi_ready else None,
            cloud_top=cloud_top,
            cloud_bottom=cloud_bottom,
            adx=_current_value(adx),
            roc13=_current_value(roc13),
            rel_volume20=self._tbounce_float(tbounce, "rel_volume20"),
            prior_high20=self._tbounce_float(tbounce, "prior_high20"),
            prior_high50=self._tbounce_float(tbounce, "prior_high50"),
            prior_high252=self._tbounce_float(tbounce, "prior_high252"),
            recent_resistance_rejection_count20=int(
                self._tbounce_float(tbounce, "recent_resistance_rejection_count20") or 0
            ),
        )

    @staticmethod
    def _tbounce_float(tbounce: Any, attr: str) -> float | None:
        value = getattr(tbounce, attr, None)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _trailing_dollar_volume(qc: Any, key: str) -> float:
        try:
            return float(_canon_map(getattr(qc, "_trailing_dv", {})).get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _signal_score(qc: Any, key: str, symbol: Any | None) -> int:
        row = _lookup(getattr(qc, "_signal_features", {}), key, symbol)
        if isinstance(row, dict):
            try:
                return int(row.get("score", 0))
            except (TypeError, ValueError):
                return 0
        return 0

    @property
    def version_marker(self) -> str:
        return "george_style_ranking_v1"
