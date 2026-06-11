"""Analyze George/Kumo source differences in the #482 scanner trade universe."""
from __future__ import annotations

import argparse
import gzip
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "sweeps" / "reports" / "scanner_trade_universe_482" / "scanner_trade_universe.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_source_diagnostics_485"

BOOL_COLUMNS = [
    "george_signal_seen",
    "george_video_only_context",
    "kumo_signal_seen",
    "kumo_top_n",
    "both_george_and_kumo",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_scanner",
    "best_entry_runner_candidate_20d",
    "best_entry_normal_winner_20d",
    "best_entry_bad_trade_20d",
    "next_open_triggered",
    "next_open_bad_trade_20d",
    "best_deployable_runner_preserved_40d",
    "oof_available",
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
]

NUMERIC_COLUMNS = [
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "entry_assumption_count",
    "triggered_entry_count",
    "strict_triggered_entry_count",
    "bad_triggered_entry_count",
    "best_entry_price",
    "best_entry_ret_20d_close_pct",
    "best_entry_mfe_20d_pct",
    "best_entry_mae_20d_pct",
    "next_open_ret_20d_close_pct",
    "next_open_mfe_20d_pct",
    "next_open_mae_20d_pct",
    "best_deployable_total_equity_ret_40d_pct",
    "best_deployable_realized_ret_pct",
    "best_deployable_exposure_sessions",
    "oracle_best_total_equity_ret_40d_pct",
    "hold_40d_total_equity_ret_40d_pct",
    "baseline_kumo_rank_score",
    "baseline_kumo_score",
    "baseline_rule_score",
    "model_trade_worthy_score",
    "model_runner_score",
    "model_combined_score",
]

EXAMPLE_COLUMNS = [
    "example_type",
    "scan_date",
    "symbol",
    "trade_bucket",
    "source_bucket",
    "reason_codes",
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "best_entry_assumption",
    "best_entry_ret_20d_close_pct",
    "best_entry_mfe_20d_pct",
    "best_entry_mae_20d_pct",
    "best_deployable_exit_policy_id",
    "best_deployable_total_equity_ret_40d_pct",
    "model_combined_score",
]


@dataclass(frozen=True)
class DiagnosticsConfig:
    universe: str
    output_dir: str
    examples_per_type_date: int


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--examples-per-type-date", type=int, default=3)
    return parser.parse_args()


def _bool_series(series: pd.Series | None, *, index: pd.Index) -> pd.Series:
    if series is None:
        return pd.Series(False, index=index)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def read_universe(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, low_memory=False)
    for column in BOOL_COLUMNS:
        if column in frame.columns:
            frame[column] = _bool_series(frame[column], index=frame.index)
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["scan_date"] = pd.to_datetime(frame["scan_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["source_bucket"] = frame["source_bucket"].fillna("unknown").astype(str)
    frame["trade_bucket"] = frame["trade_bucket"].fillna("unknown").astype(str)
    return frame


def source_outcome_summary(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    frame["has_trigger"] = frame["triggered_entry_count"].fillna(0).gt(0)
    frame["is_optimal"] = frame["trade_bucket"].eq("optimal")
    frame["is_bad"] = frame["trade_bucket"].eq("bad")
    frame["is_watch"] = frame["trade_bucket"].eq("watch")
    frame["is_runner"] = frame["best_entry_runner_candidate_20d"].astype(bool)
    frame["is_bad_entry"] = frame["best_entry_bad_trade_20d"].astype(bool)
    grouped = frame.groupby("source_bucket", dropna=False)
    summary = grouped.agg(
        opportunities=("opportunity_id", "count"),
        dates=("scan_date", "nunique"),
        symbols=("symbol", "nunique"),
        triggered_rows=("has_trigger", "sum"),
        optimal_rows=("is_optimal", "sum"),
        bad_rows=("is_bad", "sum"),
        watch_rows=("is_watch", "sum"),
        runner_rows=("is_runner", "sum"),
        bad_entry_rows=("is_bad_entry", "sum"),
        avg_best_entry_ret20_pct=("best_entry_ret_20d_close_pct", "mean"),
        avg_best_entry_mfe20_pct=("best_entry_mfe_20d_pct", "mean"),
        avg_best_entry_mae20_pct=("best_entry_mae_20d_pct", "mean"),
        avg_best_deployable_exit_total40_pct=("best_deployable_total_equity_ret_40d_pct", "mean"),
        avg_model_combined_score=("model_combined_score", "mean"),
        median_kumo_rank=("kumo_rank_by_score", "median"),
        median_george_rank=("george_rank", "median"),
    ).reset_index()
    for pct_column, count_column in [
        ("trigger_rate_pct", "triggered_rows"),
        ("optimal_pct", "optimal_rows"),
        ("bad_pct", "bad_rows"),
        ("watch_pct", "watch_rows"),
        ("runner_pct", "runner_rows"),
        ("bad_entry_pct", "bad_entry_rows"),
    ]:
        summary[pct_column] = (summary[count_column] / summary["opportunities"] * 100.0).round(3)
    numeric_cols = [
        "avg_best_entry_ret20_pct",
        "avg_best_entry_mfe20_pct",
        "avg_best_entry_mae20_pct",
        "avg_best_deployable_exit_total40_pct",
        "avg_model_combined_score",
        "median_kumo_rank",
        "median_george_rank",
    ]
    summary[numeric_cols] = summary[numeric_cols].round(4)
    return summary.sort_values(["opportunities", "source_bucket"], ascending=[False, True]).reset_index(drop=True)


def reason_code_summary(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe[["source_bucket", "trade_bucket", "reason_codes"]].copy()
    frame["reason_code"] = frame["reason_codes"].fillna("").astype(str).str.split(";")
    exploded = frame.explode("reason_code")
    exploded["reason_code"] = exploded["reason_code"].fillna("").astype(str).str.strip()
    exploded = exploded[exploded["reason_code"].ne("")]
    if exploded.empty:
        return pd.DataFrame(columns=["source_bucket", "trade_bucket", "reason_code", "rows", "pct_of_bucket_trade"])
    grouped = exploded.groupby(["source_bucket", "trade_bucket", "reason_code"], dropna=False).size().reset_index(name="rows")
    denominators = universe.groupby(["source_bucket", "trade_bucket"], dropna=False).size().reset_index(name="bucket_trade_rows")
    grouped = grouped.merge(denominators, on=["source_bucket", "trade_bucket"], how="left")
    grouped["pct_of_bucket_trade"] = (grouped["rows"] / grouped["bucket_trade_rows"] * 100.0).round(3)
    return grouped.sort_values(["source_bucket", "trade_bucket", "rows"], ascending=[True, True, False]).reset_index(drop=True)


def missed_optimal_trades(universe: pd.DataFrame) -> pd.DataFrame:
    optimal = universe[universe["trade_bucket"].eq("optimal")].copy()
    missed = optimal[
        optimal["source_bucket"].isin(["kumo_only", "george_only", "kumo_with_george_video_context"])
    ].copy()
    if missed.empty:
        return missed

    def missed_by(row: pd.Series) -> str:
        if row["source_bucket"] == "george_only":
            return "kumo"
        if row["source_bucket"] == "kumo_with_george_video_context":
            return "george_scanner_or_watchlist"
        return "george"

    missed["missed_by"] = missed.apply(missed_by, axis=1)
    missed = missed.sort_values(
        ["missed_by", "best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"],
        ascending=[True, False, False],
        na_position="last",
    )
    return missed


def high_risk_false_positives(universe: pd.DataFrame) -> pd.DataFrame:
    bad = universe[universe["trade_bucket"].eq("bad")].copy()
    if bad.empty:
        return bad
    bad["risk_score"] = (
        bad["best_entry_mae_20d_pct"].fillna(0).abs()
        + bad["bad_triggered_entry_count"].fillna(0) * 2.0
        + bad["best_deployable_total_equity_ret_40d_pct"].fillna(0).clip(upper=0).abs()
    )
    return bad.sort_values(["source_bucket", "risk_score"], ascending=[True, False]).reset_index(drop=True)


def daily_source_examples(universe: pd.DataFrame, *, examples_per_type_date: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    specs = [
        (
            "kumo_addition_optimal",
            universe["source_bucket"].isin(["kumo_only", "kumo_with_george_video_context"])
            & universe["trade_bucket"].eq("optimal"),
            ["best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"],
            [False, False],
        ),
        (
            "george_addition_optimal",
            universe["source_bucket"].eq("george_only") & universe["trade_bucket"].eq("optimal"),
            ["best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"],
            [False, False],
        ),
        (
            "shared_winner",
            universe["source_bucket"].eq("both_george_and_kumo") & universe["trade_bucket"].eq("optimal"),
            ["best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"],
            [False, False],
        ),
        (
            "shared_trap",
            universe["source_bucket"].eq("both_george_and_kumo") & universe["trade_bucket"].eq("bad"),
            ["best_entry_mae_20d_pct", "best_deployable_total_equity_ret_40d_pct"],
            [True, True],
        ),
        (
            "video_context_optimal",
            universe["source_bucket"].eq("kumo_with_george_video_context") & universe["trade_bucket"].eq("optimal"),
            ["best_entry_ret_20d_close_pct", "best_entry_mfe_20d_pct"],
            [False, False],
        ),
    ]
    for example_type, mask, sort_columns, ascending in specs:
        subset = universe[mask].copy()
        if subset.empty:
            continue
        subset = subset.sort_values(["scan_date", *sort_columns], ascending=[True, *ascending], na_position="last")
        subset = subset.groupby("scan_date", group_keys=False).head(examples_per_type_date).copy()
        subset["example_type"] = example_type
        frames.append(subset)
    if not frames:
        return pd.DataFrame(columns=EXAMPLE_COLUMNS)
    examples = pd.concat(frames, ignore_index=True)
    for column in EXAMPLE_COLUMNS:
        if column not in examples.columns:
            examples[column] = None
    return examples[EXAMPLE_COLUMNS].sort_values(["scan_date", "example_type", "symbol"]).reset_index(drop=True)


def bucket_comparison_summary(universe: pd.DataFrame) -> pd.DataFrame:
    summary = source_outcome_summary(universe)
    total_optimal = int(summary["optimal_rows"].sum())
    total_bad = int(summary["bad_rows"].sum())
    total_opportunities = int(summary["opportunities"].sum())
    summary["share_of_all_opportunities_pct"] = (summary["opportunities"] / total_opportunities * 100.0).round(3)
    summary["share_of_all_optimal_pct"] = (
        summary["optimal_rows"] / total_optimal * 100.0 if total_optimal else 0.0
    ).round(3)
    summary["share_of_all_bad_pct"] = (summary["bad_rows"] / total_bad * 100.0 if total_bad else 0.0).round(3)
    return summary


def denominator_diagnostics(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    frame["has_kumo_rank"] = frame["kumo_rank_by_score"].notna()
    frame["has_kumo_score"] = frame["kumo_score"].notna()
    frame["has_model_score"] = frame["model_combined_score"].notna()
    frame["has_deployable_exit"] = frame["best_deployable_total_equity_ret_40d_pct"].notna()
    frame["has_strict_entry"] = frame["strict_triggered_entry_count"].fillna(0).gt(0)
    grouped = frame.groupby("source_bucket", dropna=False)
    summary = grouped.agg(
        opportunities=("opportunity_id", "count"),
        missing_kumo_rank_rows=("has_kumo_rank", lambda series: int((~series).sum())),
        missing_kumo_score_rows=("has_kumo_score", lambda series: int((~series).sum())),
        missing_model_score_rows=("has_model_score", lambda series: int((~series).sum())),
        missing_deployable_exit_rows=("has_deployable_exit", lambda series: int((~series).sum())),
        strict_entry_rows=("has_strict_entry", "sum"),
    ).reset_index()
    for pct_column, count_column in [
        ("missing_kumo_rank_pct", "missing_kumo_rank_rows"),
        ("missing_kumo_score_pct", "missing_kumo_score_rows"),
        ("missing_model_score_pct", "missing_model_score_rows"),
        ("missing_deployable_exit_pct", "missing_deployable_exit_rows"),
        ("strict_entry_pct", "strict_entry_rows"),
    ]:
        summary[pct_column] = (summary[count_column] / summary["opportunities"] * 100.0).round(3)
    summary["diagnostic_note"] = summary["source_bucket"].map(
        {
            "george_only": "Not source-comparable: Kumo rank/score/model fields are structurally absent for George-only rows.",
            "both_george_and_kumo": "Partially comparable, but many rows are targeted/George rows without full Kumo rank fields.",
            "kumo_with_george_video_context": "Kumo row with video context only; not George scanner/watchlist evidence.",
            "kumo_only": "Primary Kumo-centered denominator.",
        }
    ).fillna("")
    return summary.sort_values(["opportunities", "source_bucket"], ascending=[False, True]).reset_index(drop=True)


def _markdown_table(frame: pd.DataFrame, *, max_rows: int = 20) -> str:
    if frame.empty:
        return "_No rows._"
    text_frame = frame.head(max_rows).fillna("").astype(str)
    columns = list(text_frame.columns)
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = ["| " + " | ".join(str(row[column]) for column in columns) + " |" for _, row in text_frame.iterrows()]
    return "\n".join([header, separator, *rows])


def write_report(
    *,
    universe: pd.DataFrame,
    source_summary: pd.DataFrame,
    reason_summary: pd.DataFrame,
    missed: pd.DataFrame,
    high_risk: pd.DataFrame,
    examples: pd.DataFrame,
    denominator: pd.DataFrame,
    output_dir: Path,
    config: DiagnosticsConfig,
) -> None:
    bucket_counts = universe["trade_bucket"].value_counts().rename_axis("trade_bucket").reset_index(name="rows")
    top_reasons = reason_summary.sort_values("rows", ascending=False).head(20)

    def metric(bucket: str, column: str, default: Any = "") -> Any:
        row = source_summary[source_summary["source_bucket"].eq(bucket)]
        if row.empty or column not in row.columns:
            return default
        value = row.iloc[0][column]
        if pd.isna(value):
            return default
        return value

    lines = [
        "# Scanner Source Diagnostics #485",
        "",
        "This report compares George and Kumo scanner source buckets using the #482 trade universe.",
        "",
        "## Inputs",
        "",
        f"- Trade universe: `{config.universe}`",
        "",
        "## Coverage",
        "",
        f"- Opportunities: `{len(universe)}`",
        f"- Dates: `{universe['scan_date'].nunique()}`",
        f"- Symbols: `{universe['symbol'].nunique()}`",
        "",
        "## Trade Buckets",
        "",
        _markdown_table(bucket_counts),
        "",
        "## Source Outcome Summary",
        "",
        _markdown_table(source_summary),
        "",
        "## Denominator Diagnostics",
        "",
        _markdown_table(denominator),
        "",
        "## Top Reason Codes",
        "",
        _markdown_table(top_reasons),
        "",
        "## Miss / Trap Counts",
        "",
        f"- Missed optimal trades: `{len(missed)}`",
        f"- High-risk false positives: `{len(high_risk)}`",
        f"- Daily examples: `{len(examples)}`",
        "",
        "## Key Findings",
        "",
        f"- Kumo-only rows provide `{metric('kumo_only', 'share_of_all_optimal_pct')}`% of all optimal rows and `{metric('kumo_only', 'share_of_all_bad_pct')}`% of all bad rows inside this Kumo-centered artifact.",
        f"- The George-only optimal share (`{metric('george_only', 'share_of_all_optimal_pct')}`%) is not a fair George-quality metric because the route/feature denominator is not source-balanced.",
        f"- Shared George+Kumo rows have `{metric('both_george_and_kumo', 'watch_pct')}`% watch rows and only `{metric('both_george_and_kumo', 'optimal_pct')}`% optimal rows.",
        f"- Kumo rows with George video context have `{metric('kumo_with_george_video_context', 'optimal_pct')}`% optimal rows, but video context is not scanner/watchlist evidence.",
        "",
        "## Actionable Interpretation",
        "",
        "- Do not use this report to conclude that George-only rows are weak; use it to show the current artifact is Kumo-centered.",
        "- Before #483 trains a source-comparison model, rebuild a fair route panel for George scanner/watchlist rows with the same entry/exit label coverage as Kumo rows.",
        "- If we proceed directly to #483 without that rebuild, scope it explicitly as a Kumo ranking/risk-filter model, not a George-vs-Kumo source model.",
        "- Shared overlap is not sufficient as a buy signal in the current artifact; many shared rows never get a realistic entry or still classify as bad trades.",
        "- George video-only context remains separated from George scanner/watchlist evidence.",
        "",
        "## Caveats",
        "",
        "- This analysis does not retrain or relabel; it consumes #482 labels.",
        "- Exit-policy metrics inherit the #482 caveat that deployable exits are anchored to next-open path labels.",
        "- Source-share percentages are not source-quality percentages because #482 inherits the #465 `kumo_top100_or_george` candidate filter and Kumo-ranker feature surface.",
    ]
    (output_dir / "scanner_source_diagnostics_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(output_dir: Path) -> None:
    text = (
        "# scanner_source_diagnostics_485/\n\n"
        "Generated diagnostics for comparing George and Kumo source buckets from the #482 trade universe.\n"
        "Keep compact CSV summaries, examples, manifest, and the report here.\n"
        "Do not store raw intraday data, model artifacts, or bulky sweep run folders here.\n"
    )
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def build(config: DiagnosticsConfig) -> dict[str, Any]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    universe = read_universe(Path(config.universe))
    source_summary = bucket_comparison_summary(universe)
    denominator = denominator_diagnostics(universe)
    reasons = reason_code_summary(universe)
    missed = missed_optimal_trades(universe)
    high_risk = high_risk_false_positives(universe)
    examples = daily_source_examples(universe, examples_per_type_date=config.examples_per_type_date)

    source_summary.to_csv(output_dir / "source_outcome_summary.csv", index=False)
    denominator.to_csv(output_dir / "denominator_diagnostics.csv", index=False)
    reasons.to_csv(output_dir / "reason_code_summary.csv", index=False)
    missed.to_csv(output_dir / "missed_optimal_trades.csv", index=False)
    high_risk.to_csv(output_dir / "high_risk_false_positives.csv", index=False)
    examples.to_csv(output_dir / "daily_source_examples.csv", index=False)
    write_readme(output_dir)
    write_report(
        universe=universe,
        source_summary=source_summary,
        reason_summary=reasons,
        missed=missed,
        high_risk=high_risk,
        examples=examples,
        denominator=denominator,
        output_dir=output_dir,
        config=config,
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/485",
        "config": asdict(config),
        "outputs": {
            "source_outcome_summary.csv": {"rows": int(len(source_summary))},
            "denominator_diagnostics.csv": {"rows": int(len(denominator))},
            "reason_code_summary.csv": {"rows": int(len(reasons))},
            "missed_optimal_trades.csv": {"rows": int(len(missed))},
            "high_risk_false_positives.csv": {"rows": int(len(high_risk))},
            "daily_source_examples.csv": {"rows": int(len(examples))},
            "scanner_source_diagnostics_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    args = _args()
    config = DiagnosticsConfig(
        universe=str(args.universe),
        output_dir=str(args.output_dir),
        examples_per_type_date=args.examples_per_type_date,
    )
    manifest = build(config)
    print(json.dumps(manifest["outputs"], indent=2))


if __name__ == "__main__":
    main()
