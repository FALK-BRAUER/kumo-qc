"""Run ONE period-sweep cell in its OWN process. Injects the Ichimoku periods via SWEEP_CLASS_ATTRS
(read by local_dist_builder at codegen → BCTAlgorithm class-attrs TENKAN/KIJUN/SENKOU_B). Periods break
the weekly-cache (keyed to 9/26/52) → runs FULL warmup (warmup_days=560, no cache fp). Base = S1
(matrix_sz050_off). Process-isolated env → safe to run N concurrent via run_periods (each its own env).

PARITY: t=9 k=26 sb=52 → class-attrs == the champion literals → MUST reproduce S1 (-10.4/-5.5 windows,
1.025 FY Sharpe) byte-identical. That's the plumbing-correctness gate (HQ).

Usage: python3 scripts/run_period_cell.py <tenkan> <kijun> <senkou_b> <window q1|q3|fy> <runs_subdir>
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

# inject the periods BEFORE importing the builder (local_dist_builder reads the env at build time)
_t, _k, _sb = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
os.environ["SWEEP_CLASS_ATTRS"] = json.dumps({"TENKAN": _t, "KIJUN": _k, "SENKOU_B": _sb})

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS, Window  # noqa: E402
from kpi import report_and_log  # noqa: E402

_BY = {w.name: w for w in SIX_WINDOWS}
_WIN = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"],
        "fy": Window(name="fy2025", start="2025-01-01", end="2025-12-31")}
_ASOF = {"w1_2025q1": _dt.date(2025, 3, 31), "w3_2025q3": _dt.date(2025, 9, 30), "fy2025": _dt.date(2025, 12, 31)}
# FULL warmup (no cache — periods != 9/26/52 invalidate the weekly-cache fp)
FULL = SweepConfig(choices=(), continuous_weekly=True, warmup_days=560)


def main() -> None:
    wkey, runs_sub = sys.argv[4], sys.argv[5]
    w = _WIN[wkey]
    runs_root = _ROOT / "sweeps" / f"runs_{runs_sub}" / f"t{_t}k{_k}s{_sb}"
    sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                          "base_module": "strategies.matrix_sz050_off"}
    adapter = make_local_run(runs_root=runs_root / w.name, warmup_gate=None, ensure_weekly_cache_fp=None)
    print(f"[period] t{_t}/k{_k}/s{_sb} {w.name} START (full warmup, no cache)", flush=True)
    m = adapter(FULL, w)
    rd = runs_root / w.name / FULL.config_hash / w.name
    report_and_log(rd, f"#PERIOD t{_t}k{_k}s{_sb} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct,
                   dd_pct=m.dd_pct, fills=m.orders, config_hash=FULL.config_hash, window=w.name,
                   stamp="2026-06-05", asof=_ASOF.get(w.name, _dt.date(2025, 12, 31)))
    print(f"[period] t{_t}/k{_k}/s{_sb} {w.name} DONE Sharpe {m.sharpe:+.3f} net {m.ret_pct:+.1f}%", flush=True)


if __name__ == "__main__":
    main()
