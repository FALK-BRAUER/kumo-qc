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
from engine.symbol_key import canonical_symbol_key
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
from runtime.scanner_rank_history import (
    RankHistoryInput,
    RankHistoryParams,
    update_rank_history,
)

_FALLBACK_VALUES = frozenset({"raise", "off", "bct_order"})
_OVERLAP_RANKS = (10, 20, 50)
_OVERLAP_WINDOWS = (1, 5, 20)


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
        scanner_rank_history_enabled: bool | None = None
        scanner_rank_history_short_window: int = 5
        scanner_rank_history_long_window: int = 20
        scanner_rank_history_focus_rank: int = 10
        scanner_rank_history_core_rank: int = 20
        scanner_rank_history_min_seen_short: int = 2
        scanner_rank_history_min_seen_long: int = 3
        scanner_rank_history_min_persistence_score: float = 0.85
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
            ctx.qc._scanner_ranker_context = {}
            ctx.qc._scanner_ranker_features = {}
            ctx.qc._scanner_ranker_scores = []
            return PhaseResult(
                decision=[],
                blocked=False,
                reason="scanner ranker disabled",
                facts={"enabled": False, "ranked": len(intents), "selected": len(intents)},
                metrics={},
            )
        if not intents:
            ctx.qc._scanner_ranker_context = {}
            ctx.qc._scanner_ranker_features = {}
            ctx.qc._scanner_ranker_scores = []
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
            history_enabled = self._rank_history_enabled(ctx.qc)
            if history_enabled:
                all_ranked = rank_scanner_panel(rows, model, top_x=0, min_score=None)
                ranked = self._rank_history_selection(ctx, all_ranked, top_x=top_x, min_score=min_score)
            else:
                all_ranked = rank_scanner_panel(rows, model, top_x=0, min_score=None)
                ranked = rank_scanner_panel(rows, model, top_x=top_x, min_score=min_score)
        except ScannerRankerError as exc:
            if fallback == "raise":
                raise
            ctx.qc._scanner_ranker_error = str(exc)
            ctx.qc._scanner_ranker_context = {}
            ctx.qc._scanner_ranker_features = {}
            ctx.qc._scanner_ranker_scores = []
            ctx.qc._scanner_rank_history_context = {}
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
        full_rank_by_ticker = {row.ticker: index for index, row in enumerate(all_ranked, start=1)}
        history_context = getattr(ctx.qc, "_scanner_rank_history_context", {})
        rank_history_eligible = self._rank_history_eligible_count(all_ranked, history_context, history_enabled)
        self._record_scanner_funnel(
            ctx.qc,
            raw_candidates=len(intents),
            ranked_candidates=len(all_ranked),
            rank_history_eligible=rank_history_eligible,
            selected=len(selected),
            all_ranked=all_ranked,
        )
        diagnostics = [
            {
                "ticker": row.ticker,
                "score": row.score,
                "rank": full_rank_by_ticker.get(row.ticker, index),
                "original_index": row.original_index,
                "rank_history_state": self._rank_history_state(row.ticker, history_context),
            }
            for index, row in enumerate(ranked, start=1)
        ]
        context = {
            canonical_symbol_key(row.ticker): {
                "scanner_rank": full_rank_by_ticker.get(row.ticker, index),
                "scanner_score": float(row.score),
                "scanner_original_index": int(row.original_index),
                "scanner_features": dict(row.features),
                "scanner_rank_history": dict(history_context.get(canonical_symbol_key(row.ticker), {})),
            }
            for index, row in enumerate(ranked, start=1)
        }
        ctx.qc._scanner_ranker_features = {row.ticker: row.features for row in ranked}
        ctx.qc._scanner_ranker_scores = diagnostics
        ctx.qc._scanner_ranker_all_scores = [
            {
                "ticker": row.ticker,
                "score": row.score,
                "rank": index,
                "original_index": row.original_index,
                "rank_history_state": self._rank_history_state(row.ticker, history_context),
            }
            for index, row in enumerate(all_ranked, start=1)
        ]
        ctx.qc._scanner_ranker_context = context
        cache_key = scanner_cache_key(
            artifact_hash=model.artifact_hash,
            panel_date=ctx.time.strftime("%Y-%m-%d"),
            tickers=tuple(row.ticker for row in rows),
            top_x=self._top_x(ctx.qc),
            min_score=self._min_score(ctx.qc),
            taxonomy_hash=self._taxonomy_hash(ctx.qc),
            feature_hash=model.feature_hash or feature_contract_hash(model.feature_names),
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
                "scanner_ranked": len(all_ranked),
                "rank_history_eligible": rank_history_eligible,
                "rank_history_enabled": self._rank_history_enabled(ctx.qc),
                "top_x": self._top_x(ctx.qc),
                "min_score": self._min_score(ctx.qc),
                "model_source": self._model_source,
                "model_type": model.model_type,
                "artifact_hash": model.artifact_hash[:12],
                "feature_hash": (model.feature_hash or feature_contract_hash(model.feature_names))[:12],
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

    def _rank_history_enabled(self, qc: Any) -> bool:
        if self.p.scanner_rank_history_enabled is not None:
            return bool(self.p.scanner_rank_history_enabled)
        return bool(getattr(qc, "SCANNER_RANK_HISTORY_ENABLED", False))

    def _rank_history_params(self) -> RankHistoryParams:
        return RankHistoryParams(
            short_window=int(self.p.scanner_rank_history_short_window),
            long_window=int(self.p.scanner_rank_history_long_window),
            focus_rank=int(self.p.scanner_rank_history_focus_rank),
            core_rank=int(self.p.scanner_rank_history_core_rank),
            min_seen_short=int(self.p.scanner_rank_history_min_seen_short),
            min_seen_long=int(self.p.scanner_rank_history_min_seen_long),
            min_persistence_score=float(self.p.scanner_rank_history_min_persistence_score),
        )

    def _rank_history_selection(
        self,
        ctx: PhaseContext,
        all_ranked: list[Any],
        *,
        top_x: int,
        min_score: float | None,
    ) -> list[Any]:
        params = self._rank_history_params()
        inputs = [
            RankHistoryInput(ticker=row.ticker, rank=index, score=float(row.score))
            for index, row in enumerate(all_ranked, start=1)
        ]
        state, history_context = update_rank_history(
            getattr(ctx.qc, "_scanner_rank_history_state", None),
            inputs,
            ctx.time.date(),
            params=params,
        )
        ctx.qc._scanner_rank_history_state = state
        ctx.qc._scanner_rank_history_context = history_context
        selected = [
            row
            for row in all_ranked
            if (min_score is None or row.score >= min_score)
            and bool(history_context.get(canonical_symbol_key(row.ticker), {}).get("rank_requalified"))
        ]
        return selected[:top_x] if top_x else selected

    @staticmethod
    def _rank_history_state(ticker: str, history_context: Any) -> str:
        if not isinstance(history_context, dict):
            return ""
        item = history_context.get(canonical_symbol_key(ticker), {})
        if not isinstance(item, dict):
            return ""
        return str(item.get("rank_requalification_state") or "")

    @staticmethod
    def _rank_history_eligible_count(
        all_ranked: list[Any],
        history_context: Any,
        history_enabled: bool,
    ) -> int:
        if not history_enabled or not isinstance(history_context, dict):
            return 0
        count = 0
        for row in all_ranked:
            item = history_context.get(canonical_symbol_key(row.ticker), {})
            if isinstance(item, dict) and bool(item.get("rank_requalified")):
                count += 1
        return count

    @staticmethod
    def _record_scanner_funnel(
        qc: Any,
        *,
        raw_candidates: int,
        ranked_candidates: int,
        rank_history_eligible: int,
        selected: int,
        all_ranked: list[Any],
    ) -> None:
        funnel = getattr(qc, "_scanner_ranker_funnel", None)
        if not isinstance(funnel, dict):
            funnel = {
                "days": 0,
                "raw_candidates": 0,
                "ranked_candidates": 0,
                "rank_history_eligible": 0,
                "selected": 0,
            }
            qc._scanner_ranker_funnel = funnel
        funnel["days"] = int(funnel.get("days", 0)) + 1
        funnel["raw_candidates"] = int(funnel.get("raw_candidates", 0)) + int(raw_candidates)
        funnel["ranked_candidates"] = int(funnel.get("ranked_candidates", 0)) + int(ranked_candidates)
        funnel["rank_history_eligible"] = int(funnel.get("rank_history_eligible", 0)) + int(rank_history_eligible)
        funnel["selected"] = int(funnel.get("selected", 0)) + int(selected)

        prior = getattr(qc, "_scanner_ranker_rank_sets", None)
        if not isinstance(prior, dict):
            prior = {rank: [] for rank in _OVERLAP_RANKS}
            qc._scanner_ranker_rank_sets = prior
        ranked_keys = [canonical_symbol_key(row.ticker) for row in all_ranked]
        for rank in _OVERLAP_RANKS:
            current = set(ranked_keys[:rank])
            funnel[f"top{rank}_observations"] = int(funnel.get(f"top{rank}_observations", 0)) + len(current)
            history = prior.setdefault(rank, [])
            for window in _OVERLAP_WINDOWS:
                window_sets = history[-window:]
                seen: set[str] = set()
                for prior_set in window_sets:
                    seen.update(prior_set)
                funnel[f"top{rank}_seen_last_{window}"] = int(
                    funnel.get(f"top{rank}_seen_last_{window}", 0)
                ) + len(current & seen)
            history.append(current)
            del history[:-max(_OVERLAP_WINDOWS)]

        setter = getattr(qc, "set_runtime_statistic", None) or getattr(qc, "SetRuntimeStatistic", None)
        if callable(setter):
            for key, value in sorted(funnel.items()):
                setter(f"scanner_funnel.{key}", str(value))

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
