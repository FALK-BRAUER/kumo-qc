"""Build the #489 George-first scanner/watchlist trade universe.

This artifact mirrors the #482 trade-bucket labeling path, but it changes the
candidate denominator: a row is eligible only when George scanner or watchlist
evidence was visible at scan time. George video mentions are retained as context,
not as trainable scanner evidence.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_scanner_trade_universe as scanner

DEFAULT_PANEL = ROOT / "sweeps" / "reports" / "scanner_opportunity_panel_463" / "opportunity_panel.csv.gz"
DEFAULT_ENTRY_LABELS = ROOT / "sweeps" / "reports" / "scanner_entry_replay_465" / "alternate_entry_labels.csv.gz"
DEFAULT_EXIT_LABELS = ROOT / "sweeps" / "reports" / "scanner_exit_policies_466" / "exit_policy_labels.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "george_scanner_trade_universe_489"

CLASSIFICATION_VERSION = "george_scanner_trade_universe_v1"
TRAINING_MIN_CLASS_ROWS = 100

PANEL_USECOLS = [
    "scan_date",
    "symbol",
    "kumo_scanner",
    "kumo_top_n",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "company_sector",
    "company_industry",
    "sector_category",
    "sector_etf_proxy",
    "source_tags",
]

MODEL_COLUMNS = {
    "feature_version",
    "feature_hash",
    "oof_available",
    "target_trade_worthy",
    "target_runner",
    "target_fail_risk",
    "baseline_kumo_rank_score",
    "baseline_kumo_score",
    "baseline_rule_score",
    "model_trade_worthy_score",
    "model_runner_score",
    "model_combined_score",
}

BASE_OUTPUT_COLUMNS = [column for column in scanner.OUTPUT_COLUMNS if column not in MODEL_COLUMNS]
GEORGE_OUTPUT_COLUMNS: list[str] = []
for output_column in BASE_OUTPUT_COLUMNS:
    GEORGE_OUTPUT_COLUMNS.append(output_column)
    if output_column == "source_bucket":
        GEORGE_OUTPUT_COLUMNS.append("trainable_scanner_evidence")


@dataclass(frozen=True)
class BuildConfig:
    panel: str
    entry_labels: str
    exit_labels: str
    output_dir: str
    limit: int | None
    classification_version: str
    training_min_class_rows: int


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--entry-labels", type=Path, default=DEFAULT_ENTRY_LABELS)
    parser.add_argument("--exit-labels", type=Path, default=DEFAULT_EXIT_LABELS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Optional George candidate limit for smoke runs.")
    return parser.parse_args()


def _write_csv_gz(frame: pd.DataFrame, path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        frame.to_csv(fh, index=False)


def _bool_column(frame: pd.DataFrame, column: str) -> pd.Series:
    return scanner._bool_series(frame[column] if column in frame.columns else None, index=frame.index)


def _num_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([None] * len(frame), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce")


def read_panel(path: Path) -> pd.DataFrame:
    frame = scanner._read_csv(path, usecols=PANEL_USECOLS)
    frame["scan_date"] = frame["scan_date"].map(scanner._clean_date)
    frame["symbol"] = frame["symbol"].map(scanner._clean_symbol)
    frame = frame[(frame["scan_date"] != "") & (frame["symbol"] != "")].copy()
    frame["opportunity_id"] = frame["scan_date"] + "|" + frame["symbol"]
    for column in [
        "kumo_scanner",
        "kumo_top_n",
        "george_scanner_positive",
        "george_watchlist",
        "george_video_mention",
    ]:
        frame[column] = _bool_column(frame, column)
    for column in ["kumo_rank_by_score", "kumo_score", "george_rank", "george_watchlist_rank"]:
        frame[column] = _num_column(frame, column)
    return frame.drop_duplicates("opportunity_id", keep="first").reset_index(drop=True)


def george_signal_mask(frame: pd.DataFrame) -> pd.Series:
    return _bool_column(frame, "george_scanner_positive") | _bool_column(frame, "george_watchlist")


def candidate_opportunity_ids(panel: pd.DataFrame, *, limit: int | None = None) -> set[str]:
    candidates = panel.loc[george_signal_mask(panel), "opportunity_id"].drop_duplicates()
    if limit is not None:
        candidates = candidates.head(limit)
    return set(candidates.astype(str))


def filter_george_entries(entries: pd.DataFrame, panel: pd.DataFrame, *, limit: int | None = None) -> pd.DataFrame:
    candidate_ids = candidate_opportunity_ids(panel, limit=limit)
    return entries[entries["opportunity_id"].astype(str).isin(candidate_ids)].copy().reset_index(drop=True)


def add_george_source_buckets(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    frame["george_signal_seen"] = _bool_column(frame, "george_scanner_positive") | _bool_column(frame, "george_watchlist")
    frame["trainable_scanner_evidence"] = frame["george_signal_seen"]
    frame["kumo_signal_seen"] = _bool_column(frame, "kumo_scanner")
    frame["george_video_only_context"] = _bool_column(frame, "george_video_mention") & ~frame["george_signal_seen"]
    frame["both_george_and_kumo"] = frame["george_signal_seen"] & frame["kumo_signal_seen"]

    def bucket(row: pd.Series) -> str:
        if not bool(row["george_signal_seen"]):
            if bool(row["george_video_only_context"]):
                return "video_only_context"
            return "other"
        if bool(row["both_george_and_kumo"]):
            return "both_george_and_kumo"
        if bool(row.get("george_video_mention", False)):
            return "george_with_video_context"
        return "george_only"

    frame["source_bucket"] = frame.apply(bucket, axis=1)
    return frame


def add_george_trade_classification(universe: pd.DataFrame) -> pd.DataFrame:
    frame = universe.copy()
    classifications = frame.apply(scanner.classify_trade, axis=1)
    frame["trade_bucket"] = [item[0] for item in classifications]
    frame["reason_codes"] = [item[1] for item in classifications]
    frame["classification_version"] = CLASSIFICATION_VERSION
    return frame


def build_george_trade_universe(
    *,
    entries: pd.DataFrame,
    panel: pd.DataFrame,
    exits: pd.DataFrame,
    limit: int | None = None,
) -> pd.DataFrame:
    george_entries = filter_george_entries(entries, panel, limit=limit)
    if george_entries.empty:
        return pd.DataFrame(columns=[*GEORGE_OUTPUT_COLUMNS, "classification_version"])

    universe = scanner.aggregate_entries(george_entries)
    metadata = panel[
        [
            "opportunity_id",
            "company_sector",
            "company_industry",
            "sector_category",
            "sector_etf_proxy",
        ]
    ].drop_duplicates("opportunity_id", keep="first")
    universe = universe.merge(metadata, on="opportunity_id", how="left")

    exit_summary = scanner.aggregate_exits(exits)
    if not exit_summary.empty:
        universe = universe.merge(exit_summary, on="opportunity_id", how="left")
    else:
        universe["exit_policy_entry_assumption"] = ""

    universe = add_george_source_buckets(universe)
    universe = add_george_trade_classification(universe)
    for column in GEORGE_OUTPUT_COLUMNS:
        if column not in universe.columns:
            universe[column] = None
    return universe[[*GEORGE_OUTPUT_COLUMNS, "classification_version"]].sort_values(
        ["scan_date", "symbol"]
    ).reset_index(drop=True)


def source_summary(universe: pd.DataFrame) -> pd.DataFrame:
    if universe.empty:
        return pd.DataFrame()
    frame = universe.copy()
    frame["is_optimal"] = frame["trade_bucket"].eq("optimal")
    frame["is_bad"] = frame["trade_bucket"].eq("bad")
    frame["is_watch"] = frame["trade_bucket"].eq("watch")
    frame["has_trigger"] = frame["triggered_entry_count"].fillna(0).astype(int).gt(0)
    frame["has_deployable_exit"] = frame["best_deployable_exit_policy_id"].fillna("").astype(str).ne("")
    frame["has_video_context"] = _bool_column(frame, "george_video_mention")
    frame["missing_kumo_rank"] = frame["kumo_rank_by_score"].isna()
    frame["missing_kumo_score"] = frame["kumo_score"].isna()
    grouped = frame.groupby("source_bucket", dropna=False)
    summary = grouped.agg(
        opportunities=("opportunity_id", "count"),
        dates=("scan_date", "nunique"),
        symbols=("symbol", "nunique"),
        triggered_rows=("has_trigger", "sum"),
        deployable_exit_rows=("has_deployable_exit", "sum"),
        optimal_rows=("is_optimal", "sum"),
        bad_rows=("is_bad", "sum"),
        watch_rows=("is_watch", "sum"),
        video_context_rows=("has_video_context", "sum"),
        missing_kumo_rank_rows=("missing_kumo_rank", "sum"),
        missing_kumo_score_rows=("missing_kumo_score", "sum"),
        avg_best_entry_ret20_pct=("best_entry_ret_20d_close_pct", "mean"),
        avg_best_entry_mae20_pct=("best_entry_mae_20d_pct", "mean"),
        avg_best_deployable_exit_total40_pct=("best_deployable_total_equity_ret_40d_pct", "mean"),
    ).reset_index()
    for pct_column, count_column in [
        ("trigger_rate_pct", "triggered_rows"),
        ("deployable_exit_coverage_pct", "deployable_exit_rows"),
        ("optimal_pct", "optimal_rows"),
        ("bad_pct", "bad_rows"),
        ("watch_pct", "watch_rows"),
        ("missing_kumo_rank_pct", "missing_kumo_rank_rows"),
        ("missing_kumo_score_pct", "missing_kumo_score_rows"),
    ]:
        summary[pct_column] = (summary[count_column] / summary["opportunities"] * 100.0).round(3)
    numeric_cols = [
        "avg_best_entry_ret20_pct",
        "avg_best_entry_mae20_pct",
        "avg_best_deployable_exit_total40_pct",
    ]
    summary[numeric_cols] = summary[numeric_cols].round(4)
    return summary.sort_values(["opportunities", "source_bucket"], ascending=[False, True]).reset_index(drop=True)


def coverage_summary(panel: pd.DataFrame, entries: pd.DataFrame, exits: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    panel_unique = panel.drop_duplicates("opportunity_id", keep="first").copy()
    entry_ids = set(entries["opportunity_id"].dropna().astype(str).unique())
    exit_ids = set(exits["opportunity_id"].dropna().astype(str).unique()) if "opportunity_id" in exits.columns else set()
    universe_ids = set(universe["opportunity_id"].dropna().astype(str).unique()) if not universe.empty else set()

    george_signal = george_signal_mask(panel_unique)
    video = _bool_column(panel_unique, "george_video_mention")
    kumo = _bool_column(panel_unique, "kumo_scanner")
    candidate_ids = set(panel_unique.loc[george_signal, "opportunity_id"].astype(str))

    def row(
        category: str,
        ids: set[str],
        *,
        included: bool,
        trainable: bool,
        note: str,
    ) -> dict[str, object]:
        return {
            "category": category,
            "opportunities": len(ids),
            "included_in_universe": included,
            "trainable_scanner_evidence": trainable,
            "with_entry_labels": len(ids & entry_ids),
            "with_exit_policy_labels": len(ids & exit_ids),
            "in_universe": len(ids & universe_ids),
            "note": note,
        }

    all_ids = set(panel_unique["opportunity_id"].astype(str))
    scanner_ids = set(panel_unique.loc[_bool_column(panel_unique, "george_scanner_positive"), "opportunity_id"].astype(str))
    watchlist_ids = set(panel_unique.loc[_bool_column(panel_unique, "george_watchlist"), "opportunity_id"].astype(str))
    both_ids = set(panel_unique.loc[george_signal & kumo, "opportunity_id"].astype(str))
    george_only_ids = set(panel_unique.loc[george_signal & ~kumo & ~video, "opportunity_id"].astype(str))
    george_video_ids = set(panel_unique.loc[george_signal & ~kumo & video, "opportunity_id"].astype(str))
    video_only_ids = set(panel_unique.loc[~george_signal & video, "opportunity_id"].astype(str))
    non_george_ids = set(panel_unique.loc[~george_signal & ~video, "opportunity_id"].astype(str))
    missing_entry_ids = candidate_ids - entry_ids
    missing_exit_ids = candidate_ids - exit_ids
    no_entry_ids = (
        set(universe.loc[universe["triggered_entry_count"].fillna(0).astype(int).eq(0), "opportunity_id"].astype(str))
        if not universe.empty
        else set()
    )

    return pd.DataFrame(
        [
            row("all_panel_opportunities", all_ids, included=False, trainable=False, note="Full #463 denominator."),
            row(
                "george_scanner_or_watchlist_candidates",
                candidate_ids,
                included=True,
                trainable=True,
                note="Rows where george_scanner_positive or george_watchlist is true.",
            ),
            row("george_scanner_positive", scanner_ids, included=True, trainable=True, note="Scanner-positive subset."),
            row("george_watchlist", watchlist_ids, included=True, trainable=True, note="Watchlist subset."),
            row("both_george_and_kumo", both_ids, included=True, trainable=True, note="George evidence overlaps Kumo scanner."),
            row("george_only", george_only_ids, included=True, trainable=True, note="George evidence with no Kumo scanner flag."),
            row(
                "george_with_video_context",
                george_video_ids,
                included=True,
                trainable=True,
                note="George scanner/watchlist evidence plus video context.",
            ),
            row(
                "video_only_context_excluded",
                video_only_ids,
                included=False,
                trainable=False,
                note="George video mention without scanner/watchlist evidence; excluded from trainable universe.",
            ),
            row(
                "non_george_context_excluded",
                non_george_ids,
                included=False,
                trainable=False,
                note="No George scanner/watchlist or video context.",
            ),
            row(
                "candidate_missing_entry_labels",
                missing_entry_ids,
                included=False,
                trainable=False,
                note="George candidates lacking #465 realistic-entry labels.",
            ),
            row(
                "candidate_missing_exit_policy_labels",
                missing_exit_ids,
                included=False,
                trainable=False,
                note="George candidates lacking #466 exit-policy labels.",
            ),
            row(
                "universe_no_realistic_entry",
                no_entry_ids,
                included=True,
                trainable=True,
                note="Included candidates with no realistic entry trigger; labeled watch.",
            ),
        ]
    )


def reason_code_summary(universe: pd.DataFrame) -> pd.DataFrame:
    if universe.empty:
        return pd.DataFrame(columns=["source_bucket", "trade_bucket", "reason_code", "rows", "pct_of_bucket_trade"])
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


def bucket_rows(universe: pd.DataFrame, *, bucket: str) -> pd.DataFrame:
    return scanner._bucket_rows(universe, bucket=bucket)


def training_readiness(universe: pd.DataFrame, *, min_class_rows: int = TRAINING_MIN_CLASS_ROWS) -> dict[str, Any]:
    counts = universe["trade_bucket"].value_counts() if not universe.empty else pd.Series(dtype=int)
    optimal_rows = int(counts.get("optimal", 0))
    bad_rows = int(counts.get("bad", 0))
    ready = optimal_rows >= min_class_rows and bad_rows >= min_class_rows
    return {
        "min_class_rows": min_class_rows,
        "optimal_rows": optimal_rows,
        "bad_rows": bad_rows,
        "ready_for_george_model": ready,
        "status": "unblocked" if ready else "insufficient_labeled_examples",
    }


def _markdown_table(frame: pd.DataFrame) -> str:
    return scanner._markdown_table(frame)


def write_report(
    *,
    universe: pd.DataFrame,
    source: pd.DataFrame,
    coverage: pd.DataFrame,
    reasons: pd.DataFrame,
    readiness: dict[str, Any],
    output_dir: Path,
    config: BuildConfig,
) -> None:
    bucket_counts = universe["trade_bucket"].value_counts().rename_axis("trade_bucket").reset_index(name="rows")
    source_counts = universe["source_bucket"].value_counts().rename_axis("source_bucket").reset_index(name="rows")
    coverage_gaps = coverage[
        coverage["category"].isin(
            [
                "candidate_missing_entry_labels",
                "candidate_missing_exit_policy_labels",
                "video_only_context_excluded",
                "universe_no_realistic_entry",
            ]
        )
    ]
    if readiness["ready_for_george_model"]:
        readiness_text = (
            f"#483 is unblocked for a first George-only model under the pragmatic "
            f">= {readiness['min_class_rows']} rows per class threshold."
        )
    else:
        readiness_text = (
            f"#483 should stay blocked for George-only training under the pragmatic "
            f">= {readiness['min_class_rows']} rows per class threshold."
        )

    top_reasons = reasons.sort_values("rows", ascending=False).head(20) if not reasons.empty else reasons
    lines = [
        "# George Scanner Trade Universe #489",
        "",
        "This report builds a George-first scanner/watchlist trade universe from #463 evidence,",
        "joins #465 realistic-entry labels and #466 deployable exit-policy outcomes, and applies",
        "the #482 optimal/bad/watch classification logic.",
        "",
        "George video mentions are context only. They are not treated as George scanner evidence.",
        "Kumo rank, score, and model fields are not required and are not used for classification.",
        "",
        "## Inputs",
        "",
        f"- Panel: `{config.panel}`",
        f"- Entry labels: `{config.entry_labels}`",
        f"- Exit labels: `{config.exit_labels}`",
        "- Ranker/model predictions: not joined for #489.",
        "",
        "## Coverage",
        "",
        f"- Opportunities: `{len(universe)}`",
        f"- Dates: `{universe['scan_date'].nunique() if not universe.empty else 0}`",
        f"- Symbols: `{universe['symbol'].nunique() if not universe.empty else 0}`",
        f"- Classification version: `{config.classification_version}`",
        "",
        "## Trade Buckets",
        "",
        _markdown_table(bucket_counts),
        "",
        "## Source Buckets",
        "",
        _markdown_table(source_counts),
        "",
        "## Source Summary",
        "",
        _markdown_table(source),
        "",
        "## Coverage Gaps",
        "",
        _markdown_table(coverage_gaps),
        "",
        "## Top Reason Codes",
        "",
        _markdown_table(top_reasons),
        "",
        "## #483 Training Readiness",
        "",
        f"- Optimal rows: `{readiness['optimal_rows']}`",
        f"- Bad rows: `{readiness['bad_rows']}`",
        f"- Threshold used: `{readiness['min_class_rows']}` per class",
        f"- Status: `{readiness['status']}`",
        f"- Conclusion: {readiness_text}",
        "",
        "## Caveats",
        "",
        "- `best_entry_*` is selected from #465 realistic entry replay assumptions.",
        "- `best_deployable_exit_*` comes from #466 exit-policy labels and preserves the same",
        "  `exit_policy_entry_assumption` meaning used by #482.",
        "- `optimal` and `bad` are research labels, not live trading rules.",
        "- Future path, entry, and exit columns are labels only; they must not be used as model features.",
    ]
    (output_dir / "george_scanner_trade_universe_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def write_readme(output_dir: Path) -> None:
    text = (
        "# george_scanner_trade_universe_489/\n\n"
        "Generated George-first scanner/watchlist trade-universe artifacts for issue #489.\n"
        "Keep the compressed universe, compact bucket CSVs, summaries, manifest, and report here.\n"
        "Do not place raw intraday data, model training artifacts, or unrelated sweep output here.\n"
    )
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def build(config: BuildConfig) -> dict[str, Any]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    panel = read_panel(Path(config.panel))
    entries = scanner.read_entry_labels(Path(config.entry_labels))
    exits = scanner.read_optional_frame(Path(config.exit_labels), usecols=scanner.EXIT_USECOLS)

    universe = build_george_trade_universe(entries=entries, panel=panel, exits=exits, limit=config.limit)
    source = source_summary(universe)
    coverage = coverage_summary(panel, entries, exits, universe)
    reasons = reason_code_summary(universe)
    optimal = bucket_rows(universe, bucket="optimal")
    bad = bucket_rows(universe, bucket="bad")
    watch = bucket_rows(universe, bucket="watch")
    readiness = training_readiness(universe, min_class_rows=config.training_min_class_rows)

    _write_csv_gz(universe, output_dir / "george_scanner_trade_universe.csv.gz")
    optimal.to_csv(output_dir / "george_optimal_trades.csv", index=False)
    bad.to_csv(output_dir / "george_bad_trades.csv", index=False)
    watch.to_csv(output_dir / "george_watch_trades.csv", index=False)
    source.to_csv(output_dir / "george_source_summary.csv", index=False)
    coverage.to_csv(output_dir / "george_coverage_summary.csv", index=False)
    reasons.to_csv(output_dir / "george_reason_code_summary.csv", index=False)
    write_readme(output_dir)
    write_report(
        universe=universe,
        source=source,
        coverage=coverage,
        reasons=reasons,
        readiness=readiness,
        output_dir=output_dir,
        config=config,
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/489",
        "config": asdict(config),
        "training_readiness": readiness,
        "outputs": {
            "george_scanner_trade_universe.csv.gz": {"rows": int(len(universe))},
            "george_optimal_trades.csv": {"rows": int(len(optimal))},
            "george_bad_trades.csv": {"rows": int(len(bad))},
            "george_watch_trades.csv": {"rows": int(len(watch))},
            "george_source_summary.csv": {"rows": int(len(source))},
            "george_coverage_summary.csv": {"rows": int(len(coverage))},
            "george_reason_code_summary.csv": {"rows": int(len(reasons))},
            "george_scanner_trade_universe_report.md": {},
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    args = _args()
    config = BuildConfig(
        panel=str(args.panel),
        entry_labels=str(args.entry_labels),
        exit_labels=str(args.exit_labels),
        output_dir=str(args.output_dir),
        limit=args.limit,
        classification_version=CLASSIFICATION_VERSION,
        training_min_class_rows=TRAINING_MIN_CLASS_ROWS,
    )
    manifest = build(config)
    print(json.dumps(manifest["outputs"], indent=2))


if __name__ == "__main__":
    main()
