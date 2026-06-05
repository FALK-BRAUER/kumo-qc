"""#340-reserve FY VERDICT — the FY2025 single-period run for the FY-6 (HQ tournament escalation).
The 2-window pool showed the reserve cells beat S1 on FLOOR but the win is DD/under-investment-driven
(Sharpe ≈ S1) — reserve = a de-levered S1. The pyramid is dead (pyrOFF ≥ pyrON). FY single-period Sharpe
is the arbiter: > S1 = real skip-alpha (the laggard-skip generalizes); ≈ S1 = de-lever-not-alpha (lower
DD, a Falk risk-preference call, NOT an autonomous champion-swap).

FY-6 = S1 baseline + the best reserve cells + the pyramid-isolation twins. Full FY2025 (no quarterly
window), trim+cache, same harness as the 2-window pool. Reads: FY Sharpe vs S1 + skip-backfire (did a
budget-skipped name moon FY-wide?) + DD + monster-survival. asof = 2025-12-31.

Usage: python3 scripts/run_340fy.py [cell_suffix ...]
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
from sweeps.windows import Window  # noqa: E402
from kpi import report_and_log  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_340fy"
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)
FY = Window(name="fy2025", start="2025-01-01", end="2025-12-31")
# (module_basename, label) — S1 baseline first, then the reserve candidates + pyramid-isolation twins.
CELLS = [
    ("matrix_sz050_off", "S1 baseline (1.0x, pyrOFF) [champion]"),
    ("reserve_sz050_b050_on", "S1-size × reserve50% × pyrON [best-floor]"),
    ("reserve_sz050_b050_off", "S1-size × reserve50% × pyrOFF [de-lever isolation]"),
    ("reserve_sz025_b050_on", "0.5x × reserve50% × pyrON"),
    ("reserve_sz050_b070_off", "S1-size × reserve30% × pyrOFF"),
    ("reserve_sz025_b050_off", "0.5x × reserve50% × pyrOFF [smaller de-lever]"),
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
    args = [a for a in sys.argv[1:]]
    print(f"=== #340-reserve FY2025 VERDICT — FY-6 (Sharpe is the arbiter; vs S1) ===", flush=True)
    for mod, label in CELLS:
        suffix = mod.split("_", 1)[1] if "_" in mod else mod
        if args and not any(a in mod for a in args):
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                              "base_module": f"strategies.{mod}"}
        adapter = make_local_run(runs_root=RUNS / mod / FY.name, warmup_gate=None, ensure_weekly_cache_fp=_FP)
        print(f"\n--- {mod} [{label}] FY2025 ---", flush=True)
        m = adapter(TRIM, FY)
        rd = RUNS / mod / FY.name / TRIM.config_hash / FY.name
        report_and_log(rd, f"#340FY {mod}", sharpe=m.sharpe, net_pct=m.ret_pct, dd_pct=m.dd_pct,
                       fills=m.orders, config_hash=TRIM.config_hash, window=FY.name,
                       stamp="2026-06-05", asof=_dt.date(2025, 12, 31))
        print(f"    distinct-names-entered: {_distinct_names(rd)} (LOCAL count, ~6x vs cloud — flag)", flush=True)


if __name__ == "__main__":
    main()
