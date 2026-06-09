"""Bridge Massive-backed scanner denominators into QC-style local candidate panels.

This is an offline research helper. It converts an explicit Massive-backed denominator CSV into a
local candidate-panel artifact that the George top-K and learned-ranker audits can consume. It does
not implement QC cloud universe selection and must not be imported by runtime strategy code.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import math
import pandas as pd

from sweeps.archive import candidates as C
from sweeps.archive import george_coverage_audit as coverage
from sweeps.archive import george_topk_audit as topk


BRIDGE_USECOLS: tuple[str, ...] = (
    "date",
    "symbol",
    "in_candidate_denominator",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "day_dollar_vol",
    "adv20_incl_today",
    "avg_volume20",
    "rel_volume20",
    "gap_pct",
    "day_return_pct",
    "intraday_return_pct",
    "range_pct",
    "day_dv_rank_price10",
    "adv20_rank_price10",
    "price_floor",
    "history_days_for_adv",
    "daily_structure_score",
    "d_price_above_cloud",
    "d_price_above_tenkan",
    "d_price_above_kijun",
    "d_tenkan_gt_kijun",
    "d_cloud_green",
    "d_price_above_ma200",
    "d_chikou_ok",
    "d_chikou_open_space",
    "d_cloud_distance_pct",
    "d_tenkan_extension_pct",
    "d_kijun_extension_pct",
    "d_tk_spread_pct",
    "d_near_prior20_high_within3",
    "d_near_prior50_high_within5",
    "d_near_prior252_high_within5",
    "d_close_above_prior20_high",
    "d_close_above_prior50_high",
    "d_close_above_prior252_high",
    "d_resistance_rejection_today",
    "d_recent_resistance_rejection_count20",
    "d_rel_volume50",
    "d_volume_above_ma50",
    "d_volume_spike_150",
    "d_breakout20_volume_confirmed",
    "d_breakout50_volume_confirmed",
    "d_breakout252_volume_confirmed",
    "d_return_5d_pct",
    "d_return_10d_pct",
    "d_return_20d_pct",
    "d_upper_wick_pct_range",
    "d_lower_wick_pct_range",
    "d_bearish_reversal_candle",
    "d_shooting_star_like",
    "d_no_chase_risk",
    "daily_breakout_quality_score",
    "d_adx",
    "d_plus_di",
    "d_minus_di",
    "bct_valid",
    "bct_score",
    "bct_rating",
    "bct_weekly_veto",
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
)
REQUIRED_COLUMNS: tuple[str, ...] = (
    "date",
    "symbol",
    "in_candidate_denominator",
    "adv20_rank_price10",
    "bct_score",
)


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Massive denominator to QC-style panel settings."""

    top_n: int | None = 3000
    min_score: int | None = 6
    require_candidate_denominator: bool = True
    require_price_floor: bool = True


@dataclass(frozen=True, slots=True)
class BridgeResult:
    panel: pd.DataFrame
    summary: pd.DataFrame
    daily_summary: pd.DataFrame
    label_coverage: pd.DataFrame


def load_denominator(path: Path) -> pd.DataFrame:
    """Load Massive denominator columns used by the bridge, with required-column checks."""
    header = list(pd.read_csv(path, nrows=0).columns)
    missing = [col for col in REQUIRED_COLUMNS if col not in header]
    if missing:
        raise ValueError(f"denominator missing required columns: {missing}")
    usecols = [col for col in BRIDGE_USECOLS if col in header]
    return pd.read_csv(path, usecols=usecols, low_memory=False)


def normalize_denominator(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize date/symbol/key and preserve all source columns."""
    out = df.copy()
    out["date"] = out["date"].astype(str)
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["key"] = out["date"] + "|" + out["symbol"]
    return out


def _candidate_lane(score: float) -> str:
    if not math.isfinite(score):
        return "score_not_ready"
    return C._candidate_lane(int(score))


def _price_floor_mask(df: pd.DataFrame) -> pd.Series:
    """Handle denominator files where `price_floor` is a threshold, not a boolean."""
    if "price_floor" not in df.columns:
        return pd.Series(True, index=df.index, dtype=bool)
    if df["price_floor"].dtype == bool:
        return topk._bool_col(df, "price_floor")
    numeric_floor = topk._num_col(df, "price_floor")
    if numeric_floor.notna().any():
        observed = set(float(v) for v in numeric_floor.dropna().unique())
        if observed <= {0.0, 1.0}:
            return numeric_floor.fillna(0.0).astype(bool)
        close = topk._num_col(df, "close")
        return close >= numeric_floor
    return topk._bool_col(df, "price_floor")


def build_bridge_panel(
    denominator: pd.DataFrame,
    *,
    covered_dates: set[str] | None = None,
    config: BridgeConfig = BridgeConfig(),
) -> pd.DataFrame:
    """Build a QC-style candidate panel from the Massive-backed denominator."""
    df = normalize_denominator(denominator)
    mask = pd.Series(True, index=df.index, dtype=bool)
    if config.require_candidate_denominator:
        mask &= topk._bool_col(df, "in_candidate_denominator")
    if covered_dates is not None:
        mask &= df["date"].isin(covered_dates)
    if config.require_price_floor and "price_floor" in df.columns:
        mask &= _price_floor_mask(df)
    if config.top_n is not None:
        mask &= topk._num_col(df, "adv20_rank_price10") <= config.top_n
    if config.min_score is not None:
        mask &= topk._num_col(df, "bct_score") >= config.min_score

    panel = df.loc[mask].copy()
    score = topk._num_col(panel, "bct_score")
    panel["bct_candidate_lane"] = [_candidate_lane(float(value)) for value in score]
    panel["bridge_source"] = "massive_denominator"
    panel = panel.sort_values(["date", "adv20_rank_price10", "symbol"], na_position="last")
    return panel.reset_index(drop=True)


def summarize_panel(panel: pd.DataFrame, *, config: BridgeConfig) -> pd.DataFrame:
    """Return one-row panel summary."""
    daily_counts = panel.groupby("date").size()
    score = topk._num_col(panel, "bct_score")
    return pd.DataFrame(
        [
            {
                "rows": int(len(panel)),
                "dates": int(panel["date"].nunique()) if "date" in panel else 0,
                "median_daily": float(daily_counts.median()) if not daily_counts.empty else 0.0,
                "avg_daily": float(daily_counts.mean()) if not daily_counts.empty else 0.0,
                "top_n": config.top_n,
                "min_score": config.min_score,
                "bct_ge7_rows": int((score >= 7).sum()),
                "score6_rows": int((score == 6).sum()),
            }
        ]
    )


def summarize_daily(panel: pd.DataFrame) -> pd.DataFrame:
    """Return per-date row counts and score-lane counts."""
    if panel.empty:
        return pd.DataFrame(columns=["date", "rows", "bct_ge7_rows", "score6_rows"])
    score = topk._num_col(panel, "bct_score")
    tmp = panel[["date"]].copy()
    tmp["bct_ge7"] = score >= 7
    tmp["score6"] = score == 6
    out = tmp.groupby("date", as_index=False).agg(
        rows=("date", "size"),
        bct_ge7_rows=("bct_ge7", "sum"),
        score6_rows=("score6", "sum"),
    )
    return out.sort_values("date").reset_index(drop=True)


def summarize_label_coverage(panel: pd.DataFrame, labels: Sequence[tuple[str, str]]) -> pd.DataFrame:
    """Summarize optional George-label coverage without adding labels to the exported panel."""
    label_keys = {f"{date}|{symbol.upper()}" for date, symbol in labels}
    panel_keys = set(panel["key"].astype(str)) if "key" in panel else set()
    hits = len(label_keys & panel_keys)
    return pd.DataFrame(
        [
            {
                "labels": len(label_keys),
                "hits": hits,
                "missing": len(label_keys - panel_keys),
                "recall_pct": round(100.0 * hits / len(label_keys), 2) if label_keys else 0.0,
            }
        ]
    )


def run_bridge(
    denominator: pd.DataFrame,
    *,
    covered_dates: set[str] | None = None,
    labels: Sequence[tuple[str, str]] = (),
    config: BridgeConfig = BridgeConfig(),
) -> BridgeResult:
    """Build panel plus summary tables."""
    panel = build_bridge_panel(denominator, covered_dates=covered_dates, config=config)
    return BridgeResult(
        panel=panel,
        summary=summarize_panel(panel, config=config),
        daily_summary=summarize_daily(panel),
        label_coverage=summarize_label_coverage(panel, labels),
    )


def write_result(result: BridgeResult, output_dir: Path) -> None:
    """Write bridge artifacts as CSVs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result.panel.to_csv(output_dir / "candidate_panel.csv", index=False)
    result.summary.to_csv(output_dir / "summary.csv", index=False)
    result.daily_summary.to_csv(output_dir / "daily_summary.csv", index=False)
    result.label_coverage.to_csv(output_dir / "label_coverage.csv", index=False)


def _print_result(result: BridgeResult) -> None:
    print("\nSUMMARY")
    print(result.summary.to_string(index=False))
    print("\nLABEL COVERAGE")
    print(result.label_coverage.to_string(index=False))


def _covered_dates(year: int, coarse_dir: Path | None) -> set[str] | None:
    if coarse_dir is None:
        return None
    return topk.covered_dates_from_coarse(year, coarse_dir)


def _labels(labels_csv: Path | None, covered_dates: set[str] | None) -> list[tuple[str, str]]:
    if labels_csv is None:
        return []
    labels = coverage.load_george_labels(labels_csv)
    if covered_dates is None:
        return labels
    return [(date, symbol) for date, symbol in labels if date in covered_dates]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--denominator-csv", required=True, type=Path)
    parser.add_argument("--labels-csv", type=Path)
    parser.add_argument("--coarse-dir", type=Path)
    parser.add_argument("--year", default=2026, type=int)
    parser.add_argument("--top-n", default=3000, type=int)
    parser.add_argument("--min-score", default=6, type=int)
    parser.add_argument("--no-min-score", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    covered_dates = _covered_dates(args.year, args.coarse_dir)
    min_score = None if args.no_min_score else args.min_score
    result = run_bridge(
        load_denominator(args.denominator_csv),
        covered_dates=covered_dates,
        labels=_labels(args.labels_csv, covered_dates),
        config=BridgeConfig(top_n=args.top_n, min_score=min_score),
    )
    _print_result(result)
    if args.output_dir is not None:
        write_result(result, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
