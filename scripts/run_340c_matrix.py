"""#340-C-redo — sizing × pyramid MATRIX (Falk's reopened winner-side). per-entry-size {0.05,0.033,
0.025,0.0165} × pyramid {OFF,ON} on trim+cache, Q1-bear + Q3-bull, floor-proxy leaderboard same-method
vs S1. KEY cell = {0.025/0.0165 × ON} (small probes + re-concentrate into provers). gross-cap stays 1.0
(headroom from sizing-DOWN, not leverage).

Instruments the 2 traps: per-cell FILLS + DISTINCT-NAMES-entered (slot-fill: do smaller entries fill MORE
names, or idle?) — NOTE the count is LOCAL (over-counts signals ~6× vs cloud; flag, don't over-trust).
Dilution shows as {smaller × OFF} losing; pyramid-re-concentration as {smaller × ON} recovering.

Default runs the KEY cells first (decisive), then the rest. Usage:
  python3 scripts/run_340c_matrix.py [sz050_off sz025_on ...] [q1 q3]
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

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_340cmatrix"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"]}
# KEY cells first (decisive): S1 baseline, the small×ON bets, the small×OFF dilution-isolation.
CELLS = [
    ("sz050_off", "S1 baseline (1.0x, pyrOFF)"), ("sz025_on", "0.5x + pyrON [KEY]"),
    ("sz0165_on", "0.33x + pyrON [KEY]"), ("sz025_off", "0.5x pyrOFF [dilution]"),
    ("sz0165_off", "0.33x pyrOFF [dilution]"), ("sz050_on", "1.0x + pyrON [=#340-C]"),
    ("sz033_on", "0.66x + pyrON"), ("sz033_off", "0.66x pyrOFF"),
]


def _distinct_names(run_dir: Path) -> int:
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not bts:
        return 0
    oe = next(bts[0].glob("*-order-events.json"), None)
    if oe is None:
        return 0
    ev = json.loads(oe.read_text()); ev = ev.get("orderEvents", ev) if isinstance(ev, dict) else ev
    names = set()
    for e in ev:
        if str(e.get("status", "")).lower() == "filled" and float(e.get("fillQuantity", 0)) > 0:
            s = e.get("symbol", {}); s = s.get("value", s) if isinstance(s, dict) else s
            names.add(str(s).split(" ")[0])
    return len(names)


def main() -> None:
    args = [a.lower() for a in sys.argv[1:]]
    ck = [a for a in args if a.startswith("sz")] or [c for c, _ in CELLS]
    wk = [a for a in args if a in ("q1", "q3")] or ["q1", "q3"]
    print(f"=== #340-C-redo MATRIX — {ck} × {wk} (vs S1 floor-proxy; KEY=small×ON) ===", flush=True)
    for cell, label in CELLS:
        if cell not in ck:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                              "base_module": f"strategies.matrix_{cell}"}
        for w in [WINDOWS[k] for k in wk]:
            adapter = make_local_run(runs_root=RUNS / cell / w.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
            print(f"\n--- {cell} [{label}] {w.name} ---", flush=True)
            m = adapter(TRIM, w)
            rd = RUNS / cell / w.name / TRIM.config_hash / w.name
            k = report_and_log(rd, f"#340Cm {cell} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct,
                               dd_pct=m.dd_pct, fills=m.orders, config_hash=TRIM.config_hash,
                               window=w.name, stamp="2026-06-05", asof=_dt.date.fromisoformat(w.end))
            print(f"    distinct-names-entered: {_distinct_names(rd)} (slot-fill; LOCAL count, ~6x vs cloud — flag)", flush=True)


if __name__ == "__main__":
    main()
