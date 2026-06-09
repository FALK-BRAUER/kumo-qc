"""Offline sector/industry context audit for George/BCT scanner alignment.

This research helper approximates George's sector -> industry -> stock drill-down from the
profiled Massive denominator. It derives dynamic sector and industry strength from same-day
stock-level weekly/daily chart features, then measures whether that context helps explain George
OCR scanner rows. Runtime strategy code must not import it.
"""
from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from sweeps.archive import george_topk_audit as topk


PROFILE_USECOLS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *topk.DENOMINATOR_USECOLS,
            "resolved_sector",
            "resolved_industry",
            "has_sector_profile",
            "has_industry_profile",
            "w_tenkan_gt_kijun",
            "w_cloud_green",
            "w_chikou_ok",
            "w_price_inside_cloud",
            "w_tenkan_extension_pct",
            "d_cloud_green",
            "d_chikou_open_space",
            "d_close_above_prior20_high",
            "d_close_above_prior50_high",
            "d_volume_above_ma50",
            "d_volume_spike_150",
            "d_rel_volume50",
            "d_resistance_rejection_today",
        )
    )
)


@dataclass(frozen=True, slots=True)
class SectorContextResult:
    """In-memory result tables from the sector/industry context audit."""

    base_summary: pd.DataFrame
    stage_summary: pd.DataFrame
    rank_summary: pd.DataFrame
    sector_summary: pd.DataFrame
    industry_summary: pd.DataFrame
    panel: pd.DataFrame


def load_profiled_denominator(path: Path) -> pd.DataFrame:
    """Load the profiled Massive denominator columns used by this audit."""
    header = list(pd.read_csv(path, nrows=0).columns)
    missing = [col for col in ("date", "symbol", "in_candidate_denominator", "adv20_rank_price10", "bct_score") if col not in header]
    if missing:
        raise ValueError(f"profiled denominator missing required columns: {missing}")
    usecols = [col for col in PROFILE_USECOLS if col in header]
    return pd.read_csv(path, usecols=usecols, low_memory=False)


def _norm_text(series: pd.Series | None, index: pd.Index) -> pd.Series:
    if series is None:
        return pd.Series("", index=index, dtype=str)
    return series.fillna("").astype(str).str.strip()


def _pct(part: int | float, total: int | float) -> float:
    return round(100.0 * float(part) / float(total), 2) if total else 0.0


def _safe_log1p(value: float) -> float:
    return math.log1p(max(0.0, float(value)))


def add_stock_context_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Attach profile-normalized stock-level proxy features used for hierarchy scoring."""
    out = panel.copy()
    out["resolved_sector"] = _norm_text(out.get("resolved_sector"), out.index)
    out["resolved_industry"] = _norm_text(out.get("resolved_industry"), out.index)
    out["has_sector_profile"] = out["resolved_sector"].ne("")
    out["has_industry_profile"] = out["resolved_industry"].ne("")

    bct_score = topk._num_col(out, "bct_score", default=0.0)
    out["bct6"] = bct_score >= 6.0
    out["bct7"] = bct_score >= 7.0
    out["weekly_good"] = (
        topk._bool_col(out, "w_price_above_cloud")
        & topk._bool_col(out, "w_tenkan_gt_kijun")
        & topk._bool_col(out, "w_cloud_green")
    )
    out["weekly_strong"] = out["weekly_good"] & topk._bool_col(out, "w_chikou_ok")
    out["weekly_recovering"] = topk._bool_col(out, "w_price_inside_cloud") | (
        topk._bool_col(out, "w_price_above_cloud")
        & topk._num_col(out, "w_tenkan_extension_pct").between(-1.5, 8.0, inclusive="both")
    )
    out["daily_good"] = (
        topk._bool_col(out, "d_price_above_cloud")
        & topk._bool_col(out, "d_price_above_tenkan")
        & (topk._bool_col(out, "d_price_above_kijun") | topk._bool_col(out, "d_tenkan_gt_kijun"))
    )
    out["daily_strong"] = (
        out["daily_good"]
        & topk._bool_col(out, "d_cloud_green")
        & topk._bool_col(out, "d_chikou_open_space")
    )
    out["daily_support_hold"] = (
        topk._num_col(out, "d_tenkan_extension_pct").between(-1.0, 4.0, inclusive="both")
        | topk._num_col(out, "d_kijun_extension_pct").between(-1.5, 5.0, inclusive="both")
    ) & topk._bool_col(out, "d_price_above_cloud")
    out["daily_breakout"] = (
        topk._bool_col(out, "d_near_prior20_high_within3")
        | topk._bool_col(out, "d_near_prior50_high_within5")
        | topk._bool_col(out, "d_close_above_prior20_high")
        | topk._bool_col(out, "d_close_above_prior50_high")
        | topk._bool_col(out, "d_breakout20_volume_confirmed")
        | topk._bool_col(out, "d_breakout50_volume_confirmed")
    )
    rel_volume = topk._num_col(out, "d_rel_volume50")
    rel_volume = rel_volume.fillna(topk._num_col(out, "rel_volume20", default=0.0))
    out["volume_confirmed"] = (
        topk._bool_col(out, "d_volume_above_ma50")
        | topk._bool_col(out, "d_volume_spike_150")
        | (rel_volume >= 1.2)
    )
    out["positive_day"] = topk._num_col(out, "day_return_pct", default=0.0) > 0.0
    out["bad_reversal"] = (
        topk._bool_col(out, "d_resistance_rejection_today")
        | topk._bool_col(out, "d_bearish_reversal_candle")
        | topk._bool_col(out, "d_shooting_star_like")
    )
    out["no_chase_pass"] = ~topk._bool_col(out, "d_no_chase_risk")
    out["stock_chart_score"] = (
        1.15 * out["weekly_good"].astype(float)
        + 0.65 * out["weekly_strong"].astype(float)
        + 0.95 * out["daily_good"].astype(float)
        + 0.55 * out["daily_strong"].astype(float)
        + 0.55 * out["daily_support_hold"].astype(float)
        + 0.45 * out["daily_breakout"].astype(float)
        + 0.35 * out["volume_confirmed"].astype(float)
        + 0.40 * out["bct7"].astype(float)
        + 0.18 * out["positive_day"].astype(float)
        + 0.25 * out["no_chase_pass"].astype(float)
        - 0.65 * out["bad_reversal"].astype(float)
    )
    out["base_stock_score"] = (
        bct_score.fillna(0.0)
        + topk._num_col(out, "daily_structure_score", default=0.0).fillna(0.0) * 0.25
        + out["stock_chart_score"]
        - topk._bool_col(out, "d_no_chase_risk").astype(float)
    )
    return out


def _group_metrics(group: pd.DataFrame) -> dict[str, Any]:
    """Return label-free group metrics; label count is reporting-only when present."""
    return {
        "rows": int(len(group)),
        "bct6_count": int(group["bct6"].sum()),
        "bct7_count": int(group["bct7"].sum()),
        "weekly_good_pct": float(group["weekly_good"].mean() * 100.0),
        "weekly_strong_pct": float(group["weekly_strong"].mean() * 100.0),
        "weekly_recovering_pct": float(group["weekly_recovering"].mean() * 100.0),
        "daily_good_pct": float(group["daily_good"].mean() * 100.0),
        "daily_strong_pct": float(group["daily_strong"].mean() * 100.0),
        "daily_support_hold_pct": float(group["daily_support_hold"].mean() * 100.0),
        "daily_breakout_pct": float(group["daily_breakout"].mean() * 100.0),
        "volume_confirmed_pct": float(group["volume_confirmed"].mean() * 100.0),
        "positive_day_pct": float(group["positive_day"].mean() * 100.0),
        "bad_reversal_pct": float(group["bad_reversal"].mean() * 100.0),
        "no_chase_pass_pct": float(group["no_chase_pass"].mean() * 100.0),
        "median_bct_score": float(topk._num_col(group, "bct_score", default=0.0).median()),
        "median_day_return_pct": float(topk._num_col(group, "day_return_pct", default=0.0).median()),
        "george_rows": int(topk._bool_col(group, "is_george").sum()),
    }


def _sector_score(row: pd.Series) -> float:
    return float(
        0.038 * row["weekly_good_pct"]
        + 0.020 * row["weekly_strong_pct"]
        + 0.030 * row["daily_good_pct"]
        + 0.020 * row["daily_support_hold_pct"]
        + 0.017 * row["daily_breakout_pct"]
        + 0.014 * row["bct7_count"]
        + 0.010 * row["bct6_count"]
        + 0.008 * row["positive_day_pct"]
        + 0.006 * row["no_chase_pass_pct"]
        + 0.12 * _safe_log1p(row["rows"])
        - 0.020 * row["bad_reversal_pct"]
    )


def _industry_score(row: pd.Series) -> float:
    return float(
        0.042 * row["weekly_good_pct"]
        + 0.022 * row["weekly_strong_pct"]
        + 0.034 * row["daily_good_pct"]
        + 0.024 * row["daily_support_hold_pct"]
        + 0.020 * row["daily_breakout_pct"]
        + 0.018 * row["bct7_count"]
        + 0.010 * row["bct6_count"]
        + 0.009 * row["positive_day_pct"]
        + 0.008 * row["no_chase_pass_pct"]
        + 0.10 * _safe_log1p(row["rows"])
        - 0.023 * row["bad_reversal_pct"]
    )


def _build_sector_summary(scored: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base = scored[scored["has_sector_profile"]]
    for (date, sector), group in base.groupby(["date", "resolved_sector"], sort=True):
        row = _group_metrics(group)
        row["date"] = str(date)
        row["resolved_sector"] = str(sector)
        row["sector_proxy_score"] = _sector_score(pd.Series(row))
        rows.append(row)
    sectors = pd.DataFrame(rows)
    if sectors.empty:
        return sectors
    sectors["sector_rank"] = sectors.groupby("date")["sector_proxy_score"].rank(method="first", ascending=False)
    return sectors.sort_values(["date", "sector_rank", "resolved_sector"]).reset_index(drop=True)


def _build_industry_summary(scored: pd.DataFrame, sectors: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    base = scored[scored["has_industry_profile"]]
    for (date, sector, industry), group in base.groupby(["date", "resolved_sector", "resolved_industry"], sort=True):
        row = _group_metrics(group)
        row["date"] = str(date)
        row["resolved_sector"] = str(sector)
        row["resolved_industry"] = str(industry)
        row["industry_proxy_score"] = _industry_score(pd.Series(row))
        rows.append(row)
    industries = pd.DataFrame(rows)
    if industries.empty:
        return industries
    industries = industries.merge(
        sectors[["date", "resolved_sector", "sector_proxy_score", "sector_rank"]],
        on=["date", "resolved_sector"],
        how="left",
    )
    industries["industry_rank_global"] = industries.groupby("date")["industry_proxy_score"].rank(method="first", ascending=False)
    industries["industry_rank_in_sector"] = industries.groupby(["date", "resolved_sector"])["industry_proxy_score"].rank(method="first", ascending=False)
    industries["industry_hierarchy_score"] = (
        industries["industry_proxy_score"]
        + 0.18 * industries["sector_proxy_score"].fillna(0.0)
        + 0.55 * (industries["sector_rank"].fillna(999.0) <= 5.0).astype(float)
        + 0.35 * (industries["industry_rank_in_sector"].fillna(999.0) <= 3.0).astype(float)
    )
    industries["industry_rank_hierarchy"] = industries.groupby("date")["industry_hierarchy_score"].rank(method="first", ascending=False)
    industries["strong_industry_exception"] = (industries["sector_rank"].fillna(999.0) > 5.0) & (
        (industries["industry_rank_global"] <= 20.0)
        | ((industries["weekly_good_pct"] >= 55.0) & (industries["daily_good_pct"] >= 45.0))
    )
    return industries.sort_values(["date", "industry_rank_hierarchy", "resolved_industry"]).reset_index(drop=True)


def _date_zscore(panel: pd.DataFrame, column: str) -> pd.Series:
    values = topk._num_col(panel, column, default=0.0)
    mean = values.groupby(panel["date"]).transform("mean")
    std = values.groupby(panel["date"]).transform("std").replace(0.0, 1.0)
    return ((values - mean) / std).fillna(0.0)


def add_sector_industry_context(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Attach dynamic sector/industry ranks and hierarchy flags to the stock panel."""
    sectors = _build_sector_summary(scored)
    industries = _build_industry_summary(scored, sectors)
    out = scored.copy()
    if not sectors.empty:
        out = out.merge(
            sectors[
                [
                    "date",
                    "resolved_sector",
                    "sector_proxy_score",
                    "sector_rank",
                    "weekly_good_pct",
                    "daily_good_pct",
                    "bct7_count",
                    "rows",
                ]
            ].rename(
                columns={
                    "weekly_good_pct": "sector_weekly_good_pct",
                    "daily_good_pct": "sector_daily_good_pct",
                    "bct7_count": "sector_bct7_count_proxy",
                    "rows": "sector_rows_proxy",
                }
            ),
            on=["date", "resolved_sector"],
            how="left",
        )
    if not industries.empty:
        out = out.merge(
            industries[
                [
                    "date",
                    "resolved_sector",
                    "resolved_industry",
                    "industry_proxy_score",
                    "industry_hierarchy_score",
                    "industry_rank_global",
                    "industry_rank_hierarchy",
                    "industry_rank_in_sector",
                    "strong_industry_exception",
                    "weekly_good_pct",
                    "daily_good_pct",
                    "bct7_count",
                    "rows",
                ]
            ].rename(
                columns={
                    "weekly_good_pct": "industry_weekly_good_pct",
                    "daily_good_pct": "industry_daily_good_pct",
                    "bct7_count": "industry_bct7_count_proxy",
                    "rows": "industry_rows_proxy",
                }
            ),
            on=["date", "resolved_sector", "resolved_industry"],
            how="left",
        )
    out["base_stock_rank"] = out.groupby("date")["base_stock_score"].rank(method="first", ascending=False)
    out["stock_rank_in_industry_base"] = out.groupby(["date", "resolved_sector", "resolved_industry"])["base_stock_score"].rank(method="first", ascending=False)
    out["stock_rank_in_sector_base"] = out.groupby(["date", "resolved_sector"])["base_stock_score"].rank(method="first", ascending=False)

    out["sector_pass_top7"] = topk._num_col(out, "sector_rank", default=999.0) <= 7.0
    out["industry_pass_hierarchy"] = (
        (topk._num_col(out, "industry_rank_hierarchy", default=999.0) <= 30.0)
        | (
            (topk._num_col(out, "industry_rank_in_sector", default=999.0) <= 5.0)
            & (topk._num_col(out, "sector_rank", default=999.0) <= 7.0)
        )
        | topk._bool_col(out, "strong_industry_exception")
    )
    out["stock_pass_in_industry"] = (
        (topk._num_col(out, "stock_rank_in_industry_base", default=999.0) <= 10.0)
        & (out["bct6"] | out["daily_support_hold"])
    )
    out["trigger_pass_proxy"] = out["daily_breakout"] | out["daily_support_hold"] | (
        out["daily_good"] & out["volume_confirmed"]
    )
    out["hierarchy_all_stage_pass"] = (
        out["sector_pass_top7"]
        & out["industry_pass_hierarchy"]
        & out["stock_pass_in_industry"]
        & out["trigger_pass_proxy"]
    )
    out["sector_context_score"] = (
        out["base_stock_score"]
        + 0.22 * _date_zscore(out, "sector_proxy_score")
        + 0.42 * _date_zscore(out, "industry_proxy_score")
        + 0.30 * out["sector_pass_top7"].astype(float)
        + 0.45 * out["industry_pass_hierarchy"].astype(float)
        + 0.20 * out["trigger_pass_proxy"].astype(float)
    )
    out["hierarchy_stage_score"] = (
        out["base_stock_score"]
        + 0.30 * out["sector_pass_top7"].astype(float)
        + 0.55 * out["industry_pass_hierarchy"].astype(float)
        + 0.28 * out["stock_pass_in_industry"].astype(float)
        + 0.20 * out["trigger_pass_proxy"].astype(float)
    )
    return out, sectors, industries


def summarize_stage_recall(panel: pd.DataFrame, *, label_count: int) -> pd.DataFrame:
    """Summarize hierarchy-stage recall against labels already stamped on `panel`."""
    george = panel[topk._bool_col(panel, "is_george")].copy()
    with_sector = george[george["has_sector_profile"]]
    with_industry = george[george["has_industry_profile"]]
    rows: list[dict[str, Any]] = [
        {
            "stage": "label_coverage",
            "threshold": "in_score6_panel",
            "hits": int(len(george)),
            "total": int(label_count),
            "recall_pct": _pct(len(george), label_count),
        },
        {
            "stage": "profile_coverage",
            "threshold": "sector_profile",
            "hits": int(len(with_sector)),
            "total": int(len(george)),
            "recall_pct": _pct(len(with_sector), len(george)),
        },
        {
            "stage": "profile_coverage",
            "threshold": "industry_profile",
            "hits": int(len(with_industry)),
            "total": int(len(george)),
            "recall_pct": _pct(len(with_industry), len(george)),
        },
    ]
    for k in (1, 2, 3, 5, 7, 10):
        hits = int((topk._num_col(with_sector, "sector_rank", default=999.0) <= k).sum())
        rows.append({"stage": "sector", "threshold": f"top{k}", "hits": hits, "total": len(with_sector), "recall_pct": _pct(hits, len(with_sector))})
    for k in (1, 2, 3, 5, 10):
        hits = int((topk._num_col(with_industry, "industry_rank_in_sector", default=999.0) <= k).sum())
        rows.append({"stage": "industry_in_sector", "threshold": f"top{k}", "hits": hits, "total": len(with_industry), "recall_pct": _pct(hits, len(with_industry))})
    for k in (5, 10, 20, 30, 50):
        hits = int((topk._num_col(with_industry, "industry_rank_hierarchy", default=999.0) <= k).sum())
        rows.append({"stage": "industry_hierarchy", "threshold": f"top{k}", "hits": hits, "total": len(with_industry), "recall_pct": _pct(hits, len(with_industry))})
    for k in (1, 3, 5, 10, 20):
        hits = int((topk._num_col(with_industry, "stock_rank_in_industry_base", default=999.0) <= k).sum())
        rows.append({"stage": "stock_in_industry", "threshold": f"top{k}", "hits": hits, "total": len(with_industry), "recall_pct": _pct(hits, len(with_industry))})
    combined = {
        "sector_top7_and_industry_in_sector_top5": with_industry["sector_pass_top7"] & (topk._num_col(with_industry, "industry_rank_in_sector", default=999.0) <= 5.0),
        "industry_hierarchy_top30_or_exception": with_industry["industry_pass_hierarchy"],
        "industry_pass_and_stock_top10": with_industry["industry_pass_hierarchy"] & (topk._num_col(with_industry, "stock_rank_in_industry_base", default=999.0) <= 10.0),
        "all_stage_proxy": with_industry["hierarchy_all_stage_pass"],
    }
    for label, mask in combined.items():
        hits = int(mask.sum())
        rows.append({"stage": "combined", "threshold": label, "hits": hits, "total": len(with_industry), "recall_pct": _pct(hits, len(with_industry))})
    return pd.DataFrame(rows)


def sector_rank_variants(panel: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Return rank variants for measuring whether hierarchy context improves top-K selection."""
    all_rows = pd.Series(True, index=panel.index, dtype=bool)
    sector_top7 = topk._num_col(panel, "sector_rank", default=999.0) <= 7.0
    industry_top5 = topk._num_col(panel, "industry_rank_in_sector", default=999.0) <= 5.0
    industry_hierarchy = topk._num_col(panel, "industry_rank_hierarchy", default=999.0) <= 30.0
    return {
        "base_stock_score": (all_rows, topk._num_col(panel, "base_stock_score", default=float("-inf"))),
        "sector_context_score": (all_rows, topk._num_col(panel, "sector_context_score", default=float("-inf"))),
        "hierarchy_stage_score": (all_rows, topk._num_col(panel, "hierarchy_stage_score", default=float("-inf"))),
        "sector_top7__base_stock_score": (sector_top7, topk._num_col(panel, "base_stock_score", default=float("-inf"))),
        "sector_top7_industry_top5__base_stock_score": (
            sector_top7 & industry_top5,
            topk._num_col(panel, "base_stock_score", default=float("-inf")),
        ),
        "industry_hierarchy_top30__base_stock_score": (
            industry_hierarchy,
            topk._num_col(panel, "base_stock_score", default=float("-inf")),
        ),
        "hierarchy_all_stage__base_stock_score": (
            topk._bool_col(panel, "hierarchy_all_stage_pass"),
            topk._num_col(panel, "base_stock_score", default=float("-inf")),
        ),
    }


def run_sector_context_audit(
    denominator: pd.DataFrame,
    labels: Sequence[tuple[str, str]],
    *,
    covered_dates: set[str],
    config: topk.AuditConfig = topk.AuditConfig(),
) -> SectorContextResult:
    """Run sector/industry stage recall and top-K context audit."""
    panel = topk.build_score6_panel(denominator, labels, covered_dates=covered_dates, config=config)
    scored = add_stock_context_features(panel)
    enriched, sectors, industries = add_sector_industry_context(scored)
    return SectorContextResult(
        base_summary=topk.summarize_base_panel(enriched, label_count=len(labels)),
        stage_summary=summarize_stage_recall(enriched, label_count=len(labels)),
        rank_summary=topk.evaluate_rank_variants(
            enriched,
            sector_rank_variants(enriched),
            label_count=len(labels),
            ks=config.ks,
        ),
        sector_summary=sectors,
        industry_summary=industries,
        panel=enriched,
    )


def write_result(result: SectorContextResult, output_dir: Path) -> None:
    """Write audit result tables as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.base_summary.to_csv(output_dir / "base_summary.csv", index=False)
    result.stage_summary.to_csv(output_dir / "stage_summary.csv", index=False)
    result.rank_summary.to_csv(output_dir / "rank_summary.csv", index=False)
    result.sector_summary.to_csv(output_dir / "sector_summary.csv", index=False)
    result.industry_summary.to_csv(output_dir / "industry_summary.csv", index=False)


def _print_result(result: SectorContextResult) -> None:
    print("\nBASE")
    print(result.base_summary.to_string(index=False))
    print("\nSTAGE RECALL")
    print(result.stage_summary.to_string(index=False))
    print("\nRANK VARIANTS")
    print(result.rank_summary.to_string(index=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-csv", required=True, type=Path)
    parser.add_argument("--denominator-csv", required=True, type=Path)
    parser.add_argument("--coarse-dir", required=True, type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=topk.DEFAULT_TOP_N, type=int)
    parser.add_argument("--min-score", default=topk.DEFAULT_MIN_SCORE, type=int)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = topk.covered_dates_from_coarse(args.year, args.coarse_dir)
    labels = topk.load_covered_labels(args.labels_csv, covered_dates=covered_dates)
    if not labels:
        raise ValueError("no George labels remain after covered-date filtering")
    result = run_sector_context_audit(
        load_profiled_denominator(args.denominator_csv),
        labels,
        covered_dates=covered_dates,
        config=topk.AuditConfig(top_n=args.top_n, min_score=args.min_score),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
