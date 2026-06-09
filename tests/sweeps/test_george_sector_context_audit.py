"""Tests for the offline George sector/industry context audit."""
from __future__ import annotations

import pandas as pd

from sweeps.archive import george_sector_context_audit as S
from sweeps.archive import george_topk_audit as topk


def _row(
    date: str,
    symbol: str,
    *,
    sector: str,
    industry: str,
    good: bool,
    bct_score: int = 6,
    daily_structure: float = 5.0,
    adv_rank: int = 100,
) -> dict[str, object]:
    return {
        "date": date,
        "symbol": symbol,
        "in_candidate_denominator": True,
        "adv20_rank_price10": adv_rank,
        "day_dv_rank_price10": adv_rank,
        "bct_score": bct_score,
        "gap_pct": 1.0,
        "day_return_pct": 2.0 if good else -1.0,
        "intraday_return_pct": 1.0 if good else -1.0,
        "range_pct": 3.0,
        "daily_structure_score": daily_structure,
        "resolved_sector": sector,
        "resolved_industry": industry,
        "w_price_above_cloud": good,
        "w_tenkan_gt_kijun": good,
        "w_cloud_green": good,
        "w_chikou_ok": good,
        "w_price_inside_cloud": False,
        "w_tenkan_extension_pct": 2.0,
        "d_price_above_cloud": good,
        "d_price_above_tenkan": good,
        "d_price_above_kijun": good,
        "d_tenkan_gt_kijun": good,
        "d_cloud_green": good,
        "d_chikou_open_space": good,
        "d_tenkan_extension_pct": 2.0 if good else 9.0,
        "d_kijun_extension_pct": 3.0,
        "d_near_prior20_high_within3": good,
        "d_near_prior50_high_within5": False,
        "d_close_above_prior20_high": good,
        "d_close_above_prior50_high": False,
        "d_breakout20_volume_confirmed": good,
        "d_breakout50_volume_confirmed": False,
        "d_volume_above_ma50": good,
        "d_volume_spike_150": False,
        "d_rel_volume50": 1.4 if good else 0.8,
        "d_resistance_rejection_today": False,
        "d_bearish_reversal_candle": False,
        "d_shooting_star_like": False,
        "d_no_chase_risk": not good,
        "rel_volume20": 1.2 if good else 0.8,
    }


def _denominator() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(
                "2026-02-12",
                "AAA",
                sector="Technology",
                industry="Software",
                good=True,
                bct_score=7,
                daily_structure=10.0,
            ),
            _row(
                "2026-02-12",
                "BBB",
                sector="Technology",
                industry="Software",
                good=True,
                bct_score=6,
                daily_structure=7.0,
            ),
            _row(
                "2026-02-12",
                "CCC",
                sector="Energy",
                industry="Oil",
                good=False,
                bct_score=6,
                daily_structure=2.0,
            ),
            _row(
                "2026-02-12",
                "DDD",
                sector="Financial Services",
                industry="Banks",
                good=False,
                bct_score=6,
                daily_structure=1.0,
            ),
        ]
    )


def test_add_sector_context_ranks_sector_industry_and_stock() -> None:
    panel = topk.build_score6_panel(
        _denominator(),
        [("2026-02-12", "AAA")],
        covered_dates={"2026-02-12"},
    )
    scored = S.add_stock_context_features(panel)
    enriched, sectors, industries = S.add_sector_industry_context(scored)

    aaa = enriched.set_index("symbol").loc["AAA"]
    tech = sectors.set_index("resolved_sector").loc["Technology"]
    software = industries.set_index("resolved_industry").loc["Software"]

    assert tech["sector_rank"] == 1.0
    assert software["industry_rank_in_sector"] == 1.0
    assert aaa["stock_rank_in_industry_base"] == 1.0
    assert bool(aaa["hierarchy_all_stage_pass"]) is True


def test_run_sector_context_audit_reports_stage_and_rank_tables() -> None:
    result = S.run_sector_context_audit(
        _denominator(),
        [("2026-02-12", "AAA")],
        covered_dates={"2026-02-12"},
        config=topk.AuditConfig(ks=(1, 2)),
    )
    stage = result.stage_summary.set_index(["stage", "threshold"])
    ranks = result.rank_summary.set_index("variant")

    assert result.base_summary.iloc[0]["hits"] == 1
    assert stage.loc[("label_coverage", "in_score6_panel"), "recall_pct"] == 100.0
    assert stage.loc[("profile_coverage", "sector_profile"), "recall_pct"] == 100.0
    assert stage.loc[("sector", "top1"), "hits"] == 1
    assert stage.loc[("industry_in_sector", "top1"), "hits"] == 1
    assert stage.loc[("stock_in_industry", "top1"), "hits"] == 1
    assert ranks.loc["base_stock_score", "hits1"] == 1
    assert ranks.loc["sector_context_score", "hits1"] == 1
