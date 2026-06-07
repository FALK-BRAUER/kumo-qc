"""Analyze the #408 George-range 30-pack local BT artifacts.

The sweep runner produces raw summary/order/trade CSVs. This script turns those into
parameter confidence tables, indicator-bin ranges, and a short Markdown readout that
can be regenerated after follow-up sweeps.

Usage:
  python3 scripts/analyze_408_george_range_30.py
  python3 scripts/analyze_408_george_range_30.py --report-dir sweeps/reports/george_range_30
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import parse_qsl

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "sweeps" / "reports" / "george_range_30"


def pct_to_float(value: object) -> float:
    if value is None or pd.isna(value):
        return math.nan
    text = str(value).strip().replace("%", "")
    return float(text) if text else math.nan


def fmt_pct(value: float, digits: int = 3) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.{digits}f}%"


def confidence_from_n(n: int) -> str:
    if n >= 500:
        return "high"
    if n >= 100:
        return "medium"
    if n >= 30:
        return "low"
    return "thin"


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (math.nan, math.nan)
    phat = wins / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / denom
    return (center - margin, center + margin)


def parse_entry_tag(tag: object) -> dict[str, float]:
    if tag is None or pd.isna(tag):
        return {}
    out: dict[str, float] = {}
    for key, value in parse_qsl(str(tag), keep_blank_values=True):
        if not key.startswith("decision_"):
            continue
        try:
            out[key] = float(value)
        except ValueError:
            continue
    return out


def flatten_variants(manifest: dict) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for variant in manifest["variants"]:
        scratch = variant.get("scratch") or {}
        entry_params = variant.get("entry_trigger_params") or {}
        sizer_params = variant.get("sizer_params") or {}
        rows.append(
            {
                "variant_id": variant["variant_id"],
                "family": variant["family"],
                "hypothesis": variant.get("hypothesis", ""),
                "target_pct": variant.get("target_pct"),
                "min_peak_pct": variant.get("min_peak_pct"),
                "giveback_from_peak_pct": variant.get("giveback_from_peak_pct"),
                "require_still_bullish": variant.get("require_still_bullish"),
                "scratch_enabled": bool(variant.get("scratch")),
                "scratch_no_progress_days": scratch.get("no_progress_days"),
                "scratch_min_mfe_pct": scratch.get("min_mfe_pct"),
                "scratch_band_pct": scratch.get("scratch_band_pct"),
                "scratch_max_loss_after_mfe_pct": scratch.get("max_loss_after_mfe_pct"),
                "entry_trigger": variant.get("entry_trigger"),
                "entry_near_pct": entry_params.get("near_pct"),
                "entry_breakout_pct": entry_params.get("breakout_pct"),
                "sizer": variant.get("sizer"),
                "position_pct": sizer_params.get("position_pct"),
                "risk_pct": sizer_params.get("risk_pct"),
                "max_position_pct": sizer_params.get("max_position_pct"),
                "fallback_stop_pct": sizer_params.get("fallback_stop_pct"),
                "atr_mult": variant.get("atr_mult"),
                "resistance_buffer_pct": variant.get("resistance_buffer_pct"),
                "breadth_threshold": variant.get("breadth_threshold"),
                "missing_breadth_blocks": variant.get("missing_breadth_blocks"),
            }
        )
    return pd.DataFrame(rows)


def load_inputs(report_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    variants = flatten_variants(manifest)
    summary = pd.read_csv(report_dir / "summary.csv")
    trades = pd.read_csv(report_dir / "trades_all.csv")
    orders = pd.read_csv(report_dir / "orders_all.csv")

    summary["net_profit_pct"] = summary["net_profit"].map(pct_to_float)
    summary["drawdown_pct"] = summary["drawdown"].map(pct_to_float)
    summary["total_orders_num"] = pd.to_numeric(summary["total_orders"], errors="coerce")
    summary["sharpe_num"] = pd.to_numeric(summary["sharpe"], errors="coerce")
    summary = summary.merge(variants, on=["variant_id", "family", "hypothesis"], how="left")

    for col in ["qty", "duration_days", "entry_price", "exit_price", "pnl", "return_pct"]:
        trades[col] = pd.to_numeric(trades[col], errors="coerce")
    parsed_tags = trades["entry_tag"].map(parse_entry_tag)
    for key in ("decision_gap", "decision_vol", "decision_tdist", "decision_rank"):
        trades[key] = parsed_tags.map(lambda item, k=key: item.get(k, math.nan))
    trades["return_pct_points"] = trades["return_pct"] * 100.0
    trades["decision_gap_pct"] = trades["decision_gap"] * 100.0

    orders["quantity"] = pd.to_numeric(orders["quantity"], errors="coerce")
    orders["price"] = pd.to_numeric(orders["price"], errors="coerce")
    orders["abs_quantity"] = orders["quantity"].abs()
    return summary, trades, orders, variants


def group_trade_stats(df: pd.DataFrame) -> dict[str, object]:
    closed = df[df["status"] == "closed"].copy()
    n = int(len(closed))
    wins = int((closed["pnl"] > 0).sum()) if n else 0
    ci_low, ci_high = wilson_interval(wins, n)
    positive_pnl = float(closed.loc[closed["pnl"] > 0, "pnl"].sum()) if n else 0.0
    negative_pnl = float(closed.loc[closed["pnl"] < 0, "pnl"].sum()) if n else 0.0
    profit_factor = positive_pnl / abs(negative_pnl) if negative_pnl else math.nan
    return {
        "closed_trades": n,
        "open_or_censored_trades": int((df["status"] != "closed").sum()),
        "win_rate": wins / n if n else math.nan,
        "win_rate_ci_low": ci_low,
        "win_rate_ci_high": ci_high,
        "avg_return_pct": float(closed["return_pct_points"].mean()) if n else math.nan,
        "median_return_pct": float(closed["return_pct_points"].median()) if n else math.nan,
        "avg_pnl": float(closed["pnl"].mean()) if n else math.nan,
        "median_pnl": float(closed["pnl"].median()) if n else math.nan,
        "total_trade_pnl": float(closed["pnl"].sum()) if n else math.nan,
        "profit_factor": profit_factor,
        "avg_duration_days": float(closed["duration_days"].mean()) if n else math.nan,
        "median_duration_days": float(closed["duration_days"].median()) if n else math.nan,
        "p90_duration_days": float(closed["duration_days"].quantile(0.90)) if n else math.nan,
        "avg_decision_rank": float(closed["decision_rank"].mean()) if n else math.nan,
        "median_decision_rank": float(closed["decision_rank"].median()) if n else math.nan,
        "avg_decision_gap_pct": float(closed["decision_gap_pct"].mean()) if n else math.nan,
        "avg_decision_vol": float(closed["decision_vol"].mean()) if n else math.nan,
        "avg_decision_tdist": float(closed["decision_tdist"].mean()) if n else math.nan,
        "sample_confidence": confidence_from_n(n),
    }


def build_variant_trade_diagnostics(summary: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for variant_id, group in trades.groupby("variant_id", sort=False):
        stats = group_trade_stats(group)
        summary_row = summary.loc[summary["variant_id"] == variant_id].iloc[0].to_dict()
        rows.append(
            {
                "variant_id": variant_id,
                "family": summary_row["family"],
                "net_profit_pct": summary_row["net_profit_pct"],
                "drawdown_pct": summary_row["drawdown_pct"],
                "return_dd_ratio": summary_row["net_profit_pct"] / summary_row["drawdown_pct"]
                if summary_row["drawdown_pct"]
                else math.nan,
                "total_orders": summary_row["total_orders_num"],
                "sharpe": summary_row["sharpe_num"],
                **stats,
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["net_profit_pct", "drawdown_pct"], ascending=[False, True])


def numeric_range_rows(summary: pd.DataFrame, trades: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("summary", "net_profit_pct", summary["net_profit_pct"], "higher"),
        ("summary", "drawdown_pct", summary["drawdown_pct"], "lower"),
        ("summary", "sharpe", summary["sharpe_num"], "higher"),
        ("summary", "total_orders", summary["total_orders_num"], "context"),
        ("trade", "return_pct_points", trades.loc[trades["status"] == "closed", "return_pct_points"], "higher"),
        ("trade", "pnl", trades.loc[trades["status"] == "closed", "pnl"], "higher"),
        ("trade", "duration_days", trades.loc[trades["status"] == "closed", "duration_days"], "context"),
        ("entry_indicator", "decision_rank", trades["decision_rank"], "lower_rank_is_higher_liquidity"),
        ("entry_indicator", "decision_gap_pct", trades["decision_gap_pct"], "context"),
        ("entry_indicator", "decision_vol", trades["decision_vol"], "context"),
        ("entry_indicator", "decision_tdist", trades["decision_tdist"], "context"),
        ("order", "abs_quantity", orders["abs_quantity"], "context"),
        ("order", "fill_price", orders["price"], "context"),
    ]
    rows: list[dict[str, object]] = []
    for scope, metric, series, direction in specs:
        clean = pd.to_numeric(series, errors="coerce").dropna()
        total = len(series)
        rows.append(
            {
                "scope": scope,
                "metric": metric,
                "direction": direction,
                "n": int(clean.size),
                "coverage_pct": clean.size / total * 100.0 if total else math.nan,
                "min": float(clean.min()) if clean.size else math.nan,
                "p10": float(clean.quantile(0.10)) if clean.size else math.nan,
                "p25": float(clean.quantile(0.25)) if clean.size else math.nan,
                "median": float(clean.median()) if clean.size else math.nan,
                "p75": float(clean.quantile(0.75)) if clean.size else math.nan,
                "p90": float(clean.quantile(0.90)) if clean.size else math.nan,
                "max": float(clean.max()) if clean.size else math.nan,
                "sample_confidence": confidence_from_n(int(clean.size)),
            }
        )
    return pd.DataFrame(rows)


def summarize_bin(frame: pd.DataFrame, label: str, indicator: str, bucket: object) -> dict[str, object]:
    closed = frame[frame["status"] == "closed"]
    n = int(len(closed))
    wins = int((closed["pnl"] > 0).sum()) if n else 0
    ci_low, ci_high = wilson_interval(wins, n)
    return {
        "scope": label,
        "indicator": indicator,
        "bucket": str(bucket),
        "closed_trades": n,
        "win_rate": wins / n if n else math.nan,
        "win_rate_ci_low": ci_low,
        "win_rate_ci_high": ci_high,
        "avg_return_pct": float(closed["return_pct_points"].mean()) if n else math.nan,
        "median_return_pct": float(closed["return_pct_points"].median()) if n else math.nan,
        "avg_duration_days": float(closed["duration_days"].mean()) if n else math.nan,
        "total_pnl": float(closed["pnl"].sum()) if n else math.nan,
        "sample_confidence": confidence_from_n(n),
    }


def build_indicator_bins(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    closed = trades[trades["status"] == "closed"].copy()
    bin_specs = {
        "decision_rank": (
            [-math.inf, 24, 49, 99, 249, math.inf],
            ["rank_000_024", "rank_025_049", "rank_050_099", "rank_100_249", "rank_250_plus"],
        ),
        "decision_gap_pct": (
            [-math.inf, -1.0, 0.0, 1.0, 2.0, math.inf],
            ["gap_lt_-1pct", "gap_-1_to_0pct", "gap_0_to_1pct", "gap_1_to_2pct", "gap_gt_2pct"],
        ),
        "duration_days": (
            [-math.inf, 1, 3, 7, 14, 30, math.inf],
            ["hold_0_1d", "hold_1_3d", "hold_3_7d", "hold_7_14d", "hold_14_30d", "hold_30d_plus"],
        ),
    }
    for indicator, (bins, labels) in bin_specs.items():
        temp = closed.dropna(subset=[indicator]).copy()
        temp["bucket"] = pd.cut(temp[indicator], bins=bins, labels=labels, include_lowest=True)
        for bucket, group in temp.groupby("bucket", observed=True):
            rows.append(summarize_bin(group, "all", indicator, bucket))
        for family, family_group in temp.groupby("family", observed=True):
            for bucket, group in family_group.groupby("bucket", observed=True):
                rows.append(summarize_bin(group, f"family:{family}", indicator, bucket))

    temp = closed.dropna(subset=["decision_vol"]).copy()
    if not temp.empty and temp["decision_vol"].nunique() >= 4:
        temp["bucket"] = pd.qcut(temp["decision_vol"], q=4, duplicates="drop")
        for bucket, group in temp.groupby("bucket", observed=True):
            rows.append(summarize_bin(group, "all", "decision_vol_quartile", bucket))
        for family, family_group in temp.groupby("family", observed=True):
            for bucket, group in family_group.groupby("bucket", observed=True):
                rows.append(summarize_bin(group, f"family:{family}", "decision_vol_quartile", bucket))

    temp = closed.dropna(subset=["decision_tdist"]).copy()
    if not temp.empty and temp["decision_tdist"].nunique() > 1:
        temp["bucket"] = pd.qcut(temp["decision_tdist"], q=4, duplicates="drop")
        for bucket, group in temp.groupby("bucket", observed=True):
            rows.append(summarize_bin(group, "all", "decision_tdist_quartile", bucket))
    return pd.DataFrame(rows)


def group_summary(summary: pd.DataFrame, variant_ids: list[str]) -> pd.DataFrame:
    return summary[summary["variant_id"].isin(variant_ids)].copy()


def parameter_confidence_rows(summary: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    axes = [
        {
            "axis": "exit_target_management",
            "variant_ids": [
                "target_04_fast_take",
                "target_08_let_run",
                "target_10_patient_giveback",
                "giveback_loose_04",
                "giveback_tight_no_bull",
                "minpeak_low_03",
            ],
            "tested_range": "target 4-10%, min_peak 3-8%, giveback 1.5-4%, bullish true/false",
            "recommended_range": "target 6-8%, min_peak 3-5%, giveback 1.5-2.5%; test no-bullish-gate again",
            "confidence": "medium",
            "interpretation": "Best risk-adjusted cells are all proactive exit variants near 10% net with <=18% DD.",
        },
        {
            "axis": "scratch_no_progress",
            "variant_ids": [
                "scratch_base",
                "scratch_fast",
                "scratch_patient",
                "scratch_tight_risk",
                "scratch_1d_low_mfe",
                "scratch_2d_low_mfe",
                "scratch_5d_wide_band",
                "scratch_7d_patient",
                "scratch_losscap_03",
                "scratch_roundtrip_wide_01",
            ],
            "tested_range": "1-7 no-progress days, MFE 1-3%, flat band 0.3-1.0%, loss cap 1-3%",
            "recommended_range": "Do not promote as primary edge; if kept, retest only tight-risk or 1d low-MFE.",
            "confidence": "medium",
            "interpretation": "Scratch variants prove the path contract but consistently trail proactive-only return.",
        },
        {
            "axis": "entry_near_pct",
            "variant_ids": ["entry_near_010", "entry_near_020", "entry_near_025"],
            "tested_range": "near_pct 1.0-2.5%",
            "recommended_range": "2.0-2.5% only as a follow-up if paired with stronger exits/DD cap.",
            "confidence": "low",
            "interpretation": "Wider near-zone raises return, but DD stays worse than the best proactive exit cells.",
        },
        {
            "axis": "buy_stop_breakout",
            "variant_ids": ["buy_stop_flat", "buy_stop_005", "buy_stop_010"],
            "tested_range": "breakout offset 0-1.0%",
            "recommended_range": "0.5-1.0% for lower-DD entry experiments; 0.5% is the better return/DD balance.",
            "confidence": "medium",
            "interpretation": "Buy-stop offsets reduce DD materially versus scratch baseline, with lower return.",
        },
        {
            "axis": "flat_position_atr",
            "variant_ids": ["scratch_base", "pos_03_atr_075", "pos_05_atr_050"],
            "tested_range": "position 3-5%, ATR 0.5-0.75",
            "recommended_range": "3% position with wider ATR if DD cap matters; avoid 5% flat sizing.",
            "confidence": "low",
            "interpretation": "3% position lowers DD sharply; 5% position increases DD without return improvement.",
        },
        {
            "axis": "vol_adjusted_risk",
            "variant_ids": ["volrisk_075", "volrisk_125"],
            "tested_range": "risk_pct 0.75-1.25%, max position 6-8%",
            "recommended_range": "Do not promote without hard gross/DD controls.",
            "confidence": "medium",
            "interpretation": "Both vol-risk cells increase return by accepting too much drawdown.",
        },
        {
            "axis": "resistance_or_breadth_gate",
            "variant_ids": ["scratch_base", "resistance_loose_010", "breadth_050_strict"],
            "tested_range": "resistance buffer 1-2%, breadth threshold 40-50%",
            "recommended_range": "Treat as non-binding in this config path; instrument before retesting.",
            "confidence": "low",
            "interpretation": "Both variants matched scratch_base exactly, so these params likely did not bind.",
        },
    ]
    rows: list[dict[str, object]] = []
    for axis in axes:
        group = group_summary(summary, axis["variant_ids"])
        trade_group = trades[trades["variant_id"].isin(axis["variant_ids"])]
        best_net = group.sort_values(["net_profit_pct", "drawdown_pct"], ascending=[False, True]).iloc[0]
        eligible = group[group["drawdown_pct"] <= 18.0]
        best_clean = (
            eligible.sort_values(["net_profit_pct", "drawdown_pct"], ascending=[False, True]).iloc[0]
            if not eligible.empty
            else best_net
        )
        rows.append(
            {
                "axis": axis["axis"],
                "tested_range": axis["tested_range"],
                "n_variants": int(len(group)),
                "closed_trades": int((trade_group["status"] == "closed").sum()),
                "net_min_pct": float(group["net_profit_pct"].min()),
                "net_median_pct": float(group["net_profit_pct"].median()),
                "net_max_pct": float(group["net_profit_pct"].max()),
                "drawdown_min_pct": float(group["drawdown_pct"].min()),
                "drawdown_median_pct": float(group["drawdown_pct"].median()),
                "drawdown_max_pct": float(group["drawdown_pct"].max()),
                "best_net_variant": best_net["variant_id"],
                "best_net_pct": best_net["net_profit_pct"],
                "best_net_drawdown_pct": best_net["drawdown_pct"],
                "best_clean_variant": best_clean["variant_id"],
                "best_clean_net_pct": best_clean["net_profit_pct"],
                "best_clean_drawdown_pct": best_clean["drawdown_pct"],
                "recommended_range": axis["recommended_range"],
                "confidence": axis["confidence"],
                "interpretation": axis["interpretation"],
            }
        )
    return pd.DataFrame(rows)


def symbol_edges(trades: pd.DataFrame) -> pd.DataFrame:
    closed = trades[trades["status"] == "closed"].copy()
    rows: list[dict[str, object]] = []
    for symbol, group in closed.groupby("symbol"):
        if len(group) < 30:
            continue
        rows.append(
            {
                "symbol": symbol,
                "closed_trades": int(len(group)),
                "variant_count": int(group["variant_id"].nunique()),
                "win_rate": float((group["pnl"] > 0).mean()),
                "avg_return_pct": float(group["return_pct_points"].mean()),
                "median_return_pct": float(group["return_pct_points"].median()),
                "total_pnl": float(group["pnl"].sum()),
                "avg_duration_days": float(group["duration_days"].mean()),
                "sample_confidence": confidence_from_n(int(len(group))),
            }
        )
    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False)


def write_markdown(
    path: Path,
    summary: pd.DataFrame,
    diagnostics: pd.DataFrame,
    params: pd.DataFrame,
    bins: pd.DataFrame,
    symbols: pd.DataFrame,
) -> None:
    top_clean = summary[summary["drawdown_pct"] <= 18.0].sort_values(
        ["net_profit_pct", "drawdown_pct"], ascending=[False, True]
    )
    best_dd = summary.sort_values(["drawdown_pct", "net_profit_pct"], ascending=[True, False]).head(5)
    rank_bins = bins[(bins["scope"] == "all") & (bins["indicator"] == "decision_rank")].copy()
    gap_bins = bins[(bins["scope"] == "all") & (bins["indicator"] == "decision_gap_pct")].copy()
    vol_bins = bins[(bins["scope"] == "all") & (bins["indicator"] == "decision_vol_quartile")].copy()
    hold_bins = bins[(bins["scope"] == "all") & (bins["indicator"] == "duration_days")].copy()

    lines = [
        "# George Range 30 Analysis",
        "",
        "## Scope",
        "",
        "This analysis uses only the completed local LEAN artifacts from `george_range_30`: "
        "summary rows, filled orders, paired/censored trades, and the decision tags embedded in entries. "
        "It does not infer sector, regime, gap-fill, or scanner-miss context that is not present in these CSVs.",
        "",
        "## Best Observed Parameter Cells",
        "",
        "| variant | family | net | DD | orders | sharpe | confidence |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for _, row in top_clean.head(8).iterrows():
        diag = diagnostics.loc[diagnostics["variant_id"] == row["variant_id"]].iloc[0]
        lines.append(
            f"| `{row['variant_id']}` | {row['family']} | {fmt_pct(row['net_profit_pct'])} | "
            f"{fmt_pct(row['drawdown_pct'])} | {int(row['total_orders_num'])} | "
            f"{row['sharpe_num']:.3f} | {diag['sample_confidence']} |"
        )

    lines.extend(
        [
            "",
            "## Lowest Drawdown Cells",
            "",
            "| variant | family | net | DD | orders | read |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for _, row in best_dd.iterrows():
        read = "candidate DD control" if row["drawdown_pct"] < 16 else "context"
        lines.append(
            f"| `{row['variant_id']}` | {row['family']} | {fmt_pct(row['net_profit_pct'])} | "
            f"{fmt_pct(row['drawdown_pct'])} | {int(row['total_orders_num'])} | {read} |"
        )

    lines.extend(
        [
            "",
            "## Parameter Confidence",
            "",
            "| axis | best net | best <=18% DD | recommended range | confidence | interpretation |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for _, row in params.iterrows():
        best_net = f"`{row['best_net_variant']}` ({fmt_pct(row['best_net_pct'])} / {fmt_pct(row['best_net_drawdown_pct'])} DD)"
        best_clean = f"`{row['best_clean_variant']}` ({fmt_pct(row['best_clean_net_pct'])} / {fmt_pct(row['best_clean_drawdown_pct'])} DD)"
        lines.append(
            f"| {row['axis']} | {best_net} | {best_clean} | {row['recommended_range']} | "
            f"{row['confidence']} | {row['interpretation']} |"
        )

    lines.extend(
        [
            "",
            "## Entry Indicator Ranges",
            "",
            "Decision-rank is lower-is-better liquidity/DV rank. These bins are trade-level observations "
            "across variants, so they are useful for pattern discovery but are not independent samples.",
            "",
            "| indicator bucket | closed trades | win rate | avg return | median return | confidence |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for _, row in rank_bins.iterrows():
        lines.append(
            f"| {row['bucket']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['sample_confidence']} |"
        )
    lines.extend(["", "| gap bucket | closed trades | win rate | avg return | median return | confidence |", "| --- | ---: | ---: | ---: | ---: | --- |"])
    for _, row in gap_bins.iterrows():
        lines.append(
            f"| {row['bucket']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['sample_confidence']} |"
        )
    lines.extend(["", "| volatility bucket | closed trades | win rate | avg return | median return | confidence |", "| --- | ---: | ---: | ---: | ---: | --- |"])
    for _, row in vol_bins.iterrows():
        lines.append(
            f"| {row['bucket']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['sample_confidence']} |"
        )
    lines.extend(["", "| hold bucket | closed trades | win rate | avg return | median return | confidence |", "| --- | ---: | ---: | ---: | ---: | --- |"])
    for _, row in hold_bins.iterrows():
        lines.append(
            f"| {row['bucket']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['sample_confidence']} |"
        )

    lines.extend(
        [
            "",
            "## Symbol Edges",
            "",
            "These are repeated across variants, so use them as ticker-behavior clues, not independent "
            "production rankings.",
            "",
            "| symbol | closed trades | win rate | avg return | median return | total pnl | confidence |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for _, row in symbols.head(8).iterrows():
        lines.append(
            f"| {row['symbol']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['total_pnl']:.0f} | {row['sample_confidence']} |"
        )
    lines.extend(["", "| weak symbol | closed trades | win rate | avg return | median return | total pnl | confidence |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
    for _, row in symbols.tail(6).iterrows():
        lines.append(
            f"| {row['symbol']} | {int(row['closed_trades'])} | {row['win_rate']:.1%} | "
            f"{fmt_pct(row['avg_return_pct'])} | {fmt_pct(row['median_return_pct'])} | "
            f"{row['total_pnl']:.0f} | {row['sample_confidence']} |"
        )

    lines.extend(
        [
            "",
            "## Confidence Notes",
            "",
            "- High/medium/low on trade bins is sample-size confidence, not causal proof.",
            "- Parameter confidence is capped at medium because this is one FY2025 slice and variants are correlated.",
            "- `exit_events_all.csv` remains empty because current phase logs do not emit per-symbol exit events.",
            "- Sector, industry, market regime, intraday candle path, George scanner context, and Falk scanner context still require enrichment before claiming George-reasoning replication.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_readme(path: Path) -> None:
    readme = path / "README.md"
    readme.write_text(
        "# analysis/\n\n"
        "Derived diagnostics for the George-range 30-pack local BT sweep.\n"
        "This folder holds regenerated analysis CSVs and Markdown summaries.\n"
        "Do not place raw LEAN backtest folders here; those stay under `sweeps/runs/`.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    report_dir = args.report_dir.resolve()
    out_dir = report_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_readme(out_dir)

    summary, trades, orders, _variants = load_inputs(report_dir)
    diagnostics = build_variant_trade_diagnostics(summary, trades)
    metric_ranges = numeric_range_rows(summary, trades, orders)
    bins = build_indicator_bins(trades)
    params = parameter_confidence_rows(summary, trades)
    symbols = symbol_edges(trades)

    diagnostics.to_csv(out_dir / "variant_trade_diagnostics.csv", index=False)
    metric_ranges.to_csv(out_dir / "metric_ranges.csv", index=False)
    bins.to_csv(out_dir / "entry_indicator_bins.csv", index=False)
    params.to_csv(out_dir / "parameter_confidence.csv", index=False)
    symbols.to_csv(out_dir / "symbol_edges.csv", index=False)
    write_markdown(out_dir / "analysis.md", summary, diagnostics, params, bins, symbols)

    print(f"ANALYSIS_DIR|{out_dir}")
    print(f"variants={len(summary)} closed_trades={(trades['status'] == 'closed').sum()} orders={len(orders)}")
    print(f"best_clean={params.loc[params['axis'] == 'exit_target_management', 'best_clean_variant'].iloc[0]}")


if __name__ == "__main__":
    main()
