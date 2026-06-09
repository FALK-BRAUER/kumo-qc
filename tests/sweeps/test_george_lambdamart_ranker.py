"""Tests for the optional LightGBM LambdaMART scanner benchmark."""
from __future__ import annotations

import pytest
import numpy as np
import pandas as pd

from sweeps.archive import george_lambdamart_ranker as M


def _row(date: str, symbol: str, *, george_like: bool) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "in_candidate_denominator": True,
        "adv20_rank_price10": 100 if george_like else 900,
        "day_dv_rank_price10": 100 if george_like else 900,
        "bct_score": 7 if george_like else 6,
        "gap_pct": 2.0 if george_like else -1.0,
        "day_return_pct": 3.0 if george_like else -2.0,
        "intraday_return_pct": 1.0 if george_like else -1.0,
        "range_pct": 3.0,
        "daily_structure_score": 8.0 if george_like else 2.0,
        "d_price_above_cloud": george_like,
        "d_price_above_tenkan": george_like,
        "d_price_above_kijun": george_like,
        "d_tenkan_gt_kijun": george_like,
        "d_tenkan_extension_pct": 2.0,
        "d_kijun_extension_pct": 3.0,
        "d_cloud_distance_pct": 4.0,
        "d_no_chase_risk": not george_like,
        "d_bearish_reversal_candle": False,
        "d_shooting_star_like": False,
        "rel_volume20": 1.3 if george_like else 0.7,
        "w_price_above_cloud": george_like,
    }


def _denominator() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18")):
        rows.append(_row(date, f"P{i}", george_like=True))
        rows.append(_row(date, f"N{i}", george_like=False))
    return pd.DataFrame(rows)


def test_sort_by_date_groups_returns_group_sizes() -> None:
    x = np.array([[1.0], [2.0], [3.0], [4.0]])
    y = np.array([0.0, 1.0, 0.0, 1.0])

    sorted_x, sorted_y, groups = M.sort_by_date_groups(
        x,
        y,
        ["2026-02-13", "2026-02-12", "2026-02-13", "2026-02-12"],
    )

    assert groups == [2, 2]
    assert sorted_x[:, 0].tolist() == [2.0, 4.0, 1.0, 3.0]
    assert sorted_y.tolist() == [1.0, 1.0, 0.0, 0.0]


def test_run_lambdamart_ranker_smoke_when_lightgbm_available() -> None:
    try:
        M._import_lightgbm()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    labels = [(date, f"P{i}") for i, date in enumerate(("2026-02-12", "2026-02-13", "2026-02-17", "2026-02-18"))]

    result = M.run_lambdamart_ranker(
        _denominator(),
        labels,
        covered_dates={date for date, _symbol in labels},
        config=M.LambdaMARTConfig(
            n_folds=2,
            n_estimators=10,
            num_leaves=7,
            min_child_samples=1,
            use_sector_context=False,
            use_denominator_ranks=True,
            use_sector_breadth=False,
            ks=(1, 2),
        ),
    )

    learned = result.rank_summary.set_index("variant").loc["lambdamart_denominator_ranks_all"]
    assert learned["hits1"] >= 1
    assert not result.importance_summary.empty
