#!/usr/bin/env python3
"""Validate parity between local and QC cloud backtest result JSON files."""

from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any


MetricMap = dict[str, tuple[str, ...]]

METRIC_PATHS: MetricMap = {
    "sharpe": (
        "statistics.Sharpe Ratio",
        "statistics.Sharpe",
        "statistics.SharpeRatio",
        "totalPerformance.portfolioStatistics.sharpeRatio",
    ),
    "cagr": (
        "statistics.Compounding Annual Return",
        "statistics.CAGR",
        "totalPerformance.portfolioStatistics.compoundingAnnualReturn",
    ),
    "total_return": (
        "statistics.Net Profit",
        "statistics.Total Return",
        "runtimeStatistics.Return",
        "totalPerformance.portfolioStatistics.totalNetProfit",
    ),
    "win_rate": (
        "statistics.Win Rate",
        "statistics.WinRate",
        "totalPerformance.portfolioStatistics.winRate",
        "totalPerformance.tradeStatistics.winRate",
    ),
    "trade_count": (
        "statistics.Total Trades",
        "statistics.TotalTradeCount",
        "totalPerformance.tradeStatistics.totalNumberOfTrades",
    ),
}


def get_nested(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        cleaned = cleaned.replace("$", "")
        if cleaned.endswith("%"):
            cleaned = cleaned[:-1].strip()
            if not cleaned:
                return None
            try:
                return float(cleaned) / 100.0
            except ValueError:
                return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def normalize_rate(value: float | None) -> float | None:
    if value is None:
        return None
    # Handle percent-like values without '%' (e.g. 45 instead of 0.45).
    if abs(value) > 1.0:
        return value / 100.0
    return value


def extract_metric(data: dict[str, Any], metric: str) -> float | None:
    for path in METRIC_PATHS[metric]:
        raw = get_nested(data, path)
        num = parse_number(raw)
        if num is None:
            continue

        if metric in {"cagr", "total_return", "win_rate"}:
            return normalize_rate(num)
        if metric == "trade_count":
            return float(int(round(num)))
        return num
    return None


def relative_diff(actual: float, expected: float) -> float:
    denom = abs(expected)
    if math.isclose(denom, 0.0, abs_tol=1e-12):
        return abs(actual - expected)
    return abs(actual - expected) / denom


def format_metric(metric: str, value: float) -> str:
    if metric in {"cagr", "total_return", "win_rate"}:
        return f"{value * 100:.2f}%"
    if metric == "trade_count":
        return str(int(round(value)))
    return f"{value:.4f}"


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare local and QC cloud backtest results for parity on "
            "Sharpe, CAGR, total return, win rate, and trade count."
        )
    )
    parser.add_argument("local_json", help="Path to local backtest results JSON")
    parser.add_argument("cloud_json", help="Path to QC cloud backtest results JSON")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Relative tolerance as decimal (default: 0.05 for 5%%)",
    )
    args = parser.parse_args()

    local_data = load_json(args.local_json)
    cloud_data = load_json(args.cloud_json)

    failures: list[str] = []

    print("Comparing metrics:")
    for metric in ("sharpe", "cagr", "total_return", "win_rate", "trade_count"):
        local_val = extract_metric(local_data, metric)
        cloud_val = extract_metric(cloud_data, metric)

        if local_val is None or cloud_val is None:
            failures.append(f"{metric}: missing value (local={local_val}, cloud={cloud_val})")
            print(f"- {metric}: FAIL (missing value)")
            continue

        diff = relative_diff(local_val, cloud_val)
        ok = diff <= args.tolerance

        local_fmt = format_metric(metric, local_val)
        cloud_fmt = format_metric(metric, cloud_val)
        diff_pct = diff * 100.0

        if ok:
            print(
                f"- {metric}: PASS (local={local_fmt}, cloud={cloud_fmt}, diff={diff_pct:.2f}%)"
            )
        else:
            failures.append(
                f"{metric}: local={local_fmt}, cloud={cloud_fmt}, diff={diff_pct:.2f}%"
            )
            print(
                f"- {metric}: FAIL (local={local_fmt}, cloud={cloud_fmt}, diff={diff_pct:.2f}%)"
            )

    if failures:
        print("\nFAIL")
        for item in failures:
            print(f"- {item}")
        return 1

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
