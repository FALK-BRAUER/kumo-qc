from __future__ import annotations

import json
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.ranking.lambdamart_scanner_ranker.lambdamart_scanner_ranker import LambdamartScannerRanker
from runtime.scanner_ranker import feature_contract_hash


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


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="test", risk_dollars=0.0)


def _ctx(qc: _QC) -> PhaseContext:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [_intent("AAA"), _intent("BBB")]
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
