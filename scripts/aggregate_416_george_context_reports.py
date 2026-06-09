"""Aggregate #416/#427 George-context wave reports into one ranked report.

The sweep runner writes one `summary.csv` per wave or retry batch. This helper combines those
rows, de-duplicates variant ids by preferring later successful rows, and emits a single
leaderboard folder that downstream trade diagnostics can read.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "sweeps" / "reports" / "george_context_combo_30_fy2025"

SUMMARY_COLUMNS = [
    "rank",
    "variant_id",
    "family",
    "wave",
    "hypothesis",
    "ok",
    "ret_pct",
    "dd_pct",
    "orders",
    "sharpe",
    "sweep_config_hash",
    "source_report",
    "run_dir",
    "result_path",
    "error",
]

FAMILY_COLUMNS = [
    "family",
    "variants",
    "ok_count",
    "best_variant",
    "best_ret_pct",
    "median_ret_pct",
    "min_dd_pct",
    "max_dd_pct",
    "total_orders",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_reports", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_report(report_dir: Path) -> list[dict[str, str]]:
    summary = report_dir / "summary.csv"
    if not summary.exists():
        raise FileNotFoundError(summary)
    with summary.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["source_report"] = report_dir.name
    return rows


def _pick_rows(source_reports: list[Path]) -> list[dict[str, str]]:
    chosen: dict[str, dict[str, str]] = {}
    order: dict[str, int] = {}
    for source_index, report in enumerate(source_reports):
        for row in _read_report(report):
            variant_id = row["variant_id"]
            current = chosen.get(variant_id)
            current_ok = _bool(current.get("ok")) if current else False
            row_ok = _bool(row.get("ok"))
            should_replace = current is None or (row_ok and not current_ok) or (
                row_ok == current_ok and source_index >= order[variant_id]
            )
            if should_replace:
                chosen[variant_id] = row
                order[variant_id] = source_index
    rows = list(chosen.values())
    rows.sort(
        key=lambda row: (
            not _bool(row.get("ok")),
            -_float(row.get("ret_pct")),
            _float(row.get("dd_pct")),
            row.get("variant_id", ""),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = str(rank)
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _family_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    families = sorted({row.get("family", "") for row in rows})
    out: list[dict[str, str]] = []
    for family in families:
        family_rows = [row for row in rows if row.get("family") == family]
        ok_rows = [row for row in family_rows if _bool(row.get("ok"))]
        returns = [_float(row.get("ret_pct")) for row in ok_rows]
        drawdowns = [_float(row.get("dd_pct")) for row in ok_rows]
        best = max(ok_rows, key=lambda row: _float(row.get("ret_pct")), default=None)
        out.append(
            {
                "family": family,
                "variants": str(len(family_rows)),
                "ok_count": str(len(ok_rows)),
                "best_variant": best.get("variant_id", "") if best else "",
                "best_ret_pct": f"{_float(best.get('ret_pct')):.3f}" if best else "",
                "median_ret_pct": f"{statistics.median(returns):.3f}" if returns else "",
                "min_dd_pct": f"{min(drawdowns):.3f}" if drawdowns else "",
                "max_dd_pct": f"{max(drawdowns):.3f}" if drawdowns else "",
                "total_orders": str(sum(_int(row.get("orders")) for row in ok_rows)),
            }
        )
    out.sort(key=lambda row: _float(row["best_ret_pct"], -1e18), reverse=True)
    return out


def _write_markdown(path: Path, rows: list[dict[str, str]], family_rows: list[dict[str, str]]) -> None:
    lines = [
        "# George Context Combo Leaderboard",
        "",
        "| Rank | Variant | Family | OK | Return % | DD % | Orders | Source |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows[:30]:
        lines.append(
            f"| {row['rank']} | {row['variant_id']} | {row['family']} | {row['ok']} | "
            f"{_float(row.get('ret_pct')):.3f} | {_float(row.get('dd_pct')):.3f} | "
            f"{_int(row.get('orders'))} | {row.get('source_report', '')} |"
        )
    lines.extend(
        [
            "",
            "## Families",
            "",
            "| Family | Variants | OK | Best | Best Return % | Median Return % | DD Range | Orders |",
            "|---|---:|---:|---|---:|---:|---|---:|",
        ]
    )
    for row in family_rows:
        lines.append(
            f"| {row['family']} | {row['variants']} | {row['ok_count']} | {row['best_variant']} | "
            f"{row['best_ret_pct']} | {row['median_ret_pct']} | "
            f"{row['min_dd_pct']}..{row['max_dd_pct']} | {row['total_orders']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate_reports(source_reports: list[Path], output_dir: Path) -> list[dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    readme = output_dir / "README.md"
    if not readme.exists():
        readme.write_text(
            "# george_context_combo_30_fy2025/\n\n"
            "Combined George-context combo FY2025 leaderboard and diagnostics inputs.\n"
            "Put aggregate report CSV/Markdown files here; raw LEAN run folders stay under sweeps/runs.\n",
            encoding="utf-8",
        )

    rows = _pick_rows(source_reports)
    family_rows = _family_rows(rows)
    _write_csv(output_dir / "summary.csv", rows, SUMMARY_COLUMNS)
    _write_csv(output_dir / "family_summary.csv", family_rows, FAMILY_COLUMNS)
    _write_markdown(output_dir / "summary.md", rows, family_rows)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "sweep_id": output_dir.name,
                "source_reports": [str(path) for path in source_reports],
                "variant_count": len(rows),
                "ok_count": sum(1 for row in rows if _bool(row.get("ok"))),
                "created_from": "local aggregate of George-context wave summary.csv files",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return rows


def main() -> None:
    args = _args()
    rows = aggregate_reports([path.resolve() for path in args.source_reports], args.output_dir.resolve())
    print(f"WROTE {args.output_dir.resolve() / 'summary.csv'} rows={len(rows)}")


if __name__ == "__main__":
    main()
