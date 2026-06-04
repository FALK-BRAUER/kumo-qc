"""#368 warmup-TRIM parity+RSS probe — does trimming set_warmup (560→N) stay byte-identical AND
shrink the per-cell RSS (→ free parallel in the existing 7.75GiB Docker, no bump)?

UNIFORM less-warming for ALL runs (a set_warmup change) — NOT the #365 snapshot-restore (which had
the deep per-name divergence). The ONLY parity question: does N-day warmup == 560d warmup at
sim-start? YES iff N ≥ every indicator lookback (the daily long pole = sma200 = 200 trading ≈ 280
calendar; weekly is history-derived, warmup-independent). N=320 calendar ≈ 221 trading ≥ 200 (buffer).

Runs S1 (the champion, 65c0cf447168) over FY2025 with WARMUP_DAYS injected via SWEEP_CLASS_ATTRS.
Compare orders to the known full-560d baseline (72). Measure RSS separately via `docker stats`.

Usage: WARMUP_DAYS=320 python3 scripts/run_368_trim.py   (1 full-FY cap-1 BT)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

_S1_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)
S1 = SweepConfig(choices=_S1_BASE, continuous_weekly=True)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
BASELINE_ORDERS = 72  # S1 full-560d-warmup FY (RUN1 of the #365 v2 run)


def main() -> None:
    wd = int(os.environ.get("WARMUP_DAYS", "320"))
    attrs = {"WARMUP_DAYS": wd}
    wcfp = os.environ.get("WEEKLY_CACHE_FP")
    if wcfp:
        # arm the #358 weekly-cache → the weekly comes from the pre-built per-symbol cache, DECOUPLED
        # from WARMUP_DAYS → trimming WARMUP_DAYS no longer starves the 78-week weekly (the 360→0 bug).
        attrs["WARMUP_WEEKLY_CACHE_FP"] = wcfp
    if os.environ.get("MISS_LOG") == "1":
        attrs["WEEKLY_MISS_LOG"] = True  # #368 enumerate cache misses (sym, date, sym-cached?)
    os.environ["SWEEP_CLASS_ATTRS"] = json.dumps(attrs)
    print(f"=== #368 trim probe: WARMUP_DAYS={wd} weekly_cache={'ARMED '+wcfp[:12] if wcfp else 'OFF'} "
          f"(baseline 560d→72), S1 {S1.config_hash} ===", flush=True)
    adapter = make_local_run()
    t0 = time.perf_counter()
    result = adapter.run_result(S1, FY)
    wall = time.perf_counter() - t0
    orders = int(getattr(result.metrics, "orders", -1))
    print(f"\nTRIM WARMUP_DAYS={wd}: orders={orders} wall={wall:.1f}s", flush=True)
    print(f"PARITY vs 560d baseline (72): {'PASS — byte-identical' if orders == BASELINE_ORDERS else 'FAIL — DIVERGED'}"
          f" ({orders} vs {BASELINE_ORDERS})", flush=True)
    print("RSS: read separately via `docker stats` during this run's warmup "
          "(TIMING_SUMMARY warmup_sec in the log too).", flush=True)
    if orders != BASELINE_ORDERS:
        sys.exit(1)


if __name__ == "__main__":
    main()
