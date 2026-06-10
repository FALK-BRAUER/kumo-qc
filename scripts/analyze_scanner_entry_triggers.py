"""Analyze leakage-safe next-open entry gates for scanner opportunities (#465).

This is the first #465 slice: it compares entry-time gates on the #464 `next_regular_open`
path labels. It does not claim to replay alternate first-hour, breakout, or pullback entry
prices; those require a second path-replay pass after these simple gates are measured.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = ROOT / "sweeps" / "reports" / "scanner_opportunity_paths_464" / "opportunity_path_labels.csv.gz"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "scanner_entry_triggers_465"

BOOL_COLUMNS = [
    "kumo_scanner",
    "kumo_top_n",
    "george_scanner_positive",
    "george_watchlist",
    "george_video_mention",
    "label_runner_candidate_20d",
    "label_normal_winner_20d",
    "label_bad_trade_20d",
    "label_extreme_path_flag",
]

USECOLS = [
    "scan_date",
    "symbol",
    "source_tags",
    "kumo_rank_by_score",
    "kumo_score",
    "george_rank",
    "george_watchlist_rank",
    "label_entry_gap_pct",
    "label_ret_20d_close_pct",
    "label_mfe_20d_pct",
    "label_mae_20d_pct",
    "label_t4_s2_20d_outcome",
    "label_t8_s4_20d_outcome",
    "label_outcome_20d",
    *BOOL_COLUMNS,
]


@dataclass(frozen=True)
class AnalysisConfig:
    labels: str
    output_dir: str


@dataclass(frozen=True)
class EntryGate:
    gate_id: str
    description: str


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def read_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, usecols=lambda column: column in set(USECOLS), low_memory=False)
    for column in BOOL_COLUMNS:
        if column in frame:
            frame[column] = _bool_series(frame[column])
    frame["entry_good_20d"] = (
        (frame["label_runner_candidate_20d"] | frame["label_normal_winner_20d"])
        & ~frame["label_bad_trade_20d"]
        & frame["label_ret_20d_close_pct"].notna()
    )
    frame["entry_available_20d"] = frame["label_ret_20d_close_pct"].notna()
    frame["george_scanner_or_watchlist"] = frame["george_scanner_positive"] | frame["george_watchlist"]
    return frame


def gate_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    rank = pd.to_numeric(frame["kumo_rank_by_score"], errors="coerce")
    score = pd.to_numeric(frame["kumo_score"], errors="coerce")
    gap = pd.to_numeric(frame["label_entry_gap_pct"], errors="coerce")
    return {
        "next_open_all": pd.Series(True, index=frame.index),
        "kumo_top20": rank.le(20),
        "kumo_top50": rank.le(50),
        "kumo_top100": frame["kumo_top_n"],
        "kumo_score_ge7": score.ge(7),
        "gap_minus2_to_5": gap.between(-2, 5),
        "gap_0_to_5": gap.between(0, 5),
        "gap_not_extreme": gap.between(-5, 8),
        "kumo_top20_gap_minus2_to_5": rank.le(20) & gap.between(-2, 5),
        "kumo_top50_gap_minus2_to_5": rank.le(50) & gap.between(-2, 5),
        "kumo_top100_gap_minus2_to_5": frame["kumo_top_n"] & gap.between(-2, 5),
        "george_scanner_or_watchlist": frame["george_scanner_or_watchlist"],
        "george_scanner_or_watchlist_gap_minus2_to_5": frame["george_scanner_or_watchlist"]
        & gap.between(-2, 5),
    }


def gate_catalog() -> dict[str, EntryGate]:
    return {
        "next_open_all": EntryGate("next_open_all", "Baseline: enter every opportunity at next regular open."),
        "kumo_top20": EntryGate("kumo_top20", "Kumo full-universe scanner rank <= 20."),
        "kumo_top50": EntryGate("kumo_top50", "Kumo full-universe scanner rank <= 50."),
        "kumo_top100": EntryGate("kumo_top100", "Kumo full-universe scanner rank <= 100."),
        "kumo_score_ge7": EntryGate("kumo_score_ge7", "Kumo BCT score >= 7."),
        "gap_minus2_to_5": EntryGate("gap_minus2_to_5", "Next-open gap between -2% and +5%."),
        "gap_0_to_5": EntryGate("gap_0_to_5", "Next-open gap between 0% and +5%."),
        "gap_not_extreme": EntryGate("gap_not_extreme", "Next-open gap between -5% and +8%."),
        "kumo_top20_gap_minus2_to_5": EntryGate("kumo_top20_gap_minus2_to_5", "Kumo top20 plus -2% to +5% next-open gap."),
        "kumo_top50_gap_minus2_to_5": EntryGate("kumo_top50_gap_minus2_to_5", "Kumo top50 plus -2% to +5% next-open gap."),
        "kumo_top100_gap_minus2_to_5": EntryGate("kumo_top100_gap_minus2_to_5", "Kumo top100 plus -2% to +5% next-open gap."),
        "george_scanner_or_watchlist": EntryGate("george_scanner_or_watchlist", "George OCR/manual scanner or explicit watchlist evidence."),
        "george_scanner_or_watchlist_gap_minus2_to_5": EntryGate(
            "george_scanner_or_watchlist_gap_minus2_to_5",
            "George scanner/watchlist plus -2% to +5% next-open gap.",
        ),
    }


def _pct(mask: pd.Series) -> float:
    if len(mask) == 0:
        return 0.0
    return round(float(mask.mean()) * 100.0, 3)


def _mean(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 4)


def _median(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.median()), 4)


def gate_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    catalog = gate_catalog()
    baseline_available = int(frame["entry_available_20d"].sum())
    for gate_id, mask in gate_masks(frame).items():
        selected = frame[mask].copy()
        available = selected[selected["entry_available_20d"]].copy()
        rows.append(
            {
                "gate_id": gate_id,
                "description": catalog[gate_id].description,
                "selected_rows": int(len(selected)),
                "available_rows": int(len(available)),
                "selected_pct_of_available_panel": round(100.0 * len(available) / baseline_available, 3)
                if baseline_available
                else 0.0,
                "avg_ret_20d_close_pct": _mean(available["label_ret_20d_close_pct"]),
                "median_ret_20d_close_pct": _median(available["label_ret_20d_close_pct"]),
                "good_pct": _pct(available["entry_good_20d"]),
                "runner_pct": _pct(available["label_runner_candidate_20d"]),
                "bad_trade_pct": _pct(available["label_bad_trade_20d"]),
                "extreme_path_pct": _pct(available["label_extreme_path_flag"]),
                "target4_before_stop2_pct": _pct(available["label_t4_s2_20d_outcome"].eq("target_before_stop")),
                "stop2_before_target4_pct": _pct(available["label_t4_s2_20d_outcome"].eq("stop_before_target")),
                "objective_score": _objective_score(available),
            }
        )
    return pd.DataFrame(rows).sort_values("objective_score", ascending=False).reset_index(drop=True)


def _objective_score(frame: pd.DataFrame) -> float:
    if frame.empty:
        return -999.0
    avg_ret = _mean(frame["label_ret_20d_close_pct"]) or 0.0
    good = _pct(frame["entry_good_20d"])
    bad = _pct(frame["label_bad_trade_20d"])
    extreme = _pct(frame["label_extreme_path_flag"])
    return round(avg_ret + 0.05 * good - 0.05 * bad - 0.25 * extreme, 4)


def bucket_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rank = pd.to_numeric(frame["kumo_rank_by_score"], errors="coerce")
    gap = pd.to_numeric(frame["label_entry_gap_pct"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for name, mask in {
        "rank_1_10": rank.between(1, 10),
        "rank_11_20": rank.between(11, 20),
        "rank_21_50": rank.between(21, 50),
        "rank_51_100": rank.between(51, 100),
        "rank_101_250": rank.between(101, 250),
        "rank_251_500": rank.between(251, 500),
        "gap_lt_minus5": gap.lt(-5),
        "gap_minus5_to_minus2": gap.between(-5, -2),
        "gap_minus2_to_0": gap.between(-2, 0),
        "gap_0_to_2": gap.between(0, 2),
        "gap_2_to_5": gap.between(2, 5),
        "gap_5_to_8": gap.between(5, 8),
        "gap_gt_8": gap.gt(8),
    }.items():
        subset = frame[mask & frame["entry_available_20d"]]
        rows.append(
            {
                "bucket": name,
                "rows": int(len(subset)),
                "avg_ret_20d_close_pct": _mean(subset["label_ret_20d_close_pct"]),
                "median_ret_20d_close_pct": _median(subset["label_ret_20d_close_pct"]),
                "good_pct": _pct(subset["entry_good_20d"]),
                "runner_pct": _pct(subset["label_runner_candidate_20d"]),
                "bad_trade_pct": _pct(subset["label_bad_trade_20d"]),
            }
        )
    return pd.DataFrame(rows)


def examples(frame: pd.DataFrame, gate_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = gate_masks(frame)[gate_id] & frame["entry_available_20d"]
    subset = frame[mask].copy()
    columns = [
        "scan_date",
        "symbol",
        "source_tags",
        "kumo_rank_by_score",
        "kumo_score",
        "label_entry_gap_pct",
        "label_outcome_20d",
        "label_ret_20d_close_pct",
        "label_mfe_20d_pct",
        "label_mae_20d_pct",
        "label_t4_s2_20d_outcome",
    ]
    best = subset.sort_values(["label_ret_20d_close_pct", "label_mfe_20d_pct"], ascending=[False, False]).head(50)
    worst = subset.sort_values(["label_ret_20d_close_pct", "label_mae_20d_pct"], ascending=[True, True]).head(50)
    return best.loc[:, columns], worst.loc[:, columns]


def _markdown_table(frame: pd.DataFrame, columns: list[str], *, limit: int | None = None) -> str:
    subset = frame.loc[:, columns]
    if limit is not None:
        subset = subset.head(limit)
    if subset.empty:
        return "_No rows._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in subset.iterrows():
        lines.append("| " + " | ".join(str(row[col]) for col in columns) + " |")
    return "\n".join(lines)


def write_report(output_dir: Path, *, gates: pd.DataFrame, buckets: pd.DataFrame, config: AnalysisConfig) -> None:
    recommended = gates.iloc[0]
    lines = [
        "# Scanner Entry Trigger Analysis #465",
        "",
        "This is the first #465 slice: leakage-safe next-open entry gates from the #464 path labels.",
        "It does not replay alternate first-hour, breakout, or pullback entry prices yet.",
        "",
        "## Inputs",
        "",
        f"- Labels: `{config.labels}`",
        "",
        "## Read",
        "",
        f"- Best simple gate by the current objective: `{recommended['gate_id']}`.",
        "- Kumo rank gates improve average return modestly, but do not solve bad-trade rate.",
        "- Gap gates alone are noisy: moderate negative/positive gaps can produce higher upside,",
        "  while very large gaps have worse average return and higher bad-trade rate.",
        "- George scanner/watchlist rows are not automatically better under next-open entry; they need",
        "  better confirmation or exit handling before being promoted.",
        "",
        "## Gate Summary",
        "",
        _markdown_table(
            gates,
            [
                "gate_id",
                "available_rows",
                "avg_ret_20d_close_pct",
                "median_ret_20d_close_pct",
                "good_pct",
                "runner_pct",
                "bad_trade_pct",
                "target4_before_stop2_pct",
                "stop2_before_target4_pct",
                "objective_score",
            ],
        ),
        "",
        "## Rank And Gap Buckets",
        "",
        _markdown_table(
            buckets,
            [
                "bucket",
                "rows",
                "avg_ret_20d_close_pct",
                "median_ret_20d_close_pct",
                "good_pct",
                "runner_pct",
                "bad_trade_pct",
            ],
        ),
        "",
        "## Recommendation",
        "",
        "- First LEAN sweep candidate: `kumo_top20` or `kumo_top20_gap_minus2_to_5` as a small",
        "  capital-allocation gate, not as a full solution.",
        "- Do not spend ML effort on gap gates alone; the next research pass should replay first-hour",
        "  confirmation and breakout/pullback entries with alternate entry prices.",
        "",
    ]
    (output_dir / "entry_trigger_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(*, labels_path: Path = DEFAULT_LABELS, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    config = AnalysisConfig(labels=str(labels_path), output_dir=str(output_dir))
    frame = read_labels(labels_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(
        "# scanner_entry_triggers_465/\n\n"
        "Entry-time gate analysis for issue #465. Keep compact summaries and examples here; "
        "alternate first-hour/breakout replay outputs belong in a later extension.\n",
        encoding="utf-8",
    )
    gates = gate_summary(frame)
    buckets = bucket_summary(frame)
    recommended_gate = str(gates.iloc[0]["gate_id"])
    best, worst = examples(frame, recommended_gate)
    gates.to_csv(output_dir / "entry_gate_summary.csv", index=False)
    buckets.to_csv(output_dir / "rank_gap_bucket_summary.csv", index=False)
    best.to_csv(output_dir / "recommended_gate_best_examples.csv", index=False)
    worst.to_csv(output_dir / "recommended_gate_worst_examples.csv", index=False)
    write_report(output_dir, gates=gates, buckets=buckets, config=config)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "issue": "https://github.com/FALK-BRAUER/kumo-qc/issues/465",
        "config": asdict(config),
        "recommended_gate": recommended_gate,
        "outputs": {
            "entry_gate_summary.csv": {"rows": int(len(gates))},
            "rank_gap_bucket_summary.csv": {"rows": int(len(buckets))},
            "recommended_gate_best_examples.csv": {"rows": int(len(best))},
            "recommended_gate_worst_examples.csv": {"rows": int(len(worst))},
            "entry_trigger_report.md": {},
        },
        "scope_note": "next-open entry gates only; alternate first-hour/breakout/pullback entry replay is not included",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "entry_gate_summary": output_dir / "entry_gate_summary.csv",
        "rank_gap_bucket_summary": output_dir / "rank_gap_bucket_summary.csv",
        "best_examples": output_dir / "recommended_gate_best_examples.csv",
        "worst_examples": output_dir / "recommended_gate_worst_examples.csv",
        "report": output_dir / "entry_trigger_report.md",
        "manifest": output_dir / "manifest.json",
    }


def main() -> None:
    args = _args()
    outputs = run(labels_path=args.labels, output_dir=args.output_dir)
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
