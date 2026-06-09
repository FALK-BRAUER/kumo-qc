"""Ranking phase: opt-in BCT/George-style LambdaMART scanner gate.

Kind: ranking
Marker: lambdamart_scanner_ranker_v1
Charter: rank and optionally Top-X trim already-qualified signal candidates using a deployable
JSON tree-ensemble artifact. Runtime features are QC-safe only; George labels/OCR/watchlists are
training/evaluation provenance and are not read here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.shared.param_space import ComplexityDecl, ParamSpace
from runtime.scanner_ranker import (
    ScannerModelArtifact,
    ScannerRankerError,
    build_scanner_candidate_rows,
    feature_contract_hash,
    load_scanner_model_artifact,
    rank_scanner_panel,
    scanner_cache_key,
)

_FALLBACK_VALUES = frozenset({"raise", "off", "bct_order"})


class LambdamartScannerRanker(BasePhase):
    PHASE_KIND = "ranking"
    REQUIRES_UPSTREAM = ["signal"]
    PROVIDES_DOWNSTREAM = ["sized_orders", "scanner_ranker_features"]

    COMPLEXITY = ComplexityDecl(
        free_params=0,
        note="Runtime-configured scanner gate; custom sweep grids count Top-X as their own axis.",
    )

    @dataclass(slots=True)
    class Params:
        scanner_ranker_enabled: bool | None = None
        scanner_ranker_model_path: str | None = None
        scanner_ranker_top_x: int | None = None
        scanner_ranker_min_score: float | None = None
        scanner_ranker_fallback: str | None = None
        enabled: bool = True

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={})

    def __init__(self, params: "LambdamartScannerRanker.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params
        self._model: ScannerModelArtifact | None = None
        self._model_source: str | None = None

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        intents = list(ctx.bar_state.sized_orders)
        enabled = self._enabled(ctx.qc)
        if not enabled:
            return PhaseResult(
                decision=[],
                blocked=False,
                reason="scanner ranker disabled",
                facts={"enabled": False, "ranked": len(intents), "selected": len(intents)},
                metrics={},
            )
        if not intents:
            return PhaseResult(
                decision=[],
                blocked=False,
                reason="scanner ranker saw 0 candidates",
                facts={"enabled": True, "ranked": 0, "selected": 0},
                metrics={},
            )

        fallback = self._fallback(ctx.qc)
        try:
            model = self._load_model(ctx.qc)
            rows = build_scanner_candidate_rows(ctx.qc, intents)
            top_x = self._top_x(ctx.qc)
            min_score = self._min_score(ctx.qc)
            ranked = rank_scanner_panel(rows, model, top_x=top_x, min_score=min_score)
        except ScannerRankerError as exc:
            if fallback == "raise":
                raise
            ctx.qc._scanner_ranker_error = str(exc)
            return PhaseResult(
                decision=intents,
                blocked=False,
                reason=f"scanner ranker fallback={fallback}: {exc}",
                facts={
                    "enabled": True,
                    "fallback": fallback,
                    "ranked": len(intents),
                    "selected": len(intents),
                    "error": str(exc),
                },
                metrics={},
            )

        by_ticker: dict[str, OrderIntent] = {row.ticker: intent for row, intent in zip(rows, intents, strict=False)}
        selected = [by_ticker[row.ticker] for row in ranked if row.ticker in by_ticker]
        ctx.bar_state.sized_orders = selected
        diagnostics = [
            {
                "ticker": row.ticker,
                "score": row.score,
                "rank": index,
                "original_index": row.original_index,
            }
            for index, row in enumerate(ranked, start=1)
        ]
        ctx.qc._scanner_ranker_features = {row.ticker: row.features for row in ranked}
        ctx.qc._scanner_ranker_scores = diagnostics
        cache_key = scanner_cache_key(
            artifact_hash=model.artifact_hash,
            panel_date=ctx.time.strftime("%Y-%m-%d"),
            tickers=tuple(row.ticker for row in rows),
            top_x=self._top_x(ctx.qc),
            min_score=self._min_score(ctx.qc),
            taxonomy_hash=self._taxonomy_hash(ctx.qc),
            feature_hash=feature_contract_hash(model.feature_names),
        )
        ctx.qc._scanner_ranker_cache_key = cache_key

        return PhaseResult(
            decision=selected,
            blocked=False,
            reason=f"scanner ranker selected {len(selected)}/{len(intents)} candidates",
            facts={
                "enabled": True,
                "ranked": len(intents),
                "selected": len(selected),
                "top_x": self._top_x(ctx.qc),
                "min_score": self._min_score(ctx.qc),
                "model_source": self._model_source,
                "artifact_hash": model.artifact_hash[:12],
                "feature_hash": feature_contract_hash(model.feature_names)[:12],
                "cache_key": cache_key[:16],
                "top": [intent.ticker for intent in selected[:5]],
            },
            metrics={"scanner_ranker_scores": diagnostics},
        )

    def _enabled(self, qc: Any) -> bool:
        if self.p.scanner_ranker_enabled is not None:
            return bool(self.p.scanner_ranker_enabled)
        return bool(getattr(qc, "SCANNER_RANKER_ENABLED", False))

    def _model_path(self, qc: Any) -> str | None:
        if self.p.scanner_ranker_model_path is not None:
            return self.p.scanner_ranker_model_path
        value = getattr(qc, "SCANNER_RANKER_MODEL_PATH", None)
        return str(value) if value else None

    def _top_x(self, qc: Any) -> int:
        value = self.p.scanner_ranker_top_x
        if value is None:
            value = getattr(qc, "SCANNER_RANKER_TOP_X", 0)
        top_x = int(value or 0)
        if top_x < 0:
            raise ScannerRankerError(f"scanner_ranker_top_x must be >= 0, got {top_x}")
        return top_x

    def _min_score(self, qc: Any) -> float | None:
        value = self.p.scanner_ranker_min_score
        if value is None:
            value = getattr(qc, "SCANNER_RANKER_MIN_SCORE", None)
        return None if value is None else float(value)

    def _fallback(self, qc: Any) -> str:
        value = self.p.scanner_ranker_fallback
        if value is None:
            value = getattr(qc, "SCANNER_RANKER_FALLBACK", "raise")
        fallback = str(value or "raise")
        if fallback not in _FALLBACK_VALUES:
            raise ScannerRankerError(
                f"scanner_ranker_fallback must be one of {sorted(_FALLBACK_VALUES)}, got {fallback!r}"
            )
        return fallback

    def _load_model(self, qc: Any) -> ScannerModelArtifact:
        source = self._model_path(qc)
        if not source:
            raise ScannerRankerError("scanner ranker enabled but no model path/objectstore key is configured")
        if self._model is not None and self._model_source == source:
            return self._model
        self._model = load_scanner_model_artifact(source, getattr(qc, "object_store", None))
        self._model_source = source
        return self._model

    @staticmethod
    def _taxonomy_hash(qc: Any) -> str:
        pieces: list[str] = []
        for attr in ("_sector_by_ticker", "_industry_by_ticker", "_proxy_by_ticker", "_proxy_etfs_by_ticker"):
            mapping = getattr(qc, attr, {})
            if isinstance(mapping, dict):
                pieces.append(f"{attr}:{len(mapping)}")
        return "|".join(pieces)

    @property
    def version_marker(self) -> str:
        return "lambdamart_scanner_ranker_v1"
