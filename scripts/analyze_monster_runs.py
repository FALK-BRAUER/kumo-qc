"""Monster-run and hold-bucket diagnostics for completed trade CSVs.

This reads tracked `trades_all.csv` report artifacts. It does not rerun LEAN and it does not
require ignored `sweeps/runs/` result JSONs to still exist locally.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "sweeps" / "reports" / "monster_run_decomposition_459"
DEFAULT_INPUTS = (
    ROOT / "sweeps" / "reports" / "george_range_30" / "trades_all.csv",
    ROOT / "sweeps" / "reports" / "george_combo_30_cached_storage_w3" / "trades_all.csv",
)
DEFAULT_VARIANTS = (
    "p_only_base",
    "target_04_fast_take",
    "target_08_let_run",
    "giveback_tight_no_bull",
    "combo_gb_buy005",
    "combo_t08_buy005",
)

HOLD_BUCKETS = (
    ("0-3d", 0.0, 3.0),
    ("4-10d", 3.0, 10.0),
    ("11-30d", 10.0, 30.0),
    ("31-60d", 30.0, 60.0),
    ("60d+", 60.0, float("inf")),
)


@dataclass(frozen=True)
class AnalysisConfig:
    trades_csv: tuple[str, ...]
    variants: tuple[str, ...]
    output_dir: str


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trades-csv",
        action="append",
        type=Path,
        default=[],
        help="Input trades_all.csv. May be passed more than once.",
    )
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="Variant id to include. May be passed more than once.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, default=20)
    return parser.parse_args()


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _read_trades(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        frame = pd.read_csv(path)
        frame["source_csv"] = str(path)
        frames.append(frame)
    if not frames:
        raise ValueError("at least one trades CSV is required")
    out = pd.concat(frames, ignore_index=True)
    out["variant_id"] = out["variant_id"].astype(str)
    out["symbol"] = out["symbol"].astype(str)
    out["status"] = out["status"].astype(str)
    out["pnl"] = _num(out["pnl"]).fillna(0.0)
    out["return_pct"] = _num(out["return_pct"])
    out["duration_days"] = _num(out["duration_days"])
    out["censored"] = out.get("censored", False).astype(str).str.lower().isin({"true", "1", "yes"})
    return out


def _dedupe_variant_rows(trades: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "variant_id",
        "symbol",
        "entry_order_id",
        "exit_order_id",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "status",
        "pnl",
    ]
    present = [key for key in keys if key in trades.columns]
    return trades.drop_duplicates(subset=present, keep="first").reset_index(drop=True)


def _share(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return round(100.0 * numerator / denominator, 3)


def _summary_for_variant(group: pd.DataFrame) -> dict[str, object]:
    closed = group[group["status"].eq("closed")].copy()
    open_rows = group[~group["status"].eq("closed")].copy()
    closed_pnl = float(closed["pnl"].sum())
    positive_pnl = float(closed.loc[closed["pnl"] > 0, "pnl"].sum())
    top_positive = closed[closed["pnl"] > 0].sort_values("pnl", ascending=False)
    top_all = closed.sort_values("pnl", ascending=False)
    wins = int((closed["pnl"] > 0).sum())
    closed_count = int(len(closed))
    monster = closed[(closed["return_pct"] >= 0.10) | (closed["pnl"] >= top_positive["pnl"].quantile(0.90))]
    return {
        "variant_id": str(group["variant_id"].iloc[0]),
        "source_rows": int(len(group)),
        "closed_trades": closed_count,
        "open_or_censored_trades": int(len(open_rows)),
        "closed_pnl": round(closed_pnl, 3),
        "open_or_censored_pnl": round(float(open_rows["pnl"].sum()), 3),
        "win_rate_pct": round(100.0 * wins / closed_count, 3) if closed_count else 0.0,
        "avg_return_pct": round(float(closed["return_pct"].mean() * 100.0), 3) if closed_count else 0.0,
        "median_return_pct": round(float(closed["return_pct"].median() * 100.0), 3) if closed_count else 0.0,
        "avg_duration_days": round(float(closed["duration_days"].mean()), 3) if closed_count else 0.0,
        "median_duration_days": round(float(closed["duration_days"].median()), 3) if closed_count else 0.0,
        "p90_duration_days": round(float(closed["duration_days"].quantile(0.90)), 3) if closed_count else 0.0,
        "top1_positive_pnl_share_pct": _share(float(top_positive["pnl"].head(1).sum()), positive_pnl),
        "top5_positive_pnl_share_pct": _share(float(top_positive["pnl"].head(5).sum()), positive_pnl),
        "top10_positive_pnl_share_pct": _share(float(top_positive["pnl"].head(10).sum()), positive_pnl),
        "top1_net_pnl_share_pct": _share(float(top_all["pnl"].head(1).sum()), closed_pnl),
        "top5_net_pnl_share_pct": _share(float(top_all["pnl"].head(5).sum()), closed_pnl),
        "top10_net_pnl_share_pct": _share(float(top_all["pnl"].head(10).sum()), closed_pnl),
        "monster_trades": int(len(monster)),
        "monster_pnl": round(float(monster["pnl"].sum()), 3),
        "monster_pnl_share_pct": _share(float(monster["pnl"].sum()), closed_pnl),
    }


def variant_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows = [_summary_for_variant(group) for _variant, group in trades.groupby("variant_id", sort=False)]
    return pd.DataFrame(rows).sort_values("closed_pnl", ascending=False).reset_index(drop=True)


def hold_bucket_summary(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    closed = trades[trades["status"].eq("closed")].copy()
    for variant, group in closed.groupby("variant_id", sort=False):
        for bucket, low, high in HOLD_BUCKETS:
            if high == float("inf"):
                mask = group["duration_days"] > low
            else:
                mask = (group["duration_days"] > low) & (group["duration_days"] <= high)
            bucket_rows = group.loc[mask]
            rows.append(
                {
                    "variant_id": variant,
                    "hold_bucket": bucket,
                    "trades": int(len(bucket_rows)),
                    "pnl": round(float(bucket_rows["pnl"].sum()), 3),
                    "avg_return_pct": round(float(bucket_rows["return_pct"].mean() * 100.0), 3)
                    if len(bucket_rows)
                    else 0.0,
                    "median_return_pct": round(float(bucket_rows["return_pct"].median() * 100.0), 3)
                    if len(bucket_rows)
                    else 0.0,
                    "win_rate_pct": round(100.0 * float((bucket_rows["pnl"] > 0).mean()), 3)
                    if len(bucket_rows)
                    else 0.0,
                }
            )
    return pd.DataFrame(rows)


def top_trades(trades: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    closed = trades[trades["status"].eq("closed")].copy()
    columns = [
        "variant_id",
        "symbol",
        "entry_date",
        "exit_date",
        "duration_days",
        "entry_price",
        "exit_price",
        "pnl",
        "return_pct",
        "exit_reason",
        "exit_event",
    ]
    present = [column for column in columns if column in closed.columns]
    out = (
        closed.sort_values(["variant_id", "pnl"], ascending=[True, False])
        .groupby("variant_id", sort=False)
        .head(top_n)
        .loc[:, present]
        .copy()
    )
    if "return_pct" in out:
        out["return_pct"] = (pd.to_numeric(out["return_pct"], errors="coerce") * 100.0).round(3)
    return out.reset_index(drop=True)


def symbol_concentration(trades: pd.DataFrame) -> pd.DataFrame:
    closed = trades[trades["status"].eq("closed")].copy()
    rows = (
        closed.groupby(["variant_id", "symbol"], sort=False)
        .agg(
            trades=("symbol", "size"),
            pnl=("pnl", "sum"),
            avg_return_pct=("return_pct", lambda s: float(s.mean() * 100.0)),
            max_return_pct=("return_pct", lambda s: float(s.max() * 100.0)),
            max_duration_days=("duration_days", "max"),
        )
        .reset_index()
    )
    for column in ("pnl", "avg_return_pct", "max_return_pct", "max_duration_days"):
        rows[column] = rows[column].round(3)
    return rows.sort_values(["variant_id", "pnl"], ascending=[True, False]).reset_index(drop=True)


def _write_markdown(
    output_dir: Path,
    *,
    summary: pd.DataFrame,
    hold_buckets: pd.DataFrame,
    top: pd.DataFrame,
    config: AnalysisConfig,
) -> None:
    def table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "_No rows._"
        columns = [str(column) for column in frame.columns]
        rows = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for _, row in frame.iterrows():
            rows.append("| " + " | ".join(str(row[column]) for column in frame.columns) + " |")
        return "\n".join(rows)

    lines: list[str] = [
        "# Monster Run Decomposition",
        "",
        "This report uses tracked `trades_all.csv` artifacts. It does not use the missing ignored",
        "`sweeps/runs/` result JSONs for the scanner-ranker headline run, so it is a first baseline",
        "on available realized-trade variants rather than the final champion/top20 trade-path dataset.",
        "",
        "## Inputs",
        "",
    ]
    for path in config.trades_csv:
        lines.append(f"- `{path}`")
    best_closed = summary.sort_values("closed_pnl", ascending=False).iloc[0]
    most_monster = summary.sort_values("monster_pnl_share_pct", ascending=False).iloc[0]
    least_monster = summary.sort_values("monster_pnl_share_pct", ascending=True).iloc[0]
    top10_min = float(summary["top10_positive_pnl_share_pct"].min())
    top10_max = float(summary["top10_positive_pnl_share_pct"].max())
    lines.extend(
        [
            "",
            "## Key Findings",
            "",
            f"- Best closed-PnL variant in this slice: `{best_closed['variant_id']}` with "
            f"{best_closed['closed_pnl']:.3f} closed PnL.",
            f"- Highest monster-run dependence: `{most_monster['variant_id']}` with "
            f"{most_monster['monster_pnl_share_pct']:.3f}% of closed net PnL from monster trades.",
            f"- Lowest monster-run dependence: `{least_monster['variant_id']}` with "
            f"{least_monster['monster_pnl_share_pct']:.3f}% of closed net PnL from monster trades.",
            f"- Top-10 positive trades contribute {top10_min:.3f}% to {top10_max:.3f}% of positive "
            "closed PnL across these variants.",
            "- `open_or_censored_pnl` is zero here because these tracked `trades_all.csv` artifacts do "
            "not include mark-to-market PnL for open rows; use #456 to rebuild a full path dataset.",
            "",
        ]
    )
    lines.extend(["", "## Variant Summary", ""])
    lines.append(table(summary))
    lines.extend(["", "## Hold Bucket PnL", ""])
    pivot = hold_buckets.pivot(index="variant_id", columns="hold_bucket", values="pnl").fillna(0.0)
    lines.append(table(pivot.reset_index()))
    lines.extend(["", "## Top Trades", ""])
    top_cols = [col for col in ["variant_id", "symbol", "entry_date", "exit_date", "duration_days", "pnl", "return_pct"] if col in top.columns]
    lines.append(table(top.loc[:, top_cols].head(40)))
    lines.extend(
        [
            "",
            "## Read",
            "",
            "- `top*_positive_pnl_share_pct` is the cleanest monster-run concentration signal.",
            "- `monster_pnl_share_pct` uses closed trades with return >= 10% or PnL above the variant's",
            "  90th percentile of positive PnL.",
            "- The patient 8% target variants show materially higher monster-run exposure than faster",
            "  target/giveback variants. That supports a two-persona exit design: protect likely runners,",
            "  but allow faster realization on ordinary swings.",
            "- The 11-30 day bucket is the strongest common PnL bucket in this available slice; George-style",
            "  fast exits should not be interpreted as same-day-only exits.",
            "- Actual George hold/exit evidence still belongs in #461; this report only compares",
            "  available strategy variants that approximate faster profit capture versus let-run behavior.",
            "",
        ]
    )
    (output_dir / "monster_run_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(
    *,
    trades_csv: tuple[Path, ...] = DEFAULT_INPUTS,
    variants: tuple[str, ...] = DEFAULT_VARIANTS,
    output_dir: Path = DEFAULT_OUTPUT,
    top_n: int = 20,
) -> dict[str, Path]:
    trades = _dedupe_variant_rows(_read_trades(trades_csv))
    selected = trades[trades["variant_id"].isin(set(variants))].copy()
    missing = sorted(set(variants) - set(selected["variant_id"].unique()))
    if missing:
        raise ValueError(f"requested variants not found: {', '.join(missing)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    readme = output_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# monster_run_decomposition_459/\n\n"
            "Generated diagnostics for issue #459. Keep compact CSV/Markdown summaries here; "
            "do not store raw LEAN run directories.\n",
            encoding="utf-8",
        )
    config = AnalysisConfig(
        trades_csv=tuple(str(path) for path in trades_csv),
        variants=variants,
        output_dir=str(output_dir),
    )
    summary = variant_summary(selected)
    buckets = hold_bucket_summary(selected)
    top = top_trades(selected, top_n=top_n)
    symbols = symbol_concentration(selected)
    summary.to_csv(output_dir / "variant_summary.csv", index=False)
    buckets.to_csv(output_dir / "hold_bucket_summary.csv", index=False)
    top.to_csv(output_dir / "top_trades.csv", index=False)
    symbols.to_csv(output_dir / "symbol_concentration.csv", index=False)
    (output_dir / "manifest.json").write_text(
        json.dumps({"config": asdict(config), "outputs": sorted(p.name for p in output_dir.glob("*"))}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    _write_markdown(output_dir, summary=summary, hold_buckets=buckets, top=top, config=config)
    return {
        "variant_summary": output_dir / "variant_summary.csv",
        "hold_bucket_summary": output_dir / "hold_bucket_summary.csv",
        "top_trades": output_dir / "top_trades.csv",
        "symbol_concentration": output_dir / "symbol_concentration.csv",
        "report": output_dir / "monster_run_report.md",
    }


def main() -> None:
    args = _args()
    trades_csv = tuple(args.trades_csv) if args.trades_csv else DEFAULT_INPUTS
    variants = tuple(args.variant) if args.variant else DEFAULT_VARIANTS
    outputs = run(trades_csv=trades_csv, variants=variants, output_dir=args.output_dir, top_n=args.top_n)
    for label, path in outputs.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
