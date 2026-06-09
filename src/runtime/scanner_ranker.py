"""Deployable BCT/George-style scanner ranker runtime.

This module is intentionally dependency-free for QC cloud. It consumes only live QC/runtime state,
loads an exported JSON tree ensemble from a local path or ObjectStore, and scores same-day scanner
candidate panels with a fixed deployable feature contract. George OCR/watchlist labels are never
runtime inputs; they belong only in the research exporter that trains the artifact.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.symbol_key import canonical_symbol_key
from phases.shared.chart_features import (
    ChartCurationInputs,
    build_chart_curation_features,
    george_qc_candidate_score,
)
from phases.shared.sector_breadth import BreadthCandidate, sector_industry_breadth_rows

FEATURE_CONTRACT_VERSION = "bct_lambdamart_qc_safe_v1"
DENOMINATOR_CONTRACT_VERSION = "live_signal_candidate_panel_v1"
ARTIFACT_SCHEMA_VERSION = 1

SECTOR_BREADTH_FEATURES: tuple[str, ...] = (
    "sector_denominator_count",
    "sector_bct6_count",
    "sector_bct7_count",
    "sector_positive_return_count",
    "sector_median_day_return_pct",
    "sector_median_rel_volume20",
    "sector_bct6_pct",
    "sector_bct7_pct",
    "sector_positive_return_pct",
    "industry_denominator_count",
    "industry_bct6_count",
    "industry_bct7_count",
    "industry_positive_return_count",
    "industry_median_day_return_pct",
    "industry_median_rel_volume20",
    "industry_bct6_pct",
    "industry_bct7_pct",
    "industry_positive_return_pct",
)

DENOMINATOR_RANK_SPECS: tuple[tuple[str, str], ...] = (
    ("gap_pct", "gap_pct"),
    ("day_return_pct", "day_return_pct"),
    ("rel_volume20", "rel_volume20"),
    ("bct_score", "bct_score"),
    ("daily_structure_score", "daily_structure_score"),
    ("d_cloud_distance_pct", "daily_cloud_distance_pct"),
    ("day_dollar_vol", "day_dollar_vol"),
    ("adv20_incl_today", "adv20"),
)

DENOMINATOR_RANK_FEATURES: tuple[str, ...] = tuple(
    feature
    for _source, prefix in DENOMINATOR_RANK_SPECS
    for feature in (
        f"{prefix}_rank_in_panel",
        f"{prefix}_pctile_in_panel",
    )
)

DEPLOYABLE_SCANNER_FEATURES: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            "bct_score",
            "gap_pct",
            "day_return_pct",
            "rel_volume20",
            "day_dollar_vol",
            "adv20_incl_today",
            "daily_structure_score",
            "d_price_above_cloud",
            "d_price_above_tenkan",
            "d_price_above_kijun",
            "d_tenkan_gt_kijun",
            "d_cloud_green",
            "d_price_above_ma200",
            "d_cloud_distance_pct",
            "d_tenkan_extension_pct",
            "d_kijun_extension_pct",
            "d_tk_spread_pct",
            "d_distance_to_prior_high20_pct",
            "d_distance_to_prior_high50_pct",
            "d_distance_to_prior_high252_pct",
            "d_near_prior20_high_within3",
            "d_near_prior50_high_within5",
            "d_near_prior252_high_within5",
            "d_recent_resistance_rejection_count20",
            "d_breakout20_volume_confirmed",
            "d_breakout50_volume_confirmed",
            "d_breakout252_volume_confirmed",
            "d_resistance_rejection_today",
            "d_no_chase_risk",
            "d_body_pct_range",
            "d_upper_wick_pct_range",
            "d_lower_wick_pct_range",
            "d_volume_spike_150",
            "d_adx",
            "d_plus_di",
            "d_minus_di",
            "d_adx_rising_3",
            "bct_c1_weekly_price_above_cloud",
            "bct_c2_weekly_tenkan_gt_kijun",
            "bct_c3_weekly_chikou_ok",
            "bct_c4_weekly_cloud_green",
            "bct_c5_daily_price_above_cloud",
            "bct_c6_daily_price_above_tenkan",
            "bct_c7_adx_confirmed",
            "bct_c8_daily_price_above_ma200",
            "w_price_above_cloud",
            "w_cloud_green",
            "w_tenkan_gt_kijun",
            "w_chikou_ok",
            "w_cloud_distance_pct",
            "w_tenkan_extension_pct",
            *DENOMINATOR_RANK_FEATURES,
            *SECTOR_BREADTH_FEATURES,
        )
    )
)

DENIED_FEATURE_TOKENS: tuple[str, ...] = (
    "george",
    "ocr",
    "watchlist",
    "future",
    "label",
    "scanner_rank",
    "post",
    "video",
    "transcript",
)


class ScannerRankerError(RuntimeError):
    """Raised when the scanner ranker cannot safely score a panel."""


@dataclass(frozen=True, slots=True)
class ScannerCandidateRow:
    ticker: str
    features: dict[str, float | bool]


@dataclass(frozen=True, slots=True)
class RankedScannerCandidate:
    ticker: str
    score: float
    original_index: int
    features: dict[str, float | bool]


@dataclass(frozen=True, slots=True)
class ScannerModelArtifact:
    feature_names: tuple[str, ...]
    trees: tuple[dict[str, Any], ...]
    base_score: float
    artifact_hash: str
    metadata: dict[str, Any]


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def feature_contract_hash(feature_names: tuple[str, ...] = DEPLOYABLE_SCANNER_FEATURES) -> str:
    payload = {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "denominator_contract_version": DENOMINATOR_CONTRACT_VERSION,
        "feature_names": list(feature_names),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def scanner_cache_key(
    *,
    artifact_hash: str,
    panel_date: str,
    tickers: tuple[str, ...],
    top_x: int,
    min_score: float | None,
    taxonomy_hash: str = "",
    feature_hash: str | None = None,
) -> str:
    """Deterministic feature/model cache key shared by local, cloud, and offline runners."""
    payload = {
        "artifact_hash": artifact_hash,
        "denominator_contract_version": DENOMINATOR_CONTRACT_VERSION,
        "feature_hash": feature_hash or feature_contract_hash(),
        "min_score": min_score,
        "panel_date": panel_date,
        "taxonomy_hash": taxonomy_hash,
        "tickers": [canonical_symbol_key(ticker) for ticker in tickers],
        "top_x": int(top_x),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _validate_feature_names(feature_names: tuple[str, ...]) -> None:
    if not feature_names:
        raise ScannerRankerError("scanner ranker artifact has no feature_names")
    allowed = set(DEPLOYABLE_SCANNER_FEATURES)
    denied = [
        name
        for name in feature_names
        if any(token in name.lower() for token in DENIED_FEATURE_TOKENS)
    ]
    if denied:
        raise ScannerRankerError(f"scanner ranker artifact uses denied runtime features: {denied}")
    unknown = sorted(set(feature_names) - allowed)
    if unknown:
        raise ScannerRankerError(f"scanner ranker artifact uses features outside deployable contract: {unknown}")


def _object_store_contains(object_store: Any, key: str) -> bool:
    contains = getattr(object_store, "contains_key", None)
    if callable(contains):
        return bool(contains(key))
    contains = getattr(object_store, "contains", None)
    if callable(contains):
        return bool(contains(key))
    return False


def _object_store_read(object_store: Any, key: str) -> str:
    read = getattr(object_store, "read", None)
    if callable(read):
        value = read(key)
    else:
        read_bytes = getattr(object_store, "read_bytes", None)
        if not callable(read_bytes):
            raise ScannerRankerError("ObjectStore does not expose read/read_bytes")
        value = read_bytes(key)
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _load_artifact_text(path_or_key: str, object_store: Any | None) -> str:
    source = str(path_or_key or "").strip()
    if not source:
        raise ScannerRankerError("scanner ranker model path/key is empty")

    object_key = None
    if source.startswith("objectstore://"):
        object_key = source.removeprefix("objectstore://")
    elif source.startswith("objectstore:"):
        object_key = source.removeprefix("objectstore:")
    if object_key is not None:
        if object_store is None or not _object_store_contains(object_store, object_key):
            raise ScannerRankerError(f"scanner ranker ObjectStore key missing: {object_key}")
        return _object_store_read(object_store, object_key)

    path = Path(source)
    if path.exists():
        return path.read_text(encoding="utf-8")
    if object_store is not None and _object_store_contains(object_store, source):
        return _object_store_read(object_store, source)
    raise ScannerRankerError(f"scanner ranker model not found as local path or ObjectStore key: {source}")


def load_scanner_model_artifact(path_or_key: str, object_store: Any | None = None) -> ScannerModelArtifact:
    """Load and validate an exported LambdaMART JSON tree artifact."""
    text = _load_artifact_text(path_or_key, object_store)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScannerRankerError(f"scanner ranker artifact is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ScannerRankerError("scanner ranker artifact root must be an object")
    if int(raw.get("schema_version", 0)) != ARTIFACT_SCHEMA_VERSION:
        raise ScannerRankerError(
            f"scanner ranker artifact schema_version must be {ARTIFACT_SCHEMA_VERSION}"
        )
    model_type = str(raw.get("model_type", ""))
    if model_type not in {"lambdamart_tree_ensemble", "lightgbm_lambdamart_json"}:
        raise ScannerRankerError(f"unsupported scanner ranker model_type: {model_type!r}")
    feature_names = tuple(str(name) for name in raw.get("feature_names", ()))
    _validate_feature_names(feature_names)
    trees_raw = raw.get("trees", ())
    if not isinstance(trees_raw, list) or not trees_raw:
        raise ScannerRankerError("scanner ranker artifact must contain at least one tree")
    base_score = _finite_float(raw.get("base_score"), default=0.0)
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    expected_hash = raw.get("feature_list_hash")
    if expected_hash is not None:
        actual_hash = feature_contract_hash(feature_names)
        if str(expected_hash) != actual_hash:
            raise ScannerRankerError(
                f"scanner ranker feature_list_hash mismatch: expected {expected_hash}, actual {actual_hash}"
            )
    return ScannerModelArtifact(
        feature_names=feature_names,
        trees=tuple(dict(tree) for tree in trees_raw),
        base_score=base_score,
        artifact_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata=metadata,
    )


def score_features(model: ScannerModelArtifact, features: dict[str, float | bool]) -> float:
    score = float(model.base_score)
    for tree in model.trees:
        score += _finite_float(tree.get("shrinkage"), default=1.0) * _eval_tree(
            tree.get("tree_structure", tree),
            model.feature_names,
            features,
        )
    return score


def rank_scanner_panel(
    rows: list[ScannerCandidateRow],
    model: ScannerModelArtifact,
    *,
    top_x: int,
    min_score: float | None = None,
) -> list[RankedScannerCandidate]:
    if top_x < 0:
        raise ScannerRankerError(f"scanner_ranker_top_x must be >= 0, got {top_x}")
    scored = [
        RankedScannerCandidate(
            ticker=row.ticker,
            score=score_features(model, row.features),
            original_index=index,
            features=row.features,
        )
        for index, row in enumerate(rows)
    ]
    if min_score is not None:
        scored = [row for row in scored if row.score >= min_score]
    scored.sort(key=lambda row: (-row.score, row.original_index, canonical_symbol_key(row.ticker)))
    return scored[:top_x] if top_x else scored


def build_scanner_candidate_rows(qc: Any, intents: list[Any]) -> list[ScannerCandidateRow]:
    """Build deployable same-day feature rows in the same order as the candidate intents."""
    base_rows: list[ScannerCandidateRow] = []
    breadth_inputs: list[BreadthCandidate] = []
    for intent in intents:
        ticker = canonical_symbol_key(getattr(intent, "ticker", ""))
        features = _base_features(qc, intent, ticker)
        base_rows.append(ScannerCandidateRow(ticker=ticker, features=features))
        breadth_inputs.append(
            BreadthCandidate(
                ticker=ticker,
                bct_score=features.get("bct_score"),
                day_return_pct=features.get("day_return_pct"),
                rel_volume20=features.get("rel_volume20"),
            )
        )

    breadth_rows = sector_industry_breadth_rows(
        breadth_inputs,
        sector_by_ticker=getattr(qc, "_sector_by_ticker", {}),
        industry_by_ticker=getattr(qc, "_industry_by_ticker", {}),
    )
    rows_with_breadth: list[ScannerCandidateRow] = []
    for row, breadth in zip(base_rows, breadth_rows, strict=False):
        features = dict(row.features)
        for name in SECTOR_BREADTH_FEATURES:
            features[name] = _finite_float(breadth.get(name), default=0.0)
        rows_with_breadth.append(ScannerCandidateRow(ticker=row.ticker, features=features))

    return _add_denominator_ranks(rows_with_breadth)


def _base_features(qc: Any, intent: Any, ticker: str) -> dict[str, float | bool]:
    symbol = _active_symbol(qc, ticker)
    indicators = _lookup(getattr(qc, "_indicators", {}), ticker, symbol)
    ind = indicators if isinstance(indicators, dict) else {}
    tbounce = ind.get("tbounce")
    d_ichi = ind.get("d_ichi")
    w_ichi = ind.get("w_ichi")
    sma200 = ind.get("sma200")
    adx = ind.get("adx")
    adx_window = ind.get("adx_window")
    signal_row = _lookup(getattr(qc, "_signal_features", {}), ticker, symbol)
    signal = signal_row if isinstance(signal_row, dict) else {}

    price = _security_price(qc, intent, symbol)
    close = _tbounce_float(tbounce, "last_close") or price
    open_ = _tbounce_float(tbounce, "last_open")
    high = _tbounce_float(tbounce, "last_high")
    low = _tbounce_float(tbounce, "last_low")
    prior_close = _tbounce_float(tbounce, "last_prior_close")
    volume = _tbounce_float(tbounce, "last_volume")
    bct_score = _finite_float(signal.get("score"), default=0.0)
    d_cloud_a = _line_value(d_ichi, "senkou_a")
    d_cloud_b = _line_value(d_ichi, "senkou_b")
    d_cloud_top = max(d_cloud_a, d_cloud_b) if d_cloud_a is not None and d_cloud_b is not None else None
    d_cloud_bottom = min(d_cloud_a, d_cloud_b) if d_cloud_a is not None and d_cloud_b is not None else None
    d_tenkan = _line_value(d_ichi, "tenkan")
    d_kijun = _line_value(d_ichi, "kijun")
    w_cloud_a = _line_value(w_ichi, "senkou_a")
    w_cloud_b = _line_value(w_ichi, "senkou_b")
    w_cloud_top = max(w_cloud_a, w_cloud_b) if w_cloud_a is not None and w_cloud_b is not None else None
    w_tenkan = _line_value(w_ichi, "tenkan")
    w_kijun = _line_value(w_ichi, "kijun")

    chart_inputs = ChartCurationInputs(
        bct_score=int(bct_score),
        open=open_,
        high=high,
        low=low,
        close=close,
        tenkan=d_tenkan,
        kijun=d_kijun,
        cloud_top=d_cloud_top,
        cloud_bottom=d_cloud_bottom,
        adx=_current_value(adx),
        roc13=_current_value(ind.get("roc13")),
        rel_volume20=_tbounce_float(tbounce, "rel_volume20"),
        prior_high20=_tbounce_float(tbounce, "prior_high20"),
        prior_high50=_tbounce_float(tbounce, "prior_high50"),
        prior_high252=_tbounce_float(tbounce, "prior_high252"),
        recent_resistance_rejection_count20=int(
            _tbounce_float(tbounce, "recent_resistance_rejection_count20") or 0
        ),
    )
    chart = build_chart_curation_features(chart_inputs)
    conditions = signal.get("conditions", ())
    trailing_dv = _trailing_dollar_volume(qc, ticker)
    day_dollar_vol = close * volume if volume is not None and close > 0.0 else math.nan
    day_return_pct = _pct_distance(close, prior_close)

    features: dict[str, float | bool] = {
        "bct_score": bct_score,
        "gap_pct": _tbounce_float(tbounce, "gap_pct") or 0.0,
        "day_return_pct": day_return_pct,
        "rel_volume20": chart_inputs.rel_volume20 if chart_inputs.rel_volume20 is not None else math.nan,
        "day_dollar_vol": day_dollar_vol,
        "adv20_incl_today": trailing_dv,
        "daily_structure_score": george_qc_candidate_score(chart),
        "d_price_above_cloud": chart.price_above_cloud,
        "d_price_above_tenkan": chart.price_above_tenkan,
        "d_price_above_kijun": chart.price_above_kijun,
        "d_tenkan_gt_kijun": _gt(d_tenkan, d_kijun),
        "d_cloud_green": _gt(d_cloud_a, d_cloud_b),
        "d_price_above_ma200": _gt(close, _current_value(sma200)),
        "d_cloud_distance_pct": _pct_or_nan(chart.cloud_distance_pct),
        "d_tenkan_extension_pct": _pct_or_nan(chart.tenkan_extension_pct),
        "d_kijun_extension_pct": _pct_or_nan(chart.kijun_extension_pct),
        "d_tk_spread_pct": _pct_distance(d_tenkan, d_kijun),
        "d_distance_to_prior_high20_pct": _pct_distance(close, chart_inputs.prior_high20),
        "d_distance_to_prior_high50_pct": _pct_distance(close, chart_inputs.prior_high50),
        "d_distance_to_prior_high252_pct": _pct_distance(close, chart_inputs.prior_high252),
        "d_near_prior20_high_within3": _near(close, chart_inputs.prior_high20, 3.0),
        "d_near_prior50_high_within5": _near(close, chart_inputs.prior_high50, 5.0),
        "d_near_prior252_high_within5": _near(close, chart_inputs.prior_high252, 5.0),
        "d_recent_resistance_rejection_count20": chart_inputs.recent_resistance_rejection_count20,
        "d_breakout20_volume_confirmed": _breakout_volume(close, chart_inputs.prior_high20, chart_inputs.rel_volume20),
        "d_breakout50_volume_confirmed": _breakout_volume(close, chart_inputs.prior_high50, chart_inputs.rel_volume20),
        "d_breakout252_volume_confirmed": _breakout_volume(close, chart_inputs.prior_high252, chart_inputs.rel_volume20),
        "d_resistance_rejection_today": chart.resistance_rejection_today,
        "d_no_chase_risk": chart.no_chase_risk,
        "d_body_pct_range": _pct_or_nan(chart.body_ratio),
        "d_upper_wick_pct_range": _pct_or_nan(chart.upper_wick_ratio),
        "d_lower_wick_pct_range": _pct_or_nan(chart.lower_wick_ratio),
        "d_volume_spike_150": _gte(chart_inputs.rel_volume20, 1.5),
        "d_adx": _current_value(adx) or math.nan,
        "d_plus_di": _current_value(getattr(adx, "positive_directional_index", None)) or math.nan,
        "d_minus_di": _current_value(getattr(adx, "negative_directional_index", None)) or math.nan,
        "d_adx_rising_3": _adx_rising_3(adx_window),
        "w_price_above_cloud": _gt(close, w_cloud_top),
        "w_cloud_green": _gt(w_cloud_a, w_cloud_b),
        "w_tenkan_gt_kijun": _gt(w_tenkan, w_kijun),
        "w_chikou_ok": _weekly_chikou_ok(ind.get("w_close")),
        "w_cloud_distance_pct": _pct_distance(close, w_cloud_top),
        "w_tenkan_extension_pct": _pct_distance(close, w_tenkan),
    }
    for index in range(8):
        name = (
            "bct_c1_weekly_price_above_cloud",
            "bct_c2_weekly_tenkan_gt_kijun",
            "bct_c3_weekly_chikou_ok",
            "bct_c4_weekly_cloud_green",
            "bct_c5_daily_price_above_cloud",
            "bct_c6_daily_price_above_tenkan",
            "bct_c7_adx_confirmed",
            "bct_c8_daily_price_above_ma200",
        )[index]
        features[name] = bool(index < len(conditions) and conditions[index])
    return features


def _add_denominator_ranks(rows: list[ScannerCandidateRow]) -> list[ScannerCandidateRow]:
    out = [ScannerCandidateRow(row.ticker, dict(row.features)) for row in rows]
    for source, prefix in DENOMINATOR_RANK_SPECS:
        values = [_numeric(row.features.get(source)) for row in out]
        descending_ranks = _average_ranks(values, ascending=False)
        ascending_pctiles = _average_ranks(values, ascending=True)
        finite_n = sum(1 for value in values if _is_finite(value))
        for row, rank, pctile_rank in zip(out, descending_ranks, ascending_pctiles, strict=False):
            row.features[f"{prefix}_rank_in_panel"] = rank
            row.features[f"{prefix}_pctile_in_panel"] = (
                pctile_rank / float(finite_n) if finite_n and _is_finite(pctile_rank) else math.nan
            )
    return out


def _average_ranks(values: list[float], *, ascending: bool) -> list[float]:
    ranked = sorted(
        [(value, index) for index, value in enumerate(values) if _is_finite(value)],
        key=lambda item: (item[0], item[1]),
        reverse=not ascending,
    )
    ranks = [math.nan] * len(values)
    position = 1
    i = 0
    while i < len(ranked):
        value = ranked[i][0]
        j = i + 1
        while j < len(ranked) and ranked[j][0] == value:
            j += 1
        avg_rank = (position + position + (j - i) - 1) / 2.0
        for _value, original_index in ranked[i:j]:
            ranks[original_index] = avg_rank
        position += j - i
        i = j
    return ranks


def _eval_tree(node: Any, feature_names: tuple[str, ...], features: dict[str, float | bool]) -> float:
    if not isinstance(node, dict):
        raise ScannerRankerError("tree node must be an object")
    if "leaf_value" in node:
        return _finite_float(node.get("leaf_value"), default=0.0)
    split = node.get("split_feature")
    if isinstance(split, int):
        if split < 0 or split >= len(feature_names):
            raise ScannerRankerError(f"split_feature index out of bounds: {split}")
        feature_name = feature_names[split]
    else:
        feature_name = str(split)
    if feature_name not in feature_names:
        raise ScannerRankerError(f"tree split_feature {feature_name!r} not in artifact feature_names")
    threshold = _finite_float(node.get("threshold"), default=0.0)
    value = _numeric(features.get(feature_name))
    default_left = bool(node.get("default_left", True))
    go_left = default_left if not _is_finite(value) else value <= threshold
    child_name = "left_child" if go_left else "right_child"
    if child_name not in node:
        raise ScannerRankerError(f"tree node missing {child_name}")
    return _eval_tree(node[child_name], feature_names, features)


def _active_symbol(qc: Any, ticker: str) -> Any | None:
    for symbol in getattr(qc, "_active", set()):
        if canonical_symbol_key(symbol) == ticker:
            return symbol
    return None


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
    if ichi is None or not bool(getattr(ichi, "is_ready", True)):
        return None
    return _current_value(getattr(ichi, name, None))


def _security_price(qc: Any, intent: Any, symbol: Any | None) -> float:
    securities = getattr(qc, "securities", {})
    for candidate in (symbol, getattr(intent, "ticker", None), canonical_symbol_key(getattr(intent, "ticker", ""))):
        if candidate is None:
            continue
        try:
            security = securities[candidate]
        except Exception:
            continue
        for attr in ("price", "close"):
            try:
                value = float(getattr(security, attr))
            except Exception:
                continue
            if value > 0.0:
                return value
    try:
        price = float(intent.price)
    except Exception:
        price = 0.0
    return price if price > 0.0 else 0.0


def _tbounce_float(tbounce: Any, attr: str) -> float | None:
    return None if tbounce is None else _optional_float(getattr(tbounce, attr, None))


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_float(value: Any, *, default: float) -> float:
    number = _optional_float(value)
    return number if number is not None else default


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    number = _optional_float(value)
    return number if number is not None else math.nan


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _pct_or_nan(fraction: float | None) -> float:
    return 100.0 * fraction if fraction is not None and math.isfinite(fraction) else math.nan


def _pct_distance(value: float | None, reference: float | None) -> float:
    if value is None or reference is None or reference <= 0.0:
        return math.nan
    return 100.0 * (value - reference) / reference


def _gt(left: float | None, right: float | None) -> bool:
    return left is not None and right is not None and left > right


def _gte(left: float | None, right: float) -> bool:
    return left is not None and left >= right


def _near(value: float | None, reference: float | None, pct: float) -> bool:
    distance = _pct_distance(value, reference)
    return math.isfinite(distance) and abs(distance) <= pct


def _breakout_volume(close: float | None, prior_high: float | None, rel_volume20: float | None) -> bool:
    return (
        close is not None
        and prior_high is not None
        and close > prior_high * 1.002
        and rel_volume20 is not None
        and rel_volume20 >= 1.2
    )


def _adx_rising_3(adx_window: Any) -> bool:
    try:
        return bool(adx_window.count >= 4 and float(adx_window[0]) > float(adx_window[3]))
    except Exception:
        return False


def _weekly_chikou_ok(w_close: Any) -> bool:
    try:
        return bool(w_close.count >= 27 and float(w_close[0]) > float(w_close[26]))
    except Exception:
        return False


def _trailing_dollar_volume(qc: Any, key: str) -> float:
    try:
        return float(_canon_map(getattr(qc, "_trailing_dv", {})).get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0
