"""Tests for the offline George/BCT top-K audit harness."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from sweeps.archive import george_topk_audit as A


def _row(
    date: str,
    symbol: str,
    *,
    included: bool = True,
    adv_rank: int = 100,
    day_dv_rank: int = 100,
    bct_score: int = 6,
    clean: bool = True,
    daily_structure: float = 6.0,
) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "in_candidate_denominator": included,
        "adv20_rank_price10": adv_rank,
        "day_dv_rank_price10": day_dv_rank,
        "bct_score": bct_score,
        "gap_pct": 1.0,
        "day_return_pct": 1.5,
        "intraday_return_pct": 1.0,
        "range_pct": 3.0,
        "daily_structure_score": daily_structure,
        "d_price_above_cloud": clean,
        "d_price_above_tenkan": clean,
        "d_price_above_kijun": clean,
        "d_tenkan_extension_pct": 2.0 if clean else 9.0,
        "d_kijun_extension_pct": 4.0,
        "d_cloud_distance_pct": 5.0,
        "d_near_prior20_high_within3": clean,
        "d_near_prior50_high_within5": False,
        "d_near_prior252_high_within5": False,
        "d_breakout20_volume_confirmed": False,
        "d_breakout50_volume_confirmed": False,
        "d_breakout252_volume_confirmed": False,
        "d_no_chase_risk": not clean,
        "d_bearish_reversal_candle": False,
        "d_shooting_star_like": False,
        "rel_volume20": 1.0,
        "w_price_above_cloud": True,
    }


def _denominator() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("2026-02-12", "AAA", bct_score=6, clean=True, daily_structure=10.0),
            _row("2026-02-12", "BBB", bct_score=7, clean=False, daily_structure=9.0),
            _row("2026-02-12", "LOW", bct_score=5, clean=True),
            _row("2026-02-12", "FAR", bct_score=8, clean=True, adv_rank=4000),
            _row("2026-02-12", "OUT", included=False, bct_score=8, clean=True),
            _row("2026-02-13", "CCC", bct_score=6, clean=True, daily_structure=8.0),
            _row("2026-02-13", "DDD", bct_score=7, clean=True, daily_structure=7.0),
            _row("2026-02-14", "LATE", bct_score=8, clean=True),
        ]
    )


def test_build_score6_panel_filters_and_stamps_labels() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-13", "CCC"), ("2026-02-14", "LATE")]
    panel = A.build_score6_panel(
        _denominator(),
        labels,
        covered_dates={"2026-02-12", "2026-02-13"},
        config=A.AuditConfig(top_n=3000, min_score=6),
    )

    assert list(panel["symbol"]) == ["AAA", "BBB", "CCC", "DDD"]
    assert int(panel["is_george"].sum()) == 2
    assert set(panel.loc[panel["is_george"], "symbol"]) == {"AAA", "CCC"}


def test_base_and_gate_summaries_measure_pool_recall_precision() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-13", "CCC")]
    panel = A.build_score6_panel(
        _denominator(),
        labels,
        covered_dates={"2026-02-12", "2026-02-13"},
    )
    base = A.summarize_base_panel(panel, label_count=len(labels)).iloc[0]
    gates = A.summarize_gates(panel, A.default_gates(panel), label_count=len(labels))
    clean_top2000 = gates.set_index("name").loc["clean_top2000"]
    score6_clean_all = gates.set_index("name").loc["score6_clean_all"]

    assert base["rows"] == 4
    assert base["hits"] == 2
    assert base["recall_pct"] == 100.0
    assert clean_top2000["rows"] == 3
    assert clean_top2000["hits"] == 2
    assert clean_top2000["precision_pct"] == pytest.approx(66.667)
    assert score6_clean_all["rows"] == 2
    assert score6_clean_all["hits"] == 2


def test_rank_variant_reports_hits_at_k() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-13", "CCC")]
    panel = A.build_score6_panel(
        _denominator(),
        labels,
        covered_dates={"2026-02-12", "2026-02-13"},
    )
    all_rows = pd.Series(True, index=panel.index)
    score = pd.to_numeric(panel["daily_structure_score"])
    ranks = A.evaluate_rank_variants(
        panel,
        {"daily_structure": (all_rows, score)},
        label_count=len(labels),
        ks=(1, 2),
    ).iloc[0]

    assert ranks["hits1"] == 2
    assert ranks["recall1_pct"] == 100.0
    assert ranks["precision1_pct"] == 100.0
    assert ranks["hits2"] == 2
    assert ranks["median_george_rank"] == 1.0
    assert ranks["map_seen_pct"] == 100.0
    assert ranks["ndcg1_seen_pct"] == 100.0
    assert ranks["ndcg2_seen_pct"] == 100.0


def test_rank_failure_examples_show_dates_with_topk_miss() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-13", "CCC")]
    panel = A.build_score6_panel(
        _denominator(),
        labels,
        covered_dates={"2026-02-12", "2026-02-13"},
    )
    all_rows = pd.Series(True, index=panel.index)
    score = pd.to_numeric(panel["bct_score"])

    failures = A.rank_failure_examples(
        panel,
        {"bct_score": (all_rows, score)},
        k=1,
        limit_per_variant=2,
    )

    assert set(failures["date"]) == {"2026-02-12", "2026-02-13"}
    assert set(failures["george_symbols"]) == {"AAA@2", "CCC@2"}
    assert set(failures["top_symbols"]) == {"BBB", "DDD"}


def test_run_topk_audit_returns_all_tables() -> None:
    labels = [("2026-02-12", "AAA"), ("2026-02-13", "CCC")]
    result = A.run_topk_audit(
        _denominator(),
        labels,
        covered_dates={"2026-02-12", "2026-02-13"},
        config=A.AuditConfig(ks=(1, 2)),
    )

    assert not result.base_summary.empty
    assert "clean_top2000" in set(result.gate_summary["name"])
    assert "base__daily_structure_rank" in set(result.rank_summary["variant"])
    assert set(result.failure_examples.columns) == {
        "variant",
        "date",
        "k",
        "seen_george_count",
        "best_george_rank",
        "george_symbols",
        "top_symbols",
    }


def test_covered_dates_from_coarse_fails_loudly_on_empty_cache(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no coarse dates found"):
        A.covered_dates_from_coarse(2026, tmp_path / "missing-coarse")
