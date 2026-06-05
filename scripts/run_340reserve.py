"""#340-reserve grid — cash-reserve × size × pyramid (charter-compliant successor to the starved 16-cell
matrix). ReserveHeatcap.base_entry_gross_budget reserves (1-budget) cash for the pyramid adds → tests
whether the pyramid re-concentrates into the provers WHEN GIVEN ROOM (the #340-C question, finally with
cash). Q1-bear + Q3-bull, trim+cache, floor-proxy leaderboard same-method vs S1.

THE CONTROL (decisive, run first) = {sz050_b070_on}: S1-size big entries, 30% reserved for adds. vs S1
= PURE pyramid-reserve (isolated from breadth). pyrOFF controls confirm the reserve only pays WITH the
pyramid (idle reserve = pure downside).

Instruments: per-cell FILLS + DISTINCT-NAMES (LOCAL, over-counts signals ~6× vs cloud — flag, anchor to
cloud before trusting). Usage: python3 scripts/run_340reserve.py [sz050_b070_on ...] [q1 q3]
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
RUNS = _ROOT / "sweeps" / "runs_340reserve"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
_BY = {w.name: w for w in SIX_WINDOWS}
WINDOWS = {"q1": _BY["w1_2025q1"], "q3": _BY["w3_2025q3"]}
# CONTROL first (decisive pure pyramid-reserve), then small×budget pyrON, then pyrOFF controls.
CELLS = [
    ("sz050_b070_on", "S1-size × reserve30% × pyrON [CONTROL: pure pyramid-reserve]"),
    ("sz050_b050_on", "S1-size × reserve50% × pyrON"),
    ("sz025_b070_on", "0.5× × reserve30% × pyrON"),
    ("sz0165_b070_on", "0.33× × reserve30% × pyrON"),
    ("sz025_b050_on", "0.5× × reserve50% × pyrON"),
    ("sz0165_b050_on", "0.33× × reserve50% × pyrON"),
    ("sz050_b070_off", "S1-size × reserve30% × pyrOFF [control: reserve idles]"),
    ("sz025_b070_off", "0.5× × reserve30% × pyrOFF [control]"),
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
    print(f"=== #340-reserve GRID — {ck} × {wk} (vs S1 floor-proxy; CONTROL=sz050_b070_on) ===", flush=True)
    for cell, label in CELLS:
        if cell not in ck:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                              "base_module": f"strategies.reserve_{cell}"}
        for w in [WINDOWS[k] for k in wk]:
            adapter = make_local_run(runs_root=RUNS / cell / w.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
            print(f"\n--- {cell} [{label}] {w.name} ---", flush=True)
            m = adapter(TRIM, w)
            rd = RUNS / cell / w.name / TRIM.config_hash / w.name
            report_and_log(rd, f"#340Rsv {cell} {w.name}", sharpe=m.sharpe, net_pct=m.ret_pct,
                           dd_pct=m.dd_pct, fills=m.orders, config_hash=TRIM.config_hash,
                           window=w.name, stamp="2026-06-05", asof=_dt.date.fromisoformat(w.end))
            print(f"    distinct-names-entered: {_distinct_names(rd)} (slot-fill; LOCAL count, ~6x vs cloud — flag)", flush=True)


if __name__ == "__main__":
    main()
