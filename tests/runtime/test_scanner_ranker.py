from __future__ import annotations

import json
import math
from datetime import datetime

import pytest

from engine.context import OrderIntent
from runtime.scanner_ranker import (
    DENIED_FEATURE_TOKENS,
    DEPLOYABLE_SCANNER_FEATURES,
    ScannerCandidateRow,
    ScannerRankerError,
    build_scanner_candidate_rows,
    feature_contract_hash,
    load_scanner_model_artifact,
    rank_scanner_panel,
    scanner_cache_key,
)


class _Store:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads

    def contains_key(self, key: str) -> bool:
        return key in self.payloads

    def read(self, key: str) -> str:
        return self.payloads[key]


class _Current:
    def __init__(self, value: float) -> None:
        self.value = value


class _Line:
    def __init__(self, value: float) -> None:
        self.current = _Current(value)


class _Ichi:
    def __init__(self, *, tenkan: float = 100.0, kijun: float = 96.0, a: float = 94.0, b: float = 92.0) -> None:
        self.tenkan = _Line(tenkan)
        self.kijun = _Line(kijun)
        self.senkou_a = _Line(a)
        self.senkou_b = _Line(b)
        self.is_ready = True


class _Scalar:
    def __init__(self, value: float) -> None:
        self.current = _Current(value)
        self.is_ready = True


class _Adx(_Scalar):
    def __init__(self, value: float, plus: float = 28.0, minus: float = 12.0) -> None:
        super().__init__(value)
        self.positive_directional_index = _Scalar(plus)
        self.negative_directional_index = _Scalar(minus)


class _Window:
    count = 4

    def __getitem__(self, index: int) -> float:
        return (30.0, 28.0, 27.0, 24.0)[index]


class _TBounce:
    def __init__(self) -> None:
        self.last_prior_close = 100.0
        self.gap_pct = 5.0
        self.last_open = 105.0
        self.last_high = 1000.0
        self.last_low = 103.0
        self.last_close = 110.0
        self.last_volume = 2_000_000.0
        self.prior_high20 = 100.0
        self.prior_high50 = 120.0
        self.prior_high252 = 130.0
        self.rel_volume20 = 2.0


class _Security:
    def __init__(self, price: float) -> None:
        self.price = price


class _QC:
    def __init__(self) -> None:
        self._active = {"AAA", "BBB"}
        self._trailing_dv = {"aaa": 150_000_000.0, "bbb": 90_000_000.0}
        self._signal_features = {
            "AAA": {"score": 8, "conditions": [True, True, False, True, True, True, True, True]},
            "BBB": {"score": 6, "conditions": [True, False, False, True, True, True, False, True]},
        }
        self._sector_by_ticker = {"aaa": "Technology", "bbb": "Technology"}
        self._industry_by_ticker = {"aaa": "Software", "bbb": "Hardware"}
        self.securities = {"AAA": _Security(110.0), "BBB": _Security(90.0)}
        self._indicators = {
            "AAA": {
                "d_ichi": _Ichi(),
                "w_ichi": _Ichi(tenkan=95.0, kijun=90.0, a=88.0, b=84.0),
                "sma200": _Scalar(80.0),
                "adx": _Adx(30.0),
                "adx_window": _Window(),
                "roc13": _Scalar(0.04),
                "tbounce": _TBounce(),
            },
            "BBB": {
                "d_ichi": _Ichi(tenkan=95.0, kijun=90.0, a=85.0, b=80.0),
                "sma200": _Scalar(70.0),
                "adx": _Adx(20.0),
                "adx_window": _Window(),
                "roc13": _Scalar(0.02),
                "tbounce": _TBounce(),
            },
        }


def _artifact(feature_names: list[str] | None = None) -> str:
    features = feature_names or ["bct_score", "daily_structure_score"]
    return json.dumps(
        {
            "schema_version": 1,
            "model_type": "lambdamart_tree_ensemble",
            "feature_names": features,
            "feature_list_hash": feature_contract_hash(tuple(features)),
            "base_score": 0.0,
            "trees": [
                {
                    "shrinkage": 1.0,
                    "tree_structure": {
                        "split_feature": features[0],
                        "threshold": 6.5,
                        "default_left": True,
                        "left_child": {"leaf_value": 1.0},
                        "right_child": {"leaf_value": 10.0},
                    },
                }
            ],
            "metadata": {"training": "unit-test-fixture"},
        },
        sort_keys=True,
    )


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="test", risk_dollars=0.0)


def test_model_loads_from_local_file_and_objectstore_with_same_hash(tmp_path) -> None:
    text = _artifact()
    path = tmp_path / "scanner.json"
    path.write_text(text, encoding="utf-8")

    local_model = load_scanner_model_artifact(str(path))
    store_model = load_scanner_model_artifact("objectstore://scanner.json", _Store({"scanner.json": text}))

    assert local_model.artifact_hash == store_model.artifact_hash
    assert local_model.feature_names == ("bct_score", "daily_structure_score")


def test_model_load_failure_is_loud(tmp_path) -> None:
    with pytest.raises(ScannerRankerError, match="not found"):
        load_scanner_model_artifact(str(tmp_path / "missing.json"))


def test_artifact_rejects_denied_george_features(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(_artifact(["george_rank_pct"]), encoding="utf-8")

    with pytest.raises(ScannerRankerError, match="denied"):
        load_scanner_model_artifact(str(path))


def test_deployable_contract_has_no_label_or_ocr_features() -> None:
    for feature in DEPLOYABLE_SCANNER_FEATURES:
        lowered = feature.lower()
        assert not any(token in lowered for token in DENIED_FEATURE_TOKENS)


def test_ranking_is_deterministic_and_top_x_selects_highest_score(tmp_path) -> None:
    path = tmp_path / "scanner.json"
    path.write_text(_artifact(["bct_score"]), encoding="utf-8")
    model = load_scanner_model_artifact(str(path))
    rows = [
        ScannerCandidateRow("LOW", {"bct_score": 6.0}),
        ScannerCandidateRow("HIGH", {"bct_score": 8.0}),
        ScannerCandidateRow("ALSO_HIGH", {"bct_score": 9.0}),
    ]

    ranked = rank_scanner_panel(rows, model, top_x=2)

    assert [row.ticker for row in ranked] == ["HIGH", "ALSO_HIGH"]
    assert [row.score for row in ranked] == [10.0, 10.0]


def test_cache_key_parity_uses_artifact_hash_not_load_source(tmp_path) -> None:
    text = _artifact()
    path = tmp_path / "scanner.json"
    path.write_text(text, encoding="utf-8")
    local_model = load_scanner_model_artifact(str(path))
    store_model = load_scanner_model_artifact("scanner.json", _Store({"scanner.json": text}))

    kwargs = {
        "panel_date": "2025-01-02",
        "tickers": ("AAA", "BBB"),
        "top_x": 10,
        "min_score": None,
        "taxonomy_hash": "taxonomy-v1",
    }
    assert scanner_cache_key(artifact_hash=local_model.artifact_hash, **kwargs) == scanner_cache_key(
        artifact_hash=store_model.artifact_hash,
        **kwargs,
    )


def test_feature_builder_uses_point_in_time_prior_high_and_adds_live_ranks() -> None:
    rows = build_scanner_candidate_rows(_QC(), [_intent("AAA"), _intent("BBB")])

    aaa = rows[0].features

    assert aaa["gap_pct"] == 5.0
    assert aaa["day_return_pct"] == 10.0
    assert aaa["d_distance_to_prior_high20_pct"] == 10.0
    assert aaa["d_distance_to_prior_high20_pct"] != pytest.approx((110.0 - 1000.0) / 1000.0)
    assert aaa["sector_denominator_count"] == 2
    assert aaa["bct_score_rank_in_panel"] == 1.0
    assert aaa["bct_score_pctile_in_panel"] == 1.0
    assert math.isfinite(float(aaa["daily_structure_score"]))


def test_scanner_cache_key_is_order_sensitive_to_panel_membership() -> None:
    left = scanner_cache_key(
        artifact_hash="abc",
        panel_date=datetime(2025, 1, 2).strftime("%Y-%m-%d"),
        tickers=("AAA", "BBB"),
        top_x=10,
        min_score=None,
    )
    right = scanner_cache_key(
        artifact_hash="abc",
        panel_date="2025-01-02",
        tickers=("BBB", "AAA"),
        top_x=10,
        min_score=None,
    )
    assert left != right
