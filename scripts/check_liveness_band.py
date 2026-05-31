#!/usr/bin/env python3
"""#244-D PERIODIC liveness band check (NOT per-PR — runs on a full-FY backtest result).

Reads a LEAN backtest summary JSON (the `*-summary.json` a `kumo bt run` produces) and asserts
the champion's full-FY trade activity has NOT collapsed against the recorded baseline:

    baseline (mainV2 25b79d6, full-FY2025 local): 75 orders / 32 round-trips
    band     : FAIL if Total Orders < 50% of baseline (< 37) OR round-trips collapse (< 16)

This is the PERIODIC arm of the liveness gate (a full-FY BT is minutes + docker, so it does
NOT run per-PR — the per-PR arm is tests/acceptance/test_liveness.py, fast pytest, orders>0 +
0-trades guard). Run this nightly / manually after a full-FY backtest:

    kumo bt run algorithm/performance_bct ...        # produce the summary JSON
    python scripts/check_liveness_band.py <path-to-*-summary.json>

Exit 0 = within band; exit 1 = collapse (anti-0 / anti-turnover-collapse). NOT a hard pin to
==75 (that breaks on every legitimate #228 signal change); it catches a SILENT regression to
zero / near-zero trading, which is the intent.

Reads the standard LEAN summary keys statistics."Total Orders" +
totalPerformance.tradeStatistics.totalNumberOfTrades (with a statistics."Total Trades" fallback
for the round-trip count, in case a summary populates that instead).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# --- Recorded baseline (mainV2 25b79d6, full-FY2025 local; Sharpe -0.616 / +3.899% / 3.4% DD).
BASELINE_ORDERS = 75
BASELINE_ROUND_TRIPS = 32

# --- Band: FAIL below 50% of baseline (anti-collapse, NOT a hard pin to the exact count).
ORDERS_FLOOR_FRAC = 0.50
ORDERS_FLOOR = int(BASELINE_ORDERS * ORDERS_FLOOR_FRAC)          # 37
ROUND_TRIPS_FLOOR = int(BASELINE_ROUND_TRIPS * ORDERS_FLOOR_FRAC)  # 16

# Standard LEAN result-JSON paths. Round-trips: prefer the tradeStatistics count, fall back to
# statistics."Total Trades" (some summaries populate that instead).
ORDER_PATHS = ("statistics.Total Orders",)
ROUND_TRIP_PATHS = (
    "totalPerformance.tradeStatistics.totalNumberOfTrades",
    "statistics.Total Trades",
)


def get_nested(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def extract_int(data: dict[str, Any], paths: tuple[str, ...]) -> int | None:
    for path in paths:
        raw = get_nested(data, path)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return int(round(raw))
        if isinstance(raw, str):
            cleaned = raw.strip().replace(",", "")
            if cleaned:
                try:
                    return int(round(float(cleaned)))
                except ValueError:
                    continue
    return None


def check_band(orders: int | None, round_trips: int | None) -> tuple[bool, list[str]]:
    """Return (passed, messages). FAIL on a material drop below the band."""
    msgs: list[str] = []
    passed = True

    if orders is None:
        msgs.append("FAIL: could not read 'Total Orders' from the result JSON.")
        return False, msgs
    msgs.append(f"orders={orders} (baseline {BASELINE_ORDERS}, floor {ORDERS_FLOOR})")
    if orders <= 0:
        msgs.append("FAIL: ZERO orders — strategy stopped trading (anti-0 trip).")
        passed = False
    elif orders < ORDERS_FLOOR:
        msgs.append(
            f"FAIL: orders {orders} < floor {ORDERS_FLOOR} (<50% of baseline) — turnover collapse."
        )
        passed = False

    if round_trips is None:
        msgs.append("WARN: round-trip count absent (totalNumberOfTrades) — order band still applies.")
    else:
        msgs.append(f"round_trips={round_trips} (baseline {BASELINE_ROUND_TRIPS}, floor {ROUND_TRIPS_FLOOR})")
        if round_trips < ROUND_TRIPS_FLOOR:
            msgs.append(
                f"FAIL: round-trips {round_trips} < floor {ROUND_TRIPS_FLOOR} — turnover collapse."
            )
            passed = False

    if passed:
        msgs.append("PASS: full-FY trade activity within the liveness band.")
    return passed, msgs


def main() -> int:
    parser = argparse.ArgumentParser(description="Periodic full-FY liveness band check (#244-D).")
    parser.add_argument("summary_json", help="Path to a LEAN backtest *-summary.json")
    args = parser.parse_args()

    with open(args.summary_json, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        print(f"FAIL: expected a JSON object in {args.summary_json}", file=sys.stderr)
        return 1

    orders = extract_int(data, ORDER_PATHS)
    round_trips = extract_int(data, ROUND_TRIP_PATHS)
    passed, msgs = check_band(orders, round_trips)
    for m in msgs:
        print(m)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
