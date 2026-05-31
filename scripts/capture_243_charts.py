#!/usr/bin/env python3
"""#243 chart capture — pull the cloud custom-chart series for the #268 cloud-vs-local diff.

Reuses qc_v2_cloud.py auth + chart() (5x backoff). Captures Universe/Regime/Signal/Score for
a completed backtest into research/parity/artifacts/cloud-indicators-243.json. The chart-read
endpoint is FLAKY (it lags for minutes after a BT completes) → this wraps chart() in an OUTER
patient retry (default 25 rounds x 60s). NEVER fabricates: charts that never return are recorded
as null with the last error, so #268 sees exactly what was retrieved vs what failed.

Usage: python3 scripts/capture_243_charts.py <backtestId> <outPath>
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "qcv2", str(Path(__file__).resolve().parent / "qc_v2_cloud.py"))
assert _spec and _spec.loader
qcv2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qcv2)

CHARTS = ("Universe", "Regime", "Signal", "Score")
OUTER_ROUNDS = 25
OUTER_WAIT_S = 60


def capture(bid: str, out_path: str) -> None:
    qcv2.ensure_project()
    captured: dict[str, dict | None] = {c: None for c in CHARTS}
    last_err: dict[str, str] = {}
    for rnd in range(OUTER_ROUNDS):
        pending = [c for c in CHARTS if captured[c] is None]
        if not pending:
            break
        for name in pending:
            series = qcv2.chart(bid, name)  # inner 5x backoff
            if series is not None:
                captured[name] = series
            else:
                last_err[name] = "chart-read endpoint returned no series after inner retries"
        pending = [c for c in CHARTS if captured[c] is None]
        if pending and rnd < OUTER_ROUNDS - 1:
            print(f"  outer round {rnd + 1}/{OUTER_ROUNDS}: still pending {pending}; "
                  f"wait {OUTER_WAIT_S}s")
            time.sleep(OUTER_WAIT_S)
    payload = {
        "backtestId": bid,
        "project": qcv2.PROJECT_NAME,
        "charts": captured,
        "failed": {c: last_err.get(c, "") for c in CHARTS if captured[c] is None},
    }
    Path(out_path).write_text(json.dumps(payload, indent=2))
    ok = [c for c in CHARTS if captured[c] is not None]
    bad = [c for c in CHARTS if captured[c] is None]
    print(f"  wrote {out_path} — captured {ok}; FAILED {bad}")


if __name__ == "__main__":
    capture(sys.argv[1], sys.argv[2])
