"""Tests for the offline Massive/QC scanner substrate bridge."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sweeps.archive import massive_qc_bridge as B


def _row(
    date: str,
    symbol: str,
    *,
    included: bool = True,
    price_floor: bool = True,
    adv_rank: int = 100,
    score: int = 6,
) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "in_candidate_denominator": included,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.0,
        "volume": 1_000_000.0,
        "adv20_rank_price10": adv_rank,
        "day_dv_rank_price10": adv_rank,
        "price_floor": price_floor,
        "bct_score": score,
        "bct_rating": "++",
        "gap_pct": 1.0,
        "day_return_pct": 1.0,
        "d_price_above_cloud": True,
        "d_price_above_tenkan": True,
        "d_price_above_kijun": True,
    }


def _denominator() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("2026-02-12", "AAA", score=7, adv_rank=10),
            _row("2026-02-12", "BBB", score=6, adv_rank=20),
            _row("2026-02-12", "LOW", score=8, adv_rank=30, price_floor=False),
            _row("2026-02-12", "FAR", score=8, adv_rank=4000),
            _row("2026-02-12", "OUT", score=8, included=False),
            _row("2026-02-13", "CCC", score=5, adv_rank=40),
            _row("2026-02-14", "DDD", score=8, adv_rank=50),
        ]
    )


def test_build_bridge_panel_filters_topn_score_and_lanes() -> None:
    panel = B.build_bridge_panel(
        _denominator(),
        covered_dates={"2026-02-12", "2026-02-13"},
        config=B.BridgeConfig(top_n=3000, min_score=6),
    )

    assert list(panel["symbol"]) == ["AAA", "BBB"]
    assert list(panel["bct_candidate_lane"]) == ["bct_score_ge7", "almost_bct_score6"]
    assert set(panel["bridge_source"]) == {"massive_denominator"}


def test_no_min_score_bridge_captures_broad_top3000() -> None:
    panel = B.build_bridge_panel(
        _denominator(),
        covered_dates={"2026-02-12", "2026-02-13"},
        config=B.BridgeConfig(top_n=3000, min_score=None),
    )

    assert list(panel["symbol"]) == ["AAA", "BBB", "CCC"]
    assert panel.set_index("symbol").loc["CCC", "bct_candidate_lane"] == "below_bct_score6"


def test_run_bridge_summaries_and_label_coverage() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-12", "FAR"), ("2026-02-13", "CCC")]
    result = B.run_bridge(
        _denominator(),
        covered_dates={"2026-02-12", "2026-02-13"},
        labels=labels,
        config=B.BridgeConfig(top_n=3000, min_score=6),
    )
    summary = result.summary.iloc[0]
    coverage = result.label_coverage.iloc[0]

    assert summary["rows"] == 2
    assert summary["bct_ge7_rows"] == 1
    assert summary["score6_rows"] == 1
    assert coverage["labels"] == 3
    assert coverage["hits"] == 1
    assert coverage["recall_pct"] == 33.33


def test_write_result_creates_expected_csvs(tmp_path: Path) -> None:
    result = B.run_bridge(
        _denominator(),
        covered_dates={"2026-02-12"},
        labels=[("2026-02-12", "AAA")],
        config=B.BridgeConfig(top_n=3000, min_score=6),
    )
    B.write_result(result, tmp_path)

    assert (tmp_path / "candidate_panel.csv").is_file()
    assert (tmp_path / "summary.csv").is_file()
    assert (tmp_path / "daily_summary.csv").is_file()
    assert (tmp_path / "label_coverage.csv").is_file()
