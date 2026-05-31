#!/usr/bin/env python3
"""#243/#268 PART 1 — extract LOCAL's maintained-indicator chart series from the local BT.

The extended ChartEmit phase (src/phases/diagnostics/chart_emit) plots the same self.plot
series locally that it does on cloud — LEAN records them in the local BT result JSON under
"Charts". This pulls Regime/spy_close + Regime/spy_ma200 + Signal/n_qualifying + Score/<probe>
out of the local full-FY result and writes research/parity/artifacts/local-indicators-243.json
in the SAME shape the cloud capture (cloud-indicators-243.json, scripts/capture_243_charts.py)
will land — so #268's cloud-vs-local diff is a straight key-by-key compare.

NEVER fabricates: a missing chart/series is recorded as null, not invented. The local trio
(Sharpe/Return/Drawdown) is read straight from the result statistics to CONFIRM the emit is
inert (must still be -0.139 / +3.62% / 244 — the #265 baseline).

Usage: python3 scripts/extract_local_indicators_243.py <localResultJson> [outPath]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ("Universe", "Regime", "Signal", "Score")


def _series(chart: dict[str, Any]) -> dict[str, list[list[float]]]:
    """Normalize a LEAN chart's series → {seriesName: [[unix_ts, value], ...]} ascending."""
    raw = chart.get("series") or chart.get("Series") or {}
    out: dict[str, list[list[float]]] = {}
    for sname, s in raw.items():
        vals = s.get("values") or s.get("Values") or []
        pts: list[list[float]] = []
        for v in vals:
            if isinstance(v, dict):  # defensive: object-form point
                x = v.get("x") or v.get("Time")
                y = v.get("y") or v.get("Value")
                if x is not None and y is not None:
                    pts.append([float(x), float(y)])
            elif isinstance(v, (list, tuple)) and len(v) >= 2:
                pts.append([float(v[0]), float(v[1])])
        out[sname] = pts
    return out


def extract(result_path: Path, out_path: Path) -> dict[str, Any]:
    d = json.loads(result_path.read_text())
    charts = d.get("charts") or d.get("Charts") or {}
    stats = d.get("statistics") or d.get("Statistics") or {}

    captured: dict[str, dict[str, list[list[float]]] | None] = {}
    for name in CHARTS:
        c = charts.get(name)
        captured[name] = _series(c) if c else None

    trio = {
        "sharpe": stats.get("Sharpe Ratio"),
        "net_return_pct": stats.get("Compounding Annual Return") or stats.get("Net Profit"),
        "drawdown_pct": stats.get("Drawdown"),
        "total_orders": stats.get("Total Orders"),
    }
    payload = {
        "source": "LOCAL",
        "result_json": str(result_path.relative_to(ROOT)) if str(result_path).startswith(
            str(ROOT)
        ) else str(result_path),
        "trio_inert_confirm": trio,
        "charts": captured,
        "failed": [c for c in CHARTS if captured[c] is None],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    rp = Path(sys.argv[1])
    op = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        ROOT / "research/parity/artifacts/local-indicators-243.json"
    )
    res = extract(rp, op)
    print(f"wrote {op}")
    print(f"  trio (inert confirm): {res['trio_inert_confirm']}")
    ok = [c for c in CHARTS if res["charts"][c] is not None]
    print(f"  captured charts: {ok}; failed: {res['failed']}")
    for name in ok:
        for sname, pts in res["charts"][name].items():
            print(f"    {name}/{sname}: {len(pts)} pts")
