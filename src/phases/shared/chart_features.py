"""Pure chart-curation features for QC-safe BCT scanner ranking.

These helpers encode chart state only: completed daily OHLC, maintained daily Ichimoku,
ADX/ROC, optional relative-volume, and optional prior-high windows. They do not read files,
George/BCT evidence, OCR labels, transcripts, or learned model scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


def _finite(value: float | None) -> bool:
    return value is not None and isfinite(value)


def _positive(value: float | None) -> bool:
    return _finite(value) and value is not None and value > 0.0


def _pct_distance(value: float | None, reference: float | None) -> float | None:
    if not (_finite(value) and _positive(reference)):
        return None
    assert value is not None
    assert reference is not None
    return (value - reference) / reference


def _in_band(value: float | None, *, low: float, high: float) -> bool:
    return _finite(value) and value is not None and low <= value <= high


def _any_true(values: tuple[bool, ...]) -> bool:
    return any(values)


@dataclass(frozen=True, slots=True)
class ChartCurationInputs:
    bct_score: int
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    tenkan: float | None = None
    kijun: float | None = None
    cloud_top: float | None = None
    cloud_bottom: float | None = None
    adx: float | None = None
    roc13: float | None = None
    rel_volume20: float | None = None
    prior_high20: float | None = None
    prior_high50: float | None = None
    prior_high252: float | None = None
    recent_resistance_rejection_count20: int = 0


@dataclass(frozen=True, slots=True)
class ChartCurationFeatures:
    bct_score: int
    close_loc_in_range: float | None
    upper_wick_ratio: float | None
    lower_wick_ratio: float | None
    body_ratio: float | None
    tenkan_extension_pct: float | None
    kijun_extension_pct: float | None
    cloud_distance_pct: float | None
    price_above_tenkan: bool
    price_above_kijun: bool
    price_above_cloud: bool
    near_resistance: bool
    breakout_above_prior: bool
    breakout_volume_confirmed: bool
    resistance_rejection_today: bool
    failed_rejection_candle: bool
    bad_resistance: bool
    reclaim_after_touch: bool
    retest_prior_as_support: bool
    constructive_resistance: bool
    no_chase_risk: bool


def _nearest_prior_high(inputs: ChartCurationInputs) -> float | None:
    levels: list[float] = []
    for level in (inputs.prior_high20, inputs.prior_high50, inputs.prior_high252):
        if _positive(level) and level is not None:
            levels.append(level)
    if not levels:
        return None
    return min(levels, key=lambda level: abs(inputs.close - level))


def build_chart_curation_features(
    inputs: ChartCurationInputs,
    *,
    near_resistance_pct: float = 0.03,
    breakout_pct: float = 0.002,
    retest_pct: float = 0.01,
    volume_confirm_threshold: float = 1.2,
) -> ChartCurationFeatures:
    """Compute QC-safe chart-curation flags from point-in-time inputs.

    Missing data is conservative: optional windows that are absent produce false chart flags,
    never inferred positives.
    """
    open_ = inputs.open
    high = inputs.high
    low = inputs.low
    close = inputs.close

    candle_range: float | None = None
    if _finite(high) and _finite(low) and high is not None and low is not None:
        candle_range = high - low
    valid_range = candle_range is not None and candle_range > 0.0
    close_loc: float | None = None
    upper_wick: float | None = None
    lower_wick: float | None = None
    body_ratio: float | None = None
    if valid_range and candle_range is not None:
        if low is not None:
            close_loc = (close - low) / candle_range
        if high is not None and open_ is not None:
            upper_wick = (high - max(open_, close)) / candle_range
        if low is not None and open_ is not None:
            lower_wick = (min(open_, close) - low) / candle_range
        if open_ is not None:
            body_ratio = abs(close - open_) / candle_range

    tenkan_extension = _pct_distance(close, inputs.tenkan)
    kijun_extension = _pct_distance(close, inputs.kijun)
    cloud_distance = _pct_distance(close, inputs.cloud_top)
    price_above_tenkan = _finite(inputs.tenkan) and inputs.tenkan is not None and close > inputs.tenkan
    price_above_kijun = _finite(inputs.kijun) and inputs.kijun is not None and close > inputs.kijun
    price_above_cloud = _finite(inputs.cloud_top) and inputs.cloud_top is not None and close > inputs.cloud_top

    resistance = _nearest_prior_high(inputs)
    resistance_distance = _pct_distance(close, resistance)
    high_touched_resistance = (
        resistance is not None
        and high is not None
        and _finite(high)
        and high >= resistance * (1.0 - near_resistance_pct)
    )
    close_near_resistance = (
        resistance_distance is not None
        and abs(resistance_distance) <= near_resistance_pct
    )
    near_resistance = close_near_resistance or high_touched_resistance
    breakout_above_prior = (
        resistance is not None
        and close > resistance * (1.0 + breakout_pct)
    )
    breakout_volume_confirmed = (
        breakout_above_prior
        and _finite(inputs.rel_volume20)
        and inputs.rel_volume20 is not None
        and inputs.rel_volume20 >= volume_confirm_threshold
    )

    weak_close = _in_band(close_loc, low=0.0, high=0.45)
    heavy_upper_wick = _in_band(upper_wick, low=0.35, high=1.0)
    resistance_rejection_today = high_touched_resistance and heavy_upper_wick and weak_close
    failed_rejection_candle = near_resistance and _in_band(upper_wick, low=0.40, high=1.0) and weak_close
    bad_resistance = (
        resistance_rejection_today
        or failed_rejection_candle
        or inputs.recent_resistance_rejection_count20 >= 4
    )

    no_chase_risk = _any_true(
        (
            _finite(tenkan_extension) and tenkan_extension is not None and tenkan_extension > 0.08,
            _finite(kijun_extension) and kijun_extension is not None and kijun_extension > 0.14,
            _finite(inputs.roc13) and inputs.roc13 is not None and inputs.roc13 > 0.25,
        )
    )

    touched_tenkan = (
        inputs.tenkan is not None
        and _positive(inputs.tenkan)
        and low is not None
        and _finite(low)
        and low <= inputs.tenkan * 1.005
    )
    reclaim_after_touch = (
        touched_tenkan
        and price_above_tenkan
        and price_above_kijun
        and _in_band(close_loc, low=0.55, high=1.0)
        and not no_chase_risk
    )

    retest_prior_as_support = (
        valid_range
        and resistance is not None
        and low is not None
        and _finite(low)
        and low <= resistance * (1.0 + retest_pct)
        and close >= resistance * (1.0 - retest_pct)
        and price_above_kijun
        and (price_above_cloud or inputs.cloud_top is None)
        and not bad_resistance
    )

    constructive_resistance = (
        (near_resistance or breakout_above_prior)
        and not bad_resistance
        and (
            breakout_volume_confirmed
            or reclaim_after_touch
            or retest_prior_as_support
            or (price_above_cloud and _in_band(close_loc, low=0.65, high=1.0))
        )
    )

    return ChartCurationFeatures(
        bct_score=inputs.bct_score,
        close_loc_in_range=close_loc,
        upper_wick_ratio=upper_wick,
        lower_wick_ratio=lower_wick,
        body_ratio=body_ratio,
        tenkan_extension_pct=tenkan_extension,
        kijun_extension_pct=kijun_extension,
        cloud_distance_pct=cloud_distance,
        price_above_tenkan=price_above_tenkan,
        price_above_kijun=price_above_kijun,
        price_above_cloud=price_above_cloud,
        near_resistance=near_resistance,
        breakout_above_prior=breakout_above_prior,
        breakout_volume_confirmed=breakout_volume_confirmed,
        resistance_rejection_today=resistance_rejection_today,
        failed_rejection_candle=failed_rejection_candle,
        bad_resistance=bad_resistance,
        reclaim_after_touch=reclaim_after_touch,
        retest_prior_as_support=retest_prior_as_support,
        constructive_resistance=constructive_resistance,
        no_chase_risk=no_chase_risk,
    )


def george_qc_candidate_score(features: ChartCurationFeatures) -> float:
    """Fixed QC-safe candidate score used by the opt-in George-style ranking phase."""
    score = float(features.bct_score)
    if features.bct_score >= 8:
        score += 1.0
    elif features.bct_score >= 7:
        score += 0.5

    if features.constructive_resistance:
        score += 2.0
    if features.reclaim_after_touch:
        score += 1.25
    if features.retest_prior_as_support:
        score += 1.25
    if features.breakout_volume_confirmed:
        score += 1.0
    if features.price_above_tenkan:
        score += 0.45
    if features.price_above_kijun:
        score += 0.45
    if features.price_above_cloud:
        score += 0.35
    if _in_band(features.tenkan_extension_pct, low=0.0, high=0.05):
        score += 0.75
    if _in_band(features.kijun_extension_pct, low=0.0, high=0.10):
        score += 0.35
    if _in_band(features.cloud_distance_pct, low=0.0, high=0.08):
        score += 0.30

    if features.bad_resistance:
        score -= 2.0
    if features.no_chase_risk:
        score -= 2.0
    return score
