"""Tests for the offline QC-safe George learned-ranker harness."""
from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from sweeps.archive import first_hour_confirmation as F
from sweeps.archive import george_learned_ranker as L


def _row(date: str, symbol: str, *, george_like: bool) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "in_candidate_denominator": True,
        "adv20_rank_price10": 100 if george_like else 800,
        "day_dv_rank_price10": 100 if george_like else 900,
        "bct_score": 7 if george_like else 6,
        "gap_pct": 1.0 if george_like else -1.0,
        "avg_volume20": 100_000.0,
        "prior_close": 99.0 if george_like else 101.0,
        "day_return_pct": 2.0 if george_like else -2.0,
        "intraday_return_pct": 1.0 if george_like else -1.0,
        "range_pct": 3.0,
        "daily_structure_score": 10.0 if george_like else 1.0,
        "d_price_above_cloud": george_like,
        "d_price_above_tenkan": george_like,
        "d_price_above_kijun": george_like,
        "d_tenkan_gt_kijun": george_like,
        "d_cloud_green": george_like,
        "d_price_above_ma200": True,
        "d_chikou_ok": george_like,
        "d_chikou_open_space": george_like,
        "d_close_above_prior20_high": george_like,
        "d_close_above_prior50_high": False,
        "d_tenkan_extension_pct": 2.0 if george_like else 9.0,
        "d_kijun_extension_pct": 4.0,
        "d_cloud_distance_pct": 4.0,
        "d_tk_spread_pct": 1.0,
        "d_near_prior20_high_within3": george_like,
        "d_near_prior50_high_within5": False,
        "d_near_prior252_high_within5": False,
        "d_distance_to_prior_high20_pct": 1.0,
        "d_distance_to_prior_high50_pct": 2.0,
        "d_distance_to_prior_high252_pct": 3.0,
        "d_recent_resistance_rejection_count20": 0,
        "d_breakout20_volume_confirmed": False,
        "d_breakout50_volume_confirmed": False,
        "d_breakout252_volume_confirmed": False,
        "d_no_chase_risk": not george_like,
        "d_bearish_reversal_candle": False,
        "d_shooting_star_like": False,
        "rel_volume20": 1.0,
        "d_volume_above_ma50": george_like,
        "d_volume_spike_150": False,
        "d_rel_volume50": 1.3 if george_like else 0.7,
        "d_resistance_rejection_today": False,
        "d_price_up_volume_down": False,
        "d_price_up_volume_below50": False,
        "d_return_5d_pct": 3.0 if george_like else -3.0,
        "d_return_10d_pct": 4.0 if george_like else -4.0,
        "d_return_20d_pct": 5.0 if george_like else -5.0,
        "d_body_pct_range": 0.6 if george_like else 0.2,
        "d_upper_wick_pct_range": 0.1 if george_like else 0.5,
        "d_lower_wick_pct_range": 0.2,
        "d_doji_or_spinning_top": False,
        "d_overextended_tenkan_3": False,
        "d_overextended_tenkan_5": False,
        "d_overextended_tenkan_10": False,
        "d_rapid_run_10d_15": False,
        "d_rapid_run_20d_30": False,
        "d_extension_reversal_warning": not george_like,
        "daily_breakout_quality_score": 5.0 if george_like else 0.0,
        "d_adx": 25.0,
        "d_plus_di": 30.0 if george_like else 10.0,
        "d_minus_di": 10.0 if george_like else 30.0,
        "d_adx_rising_3": george_like,
        "bct_c1_weekly_price_above_cloud": george_like,
        "bct_c2_weekly_tenkan_gt_kijun": george_like,
        "bct_c3_weekly_chikou_ok": george_like,
        "bct_c4_weekly_cloud_green": george_like,
        "bct_c5_daily_price_above_cloud": george_like,
        "bct_c6_daily_price_above_tenkan": george_like,
        "bct_c7_adx_confirmed": george_like,
        "bct_c8_daily_price_above_ma200": True,
        "w_price_above_cloud": george_like,
        "w_cloud_green": george_like,
        "w_tenkan_gt_kijun": george_like,
        "w_chikou_ok": george_like,
        "w_price_inside_cloud": False,
        "w_cloud_distance_pct": 3.0,
        "w_tenkan_extension_pct": 2.0,
        "resolved_sector": "Technology" if george_like else "Energy",
        "resolved_industry": "Software" if george_like else "Oil & Gas",
    }


def _denominator() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18")):
        rows.append(_row(date, f"P{i}", george_like=True))
        rows.append(_row(date, f"N{i}", george_like=False))
    return pd.DataFrame(rows)


def _write_minute_zip(
    minute_dir: Path,
    symbol: str,
    date: str,
    rows: list[tuple[int, float, float, float, float, int]],
) -> None:
    lean = symbol.lower()
    ymd = date.replace("-", "")
    target = minute_dir / lean
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    for ms, open_, high, low, close, volume in rows:
        lines.append(
            ",".join(
                [
                    str(ms),
                    str(int(open_ * F.PRICE_SCALE)),
                    str(int(high * F.PRICE_SCALE)),
                    str(int(low * F.PRICE_SCALE)),
                    str(int(close * F.PRICE_SCALE)),
                    str(volume),
                ]
            )
        )
    with zipfile.ZipFile(target / f"{ymd}_trade.zip", "w") as zf:
        zf.writestr(f"{ymd}_{lean}_minute_trade.csv", "\n".join(lines) + "\n")


def test_make_date_folds_are_grouped_and_chronological() -> None:
    folds = L.make_date_folds(["2026-02-13", "2026-02-12", "2026-02-18", "2026-02-17"], n_folds=2)
    assert folds == [{"2026-02-12", "2026-02-13"}, {"2026-02-17", "2026-02-18"}]


def test_feature_matrix_is_finite_with_missing_columns() -> None:
    x, names = L.build_feature_matrix(pd.DataFrame([{"date": "2026-02-12", "symbol": "AAA"}]))
    assert x.shape[0] == 1
    assert x.shape[1] == len(names)
    assert np.isfinite(L.apply_standardizer(x, L.fit_standardizer(x))).all()


def test_denominator_rank_features_are_computed_by_date() -> None:
    panel = pd.DataFrame(
        [
            {"date": "2026-02-12", "symbol": "A", "gap_pct": 3.0, "bct_score": 7},
            {"date": "2026-02-12", "symbol": "B", "gap_pct": 1.0, "bct_score": 6},
            {"date": "2026-02-13", "symbol": "C", "gap_pct": 2.0, "bct_score": 8},
        ]
    )

    ranked = L.add_denominator_rank_features(panel)

    by_symbol = ranked.set_index("symbol")
    assert by_symbol.loc["A", "gap_pct_rank_in_panel"] == 1.0
    assert by_symbol.loc["B", "gap_pct_rank_in_panel"] == 2.0
    assert by_symbol.loc["A", "gap_pct_pctile_in_panel"] == 1.0
    assert by_symbol.loc["B", "gap_pct_pctile_in_panel"] == 0.5
    assert by_symbol.loc["C", "gap_pct_rank_in_panel"] == 1.0


def test_feature_matrix_can_include_denominator_rank_features() -> None:
    ranked = L.add_denominator_rank_features(_denominator())
    x, names = L.build_feature_matrix(ranked, include_denominator_ranks=True)

    assert x.shape[0] == len(ranked)
    assert "gap_pct_rank_in_panel" in names
    assert "daily_structure_score_pctile_in_panel" in names
    assert "day_dollar_vol_rank_in_panel" in names


def test_logistic_ridge_learns_separable_signal() -> None:
    x = np.array([[3.0], [2.0], [-2.0], [-3.0]])
    y = np.array([1.0, 1.0, 0.0, 0.0])
    model = L.fit_logistic_ridge(x, y, max_iter=300, learning_rate=0.1, l2=0.001)
    scores = L.predict_logit(model, x)
    assert scores[:2].mean() > scores[2:].mean()


def test_pairwise_ranker_learns_same_date_ordering() -> None:
    x = np.array([[3.0], [-2.0], [2.0], [-3.0]])
    y = np.array([1.0, 0.0, 1.0, 0.0])
    dates = ["2026-02-12", "2026-02-12", "2026-02-13", "2026-02-13"]
    model = L.fit_pairwise_linear_ranker(
        x,
        y,
        dates,
        max_iter=300,
        learning_rate=0.1,
        l2=0.001,
        negatives_per_positive=3,
    )
    scores = L.predict_logit(model, x)
    assert scores[0] > scores[1]
    assert scores[2] > scores[3]


def test_run_learned_ranker_reports_oof_topk() -> None:
    labels = [(date, f"P{i}") for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18"))]
    result = L.run_learned_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=L.LearnedRankerConfig(n_folds=2, max_iter=250, learning_rate=0.1, l2=0.001, ks=(1, 2)),
    )
    learned = result.rank_summary.set_index("variant").loc["learned_oof_all"]

    assert learned["hits1"] == 4
    assert learned["recall1_pct"] == 100.0
    assert len(result.fold_summary) == 2
    assert not result.coefficient_summary.empty


def test_run_learned_ranker_reports_pairwise_oof_topk() -> None:
    labels = [(date, f"P{i}") for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18"))]
    result = L.run_learned_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=L.LearnedRankerConfig(
            n_folds=2,
            model_type="pairwise",
            max_iter=250,
            learning_rate=0.1,
            l2=0.001,
            pairwise_negatives_per_positive=2,
            ks=(1, 2),
        ),
    )
    learned = result.rank_summary.set_index("variant").loc["learned_oof_pairwise_all"]

    assert learned["hits1"] == 4
    assert learned["recall1_pct"] == 100.0


def test_run_learned_ranker_can_include_first_hour_features(tmp_path: Path) -> None:
    dates = ("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18")
    labels = [(date, f"P{i}") for i, date in enumerate(dates)]
    for i, date in enumerate(dates):
        _write_minute_zip(
            tmp_path,
            f"P{i}",
            date,
            [
                (34_200_000, 100.0, 101.0, 99.5, 100.5, 6_000),
                (34_500_000, 100.5, 102.0, 100.0, 101.5, 6_000),
            ],
        )
    result = L.run_learned_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=L.LearnedRankerConfig(
            n_folds=2,
            model_type="pairwise",
            max_iter=250,
            learning_rate=0.1,
            l2=0.001,
            pairwise_negatives_per_positive=2,
            use_first_hour=True,
            first_hour_minute_dir=tmp_path,
            ks=(1, 2),
        ),
    )
    learned = result.rank_summary.set_index("variant").loc["learned_oof_pairwise_first_hour_all"]
    features = set(result.coefficient_summary["feature"])

    assert learned["hits1"] == 4
    assert "intraday_available" in features
    assert "fh_return_pct" in features
    assert "fh_confirm_basic" in features


def test_run_learned_ranker_can_include_sector_context_features() -> None:
    labels = [(date, f"P{i}") for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18"))]
    result = L.run_learned_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=L.LearnedRankerConfig(
            n_folds=2,
            max_iter=250,
            learning_rate=0.1,
            l2=0.001,
            use_sector_context=True,
            ks=(1, 2),
        ),
    )
    learned = result.rank_summary.set_index("variant").loc["learned_oof_sector_context_all"]
    features = set(result.coefficient_summary["feature"])

    assert learned["hits1"] == 4
    assert "sector_rank" in features
    assert "industry_rank_in_sector" in features
    assert "hierarchy_all_stage_pass" in features


def test_run_learned_ranker_can_include_denominator_rank_features() -> None:
    labels = [(date, f"P{i}") for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18"))]
    result = L.run_learned_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=L.LearnedRankerConfig(
            n_folds=2,
            model_type="pairwise",
            max_iter=250,
            learning_rate=0.1,
            l2=0.001,
            pairwise_negatives_per_positive=2,
            use_denominator_ranks=True,
            ks=(1, 2),
        ),
    )
    learned = result.rank_summary.set_index("variant").loc["learned_oof_pairwise_denominator_ranks_all"]
    features = set(result.coefficient_summary["feature"])

    assert learned["hits1"] == 4
    assert "gap_pct_rank_in_panel" in features
    assert "bct_score_pctile_in_panel" in features
