from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.context import OrderIntent, PhaseContext
from phases.ranking.lambdamart_scanner_ranker.lambdamart_scanner_ranker import LambdamartScannerRanker
from runtime.scanner_ranker import (
    ScannerRankerError,
    feature_contract_hash,
    load_scanner_model_artifact,
    opportunity_feature_contract_hash,
)


class _Store:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads

    def contains_key(self, key: str) -> bool:
        return key in self.payloads

    def read(self, key: str) -> str:
        return self.payloads[key]


class _QC:
    SCANNER_RANKER_ENABLED = True
    SCANNER_RANKER_MODEL_PATH = "objectstore://scanner.json"
    SCANNER_RANKER_TOP_X = 1
    SCANNER_RANKER_MIN_SCORE = None
    SCANNER_RANKER_FALLBACK = "raise"

    def __init__(self, artifact: str | None = None) -> None:
        self.object_store = _Store({"scanner.json": artifact} if artifact else {})
        self._signal_features = {
            "AAA": {"score": 6, "conditions": []},
            "BBB": {"score": 8, "conditions": []},
        }
        self._trailing_dv = {"aaa": 10.0, "bbb": 20.0}
        self._active = {"AAA", "BBB"}
        self._indicators = {}
        self._sector_by_ticker = {}
        self._industry_by_ticker = {}
        self.securities = {}
        self.runtime_stats: dict[str, str] = {}

    def set_runtime_statistic(self, key: str, value: str) -> None:
        self.runtime_stats[key] = value


def _artifact() -> str:
    features = ["bct_score"]
    return json.dumps(
        {
            "schema_version": 1,
            "model_type": "lambdamart_tree_ensemble",
            "feature_names": features,
            "feature_list_hash": feature_contract_hash(tuple(features)),
            "base_score": 0.0,
            "trees": [
                {
                    "tree_structure": {
                        "split_feature": "bct_score",
                        "threshold": 7.0,
                        "default_left": True,
                        "left_child": {"leaf_value": 0.1},
                        "right_child": {"leaf_value": 1.1},
                    }
                }
            ],
        },
        sort_keys=True,
    )


def _linear_artifact(feature: str = "kumo_score") -> str:
    features = [feature]
    return json.dumps(
        {
            "schema_version": 1,
            "model_type": "linear_pairwise_ranker",
            "feature_version": "scanner_opportunity_scan_time_v1",
            "feature_hash": opportunity_feature_contract_hash(tuple(features)),
            "feature_names": features,
            "standardizer": {"mean": [0.0], "scale": [1.0]},
            "models": {
                "trade_worthy": {"coef": [1.0], "intercept": 0.0},
                "runner": {"coef": [1.0], "intercept": 0.0},
            },
            "combined_score": {"trade_worthy_weight": 0.7, "runner_weight": 0.3},
        },
        sort_keys=True,
    )


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="test", risk_dollars=0.0)


def _ctx(qc: _QC, tickers: list[str] | None = None, *, when: datetime | None = None) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=when or datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [_intent(ticker) for ticker in (tickers or ["AAA", "BBB"])]
    return ctx


def test_phase_selects_top_x_from_model_scores() -> None:
    qc = _QC(_artifact())
    ctx = _ctx(qc)

    result = LambdamartScannerRanker(LambdamartScannerRanker.Params(), logger=None).evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["BBB"]
    assert result.facts["selected"] == 1
    assert qc._scanner_ranker_scores[0]["ticker"] == "bbb"
    assert qc._scanner_ranker_context["bbb"]["scanner_rank"] == 1
    assert qc._scanner_ranker_context["bbb"]["scanner_score"] == 1.1
    assert qc._scanner_ranker_context["bbb"]["scanner_features"]["bct_score"] == 8
    assert qc._scanner_ranker_cache_key


def test_phase_selects_top_x_from_linear_opportunity_artifact() -> None:
    qc = _QC(_linear_artifact())
    ctx = _ctx(qc)

    result = LambdamartScannerRanker(LambdamartScannerRanker.Params(), logger=None).evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["BBB"]
    assert result.facts["model_type"] == "linear_pairwise_ranker"
    assert qc._scanner_ranker_context["bbb"]["scanner_features"]["kumo_score"] == 8
    assert qc._scanner_ranker_context["bbb"]["scanner_features"]["kumo_rank_by_score"] == 2
    assert qc._scanner_ranker_cache_key


def test_committed_467_opportunity_artifact_loads() -> None:
    root = Path(__file__).resolve().parents[3]
    artifact = root / "sweeps" / "reports" / "scanner_opportunity_ranker_467" / "model_artifact.json"
    model = load_scanner_model_artifact(str(artifact))

    assert model.model_type == "linear_pairwise_ranker"
    assert model.feature_hash == "96eda175c8439bc9b988e5823e37a4d7c11b46d3f33fb008f70087b0add2896e"
    assert "kumo_score" in model.feature_names


def test_linear_opportunity_artifact_blocks_source_features() -> None:
    payload = json.loads(_linear_artifact("george_watchlist"))
    payload["feature_hash"] = opportunity_feature_contract_hash(tuple(payload["feature_names"]))
    qc = _QC(json.dumps(payload))

    try:
        LambdamartScannerRanker(LambdamartScannerRanker.Params(), logger=None).evaluate(_ctx(qc))
    except ScannerRankerError as exc:
        assert "denied runtime features" in str(exc)
    else:
        raise AssertionError("expected denied feature to fail")


def test_phase_disabled_by_runtime_is_passthrough() -> None:
    qc = _QC(_artifact())
    qc.SCANNER_RANKER_ENABLED = False
    ctx = _ctx(qc)

    result = LambdamartScannerRanker(LambdamartScannerRanker.Params(), logger=None).evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["AAA", "BBB"]
    assert result.facts["enabled"] is False
    assert qc._scanner_ranker_context == {}


def test_missing_model_can_fallback_to_bct_order() -> None:
    qc = _QC()
    qc.SCANNER_RANKER_FALLBACK = "bct_order"
    ctx = _ctx(qc)

    result = LambdamartScannerRanker(LambdamartScannerRanker.Params(), logger=None).evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["AAA", "BBB"]
    assert result.facts["fallback"] == "bct_order"
    assert "missing" in qc._scanner_ranker_error
    assert qc._scanner_ranker_context == {}


def test_rank_history_requalifies_repeated_core_names_without_top_x() -> None:
    qc = _QC(_linear_artifact())
    qc.SCANNER_RANKER_TOP_X = 0
    qc._signal_features = {
        "AAA": {"score": 9, "conditions": []},
        "BBB": {"score": 8, "conditions": []},
        "CCC": {"score": 7, "conditions": []},
    }
    qc._trailing_dv = {"aaa": 30.0, "bbb": 20.0, "ccc": 10.0}
    qc._active = {"AAA", "BBB", "CCC"}
    phase = LambdamartScannerRanker(
        LambdamartScannerRanker.Params(
            scanner_rank_history_enabled=True,
            scanner_rank_history_focus_rank=1,
            scanner_rank_history_core_rank=3,
            scanner_rank_history_min_seen_short=2,
            scanner_rank_history_min_persistence_score=99.0,
        ),
        logger=None,
    )

    day1 = _ctx(qc, ["AAA", "BBB", "CCC"], when=datetime(2025, 1, 2))
    result1 = phase.evaluate(day1)
    day2 = _ctx(qc, ["AAA", "BBB", "CCC"], when=datetime(2025, 1, 3))
    result2 = phase.evaluate(day2)

    assert [intent.ticker for intent in day1.bar_state.sized_orders] == ["AAA"]
    assert [intent.ticker for intent in day2.bar_state.sized_orders] == ["AAA", "BBB", "CCC"]
    assert result1.facts["rank_history_enabled"] is True
    assert result2.facts["selected"] == 3
    assert result2.facts["scanner_ranked"] == 3
    assert result2.facts["rank_history_eligible"] == 3
    assert qc._scanner_rank_history_context["bbb"]["days_seen_last_5"] == 2
    assert qc._scanner_rank_history_context["bbb"]["rank_requalification_state"] == "short_persistent_core"
    assert qc._scanner_ranker_context["bbb"]["scanner_rank"] == 2
    assert qc._scanner_ranker_context["bbb"]["scanner_rank_history"]["days_seen_last_5"] == 2
    assert len(qc._scanner_ranker_all_scores) == 3
    assert qc.runtime_stats["scanner_funnel.days"] == "2"
    assert qc.runtime_stats["scanner_funnel.raw_candidates"] == "6"
    assert qc.runtime_stats["scanner_funnel.ranked_candidates"] == "6"
    assert qc.runtime_stats["scanner_funnel.rank_history_eligible"] == "4"
    assert qc.runtime_stats["scanner_funnel.selected"] == "4"
    assert qc.runtime_stats["scanner_funnel.top10_observations"] == "6"
    assert qc.runtime_stats["scanner_funnel.top10_seen_last_1"] == "3"


def test_rank_history_respects_min_score_after_history_requalification() -> None:
    qc = _QC(_linear_artifact())
    qc.SCANNER_RANKER_TOP_X = 0
    qc.SCANNER_RANKER_MIN_SCORE = 8.5
    qc._signal_features = {
        "AAA": {"score": 9, "conditions": []},
        "BBB": {"score": 8, "conditions": []},
    }
    qc._trailing_dv = {"aaa": 30.0, "bbb": 20.0}
    phase = LambdamartScannerRanker(
        LambdamartScannerRanker.Params(
            scanner_rank_history_enabled=True,
            scanner_rank_history_focus_rank=10,
            scanner_rank_history_min_persistence_score=99.0,
        ),
        logger=None,
    )

    ctx = _ctx(qc, ["AAA", "BBB"])
    phase.evaluate(ctx)

    assert [intent.ticker for intent in ctx.bar_state.sized_orders] == ["AAA"]
    assert qc._scanner_rank_history_context["bbb"]["rank_requalified"] is True
    assert "bbb" not in qc._scanner_ranker_context
