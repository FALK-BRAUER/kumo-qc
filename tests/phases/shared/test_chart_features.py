"""Behavioral tests for QC-safe chart-curation helper formulas."""
from __future__ import annotations

from phases.shared.chart_features import (
    ChartCurationFeatures,
    ChartCurationInputs,
    build_chart_curation_features,
    george_qc_candidate_score,
)


def test_close_location_and_wicks_from_valid_daily_range() -> None:
    features = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=100.0,
            high=110.0,
            low=90.0,
            close=105.0,
        )
    )

    assert features.close_loc_in_range == 0.75
    assert features.upper_wick_ratio == 0.25
    assert features.lower_wick_ratio == 0.5
    assert features.body_ratio == 0.25


def test_zero_range_candle_produces_null_ratios_and_no_positive_flags() -> None:
    features = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            prior_high20=100.0,
            tenkan=99.0,
            kijun=95.0,
            cloud_top=94.0,
        )
    )

    assert features.close_loc_in_range is None
    assert features.upper_wick_ratio is None
    assert features.failed_rejection_candle is False
    assert features.constructive_resistance is False


def test_failed_rejection_near_prior_high_marks_bad_resistance() -> None:
    features = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=100.0,
            high=112.0,
            low=98.0,
            close=99.0,
            prior_high20=110.0,
            tenkan=96.0,
            kijun=94.0,
            cloud_top=93.0,
        )
    )

    assert features.near_resistance is True
    assert features.failed_rejection_candle is True
    assert features.bad_resistance is True
    assert features.constructive_resistance is False


def test_retest_prior_high_as_support_is_constructive_when_not_rejected() -> None:
    features = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=101.0,
            high=106.0,
            low=99.5,
            close=104.0,
            prior_high20=100.0,
            tenkan=101.0,
            kijun=96.0,
            cloud_top=95.0,
            rel_volume20=1.0,
        )
    )

    assert features.breakout_above_prior is True
    assert features.retest_prior_as_support is True
    assert features.constructive_resistance is True
    assert features.bad_resistance is False


def test_breakout_volume_confirmation_requires_relative_volume() -> None:
    without_volume = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=101.0,
            high=106.0,
            low=100.0,
            close=104.0,
            prior_high20=100.0,
            tenkan=101.0,
            kijun=96.0,
            cloud_top=95.0,
        )
    )
    with_volume = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=7,
            open=101.0,
            high=106.0,
            low=100.0,
            close=104.0,
            prior_high20=100.0,
            tenkan=101.0,
            kijun=96.0,
            cloud_top=95.0,
            rel_volume20=1.3,
        )
    )

    assert without_volume.breakout_above_prior is True
    assert without_volume.breakout_volume_confirmed is False
    assert with_volume.breakout_volume_confirmed is True


def test_missing_prior_high_windows_fail_conservative() -> None:
    features = build_chart_curation_features(
        ChartCurationInputs(
            bct_score=8,
            open=100.0,
            high=106.0,
            low=99.0,
            close=105.0,
            tenkan=101.0,
            kijun=98.0,
            cloud_top=97.0,
            rel_volume20=2.0,
        )
    )

    assert features.near_resistance is False
    assert features.breakout_above_prior is False
    assert features.breakout_volume_confirmed is False
    assert features.constructive_resistance is False


def test_no_chase_penalty_lowers_candidate_score() -> None:
    calm = ChartCurationFeatures(
        bct_score=8,
        close_loc_in_range=0.8,
        upper_wick_ratio=0.1,
        lower_wick_ratio=0.2,
        body_ratio=0.5,
        tenkan_extension_pct=0.02,
        kijun_extension_pct=0.06,
        cloud_distance_pct=0.05,
        price_above_tenkan=True,
        price_above_kijun=True,
        price_above_cloud=True,
        near_resistance=False,
        breakout_above_prior=False,
        breakout_volume_confirmed=False,
        resistance_rejection_today=False,
        failed_rejection_candle=False,
        bad_resistance=False,
        reclaim_after_touch=True,
        retest_prior_as_support=False,
        constructive_resistance=True,
        no_chase_risk=False,
    )
    chase = ChartCurationFeatures(
        bct_score=8,
        close_loc_in_range=0.8,
        upper_wick_ratio=0.1,
        lower_wick_ratio=0.2,
        body_ratio=0.5,
        tenkan_extension_pct=0.12,
        kijun_extension_pct=0.20,
        cloud_distance_pct=0.18,
        price_above_tenkan=True,
        price_above_kijun=True,
        price_above_cloud=True,
        near_resistance=False,
        breakout_above_prior=False,
        breakout_volume_confirmed=False,
        resistance_rejection_today=False,
        failed_rejection_candle=False,
        bad_resistance=False,
        reclaim_after_touch=True,
        retest_prior_as_support=False,
        constructive_resistance=True,
        no_chase_risk=True,
    )

    assert george_qc_candidate_score(calm) > george_qc_candidate_score(chase)
