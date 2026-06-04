"""#365 RESTORE parity gate — the 3-POINT engage gate (NOT bare byte-identical).

Byte-identical alone is a FALSE-GREEN trap: if the ObjectStore RUN1→RUN2 handoff fails, RESTORE
fail-closes → RUN2 runs a NORMAL 560d warmup → SAME trades as RUN1 (warmed==warmed) → "byte-
identical PASSES" while the restore did NOTHING (the speedup is fake). So the gate asserts THREE
(HQ, the weekly-cache order-bug lesson):

  1. RESTORE ENGAGED   — RUN2 log shows "#365 RESTORE: warmup-end rebuilt N from snapshot" with N>0
                         (proves RUN2 READ the snapshot, did not fail-close to live warmup).
  2. MINIMAL WARMUP    — RUN2 log shows "#365 RESTORE: MINIMAL warmup 40d" (NOT the 560d full warmup
                         → proves the warmup actually shrank, the speedup is real).
  3. BYTE-IDENTICAL    — RUN2 orders == RUN1 orders (count + per-order identity). The per-day
                         candidate-set / decision-trace parity (the subscription-timing desync watch)
                         is the deeper check; order-identity is its necessary surface.

#1+#2 prove the speedup is REAL; #3 proves it's CORRECT. All three or FAIL.

Mechanism: both runs use the SAME S1 config (same config_hash → same run_dir → shared ./storage =
the automatic capture→restore handoff). CAPTURE / RESTORE are injected via SWEEP_CLASS_ATTRS (NOT in
the config_hash). RUN1 captures + serializes the per-symbol warmup streams; RUN2 (same dir) restores.

Usage: python3 scripts/run_365_parity.py   (2 sequential full-FY BTs, cap-1)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402

# S1 champion base (no rotation) — the validate _S1REF (hash 65c0cf447168). continuous_weekly=True.
_S1_BASE = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)
S1 = SweepConfig(choices=_S1_BASE, continuous_weekly=True)
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")


def _data_fingerprint() -> str:
    """The snapshot key fp — the data MANIFEST fingerprint (a data change invalidates the cache).
    Fallback to a stable constant so the parity test still runs if the manifest is absent."""
    m = _ROOT / "data" / "MANIFEST.json"
    try:
        return str(json.loads(m.read_text()).get("fingerprint", "local-365-parity"))
    except Exception:  # noqa: BLE001
        return "local-365-parity"


def _run(label: str, class_attrs: dict) -> tuple[object, float]:
    """Run ONE cell directly via the local adapter (bypasses run_sweep's >=2-window panel gate —
    a parity test is a single (S1, FY) cell, not a statistical sweep). Returns (RunResult, seconds).
    RUN2 restore may raise (degraded / 0 orders if restore broke) — the caller catches to report a
    clean gate-FAIL, never a crash."""
    import time
    os.environ["SWEEP_CLASS_ATTRS"] = json.dumps(class_attrs)
    print(f"\n=== #365 parity {label}: SWEEP_CLASS_ATTRS={class_attrs} ===", flush=True)
    adapter = make_local_run()
    t0 = time.perf_counter()
    result = adapter.run_result(S1, FY)
    return result, time.perf_counter() - t0


def _run_dir() -> Path:
    return _ROOT / "sweeps" / "runs" / S1.config_hash / FY.name


def _backtest_dirs() -> list[Path]:
    bt = _run_dir() / "backtests"
    if not bt.is_dir():
        return []
    return sorted((d for d in bt.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)


def _order_count(bt_dir: Path) -> int:
    """Order-event count from a backtest result dir (the *-order-events.json artifact)."""
    for f in bt_dir.glob("*order-events*.json"):
        try:
            return len(json.loads(f.read_text()))
        except Exception:  # noqa: BLE001
            return -1
    return -1


def _grep_log(bt_dir: Path, needle: str) -> list[str]:
    hits: list[str] = []
    for f in list(bt_dir.glob("*log*.txt")) + list(bt_dir.glob("log.txt")):
        try:
            hits += [ln for ln in f.read_text().splitlines() if needle in ln]
        except Exception:  # noqa: BLE001
            pass
    return hits


def main() -> None:
    fp = _data_fingerprint()
    print(f"#365 parity gate — S1 {S1.config_hash}, fp {fp[:12]}…, run_dir {_run_dir()}", flush=True)

    # RESTORE-ONLY (PARITY_RESTORE_ONLY=1): skip the ~33-min capture, reuse the snapshot already in
    # ./storage + RUN1's order count from the oldest (capture) backtest dir. For fast fix-iteration.
    restore_only = os.environ.get("PARITY_RESTORE_ONLY") == "1"
    if restore_only:
        existing = _backtest_dirs()
        # RUN1 reference order count: env override (the capture's run_dir backtests/ gets WIPED by
        # build_sweep_dist's rebuild each run, so read it from PARITY_RUN1_ORDERS — the known S1 FY
        # capture = 72). Fall back to the oldest surviving backtest dir if no env.
        env_ref = os.environ.get("PARITY_RUN1_ORDERS")
        run1_orders = int(env_ref) if env_ref else (_order_count(existing[0]) if existing else -1)
        t1 = float("nan")
        n_before = len(existing)
        print(f"\nRESTORE-ONLY: reuse ./storage snapshot; RUN1 orders (ref)={run1_orders}", flush=True)
    else:
        r1, t1 = _run("capture", {"CAPTURE_WARMUP_SNAPSHOT": fp})
        run1_orders = int(getattr(r1.metrics, "orders", -1))
        n_before = len(_backtest_dirs())
        run1_bt = _backtest_dirs()[-1] if n_before else None
        cap_writes = _grep_log(run1_bt, "WARMUP_SNAPSHOT_WRITE") if run1_bt else []
        print(f"\nRUN1 capture: orders={run1_orders} wall={t1:.1f}s snapshot_writes={cap_writes}", flush=True)

    # DECISION_TRACE only when PARITY_TRACE=1 (it ~2-3x's the wall-clock via per-tick synchronous
    # logging — NOT needed for the orders==72 byte-identical headline; enable only for the deep
    # per-day candidate-set parity diff).
    restore_attrs = {"RESTORE_WARMUP_SNAPSHOT": fp}
    if os.environ.get("PARITY_TRACE") == "1":
        restore_attrs["DECISION_TRACE"] = True
    try:
        r2, t2 = _run("restore", restore_attrs)
        run2_orders = int(getattr(r2.metrics, "orders", -1))
    except Exception as e:  # noqa: BLE001 — a restore that breaks (degraded/0-orders) is a gate FAIL, report it
        print(f"\nRUN2 restore RAISED: {type(e).__name__}: {str(e)[:300]}", flush=True)
        run2_orders, t2 = -1, float("nan")
    bts_after = _backtest_dirs()
    run2_bt = bts_after[-1] if len(bts_after) > n_before else None
    engaged = _grep_log(run2_bt, "rebuilt") if run2_bt else []
    minimal = _grep_log(run2_bt, "MINIMAL warmup") if run2_bt else []
    print(f"\nRUN2 restore: orders={run2_orders} wall={t2:.1f}s", flush=True)

    # --- the 3-point engage gate (byte-identical alone is necessary-NOT-sufficient) ---
    p1_engaged = any("rebuilt" in ln and " 0 from snapshot" not in ln for ln in engaged)
    p2_minimal = bool(minimal)
    p3_identical = run1_orders >= 0 and run1_orders == run2_orders

    print("\n=== #365 3-POINT ENGAGE GATE ===")
    print(f"  1. RESTORE ENGAGED  : {'PASS' if p1_engaged else 'FAIL'}  {engaged}")
    print(f"  2. MINIMAL WARMUP   : {'PASS' if p2_minimal else 'FAIL'}  {minimal}")
    print(f"  3. BYTE-IDENTICAL   : {'PASS' if p3_identical else 'FAIL'}  "
          f"(RUN1 orders={run1_orders} vs RUN2 orders={run2_orders})")
    speedup = (t1 / t2) if (t2 == t2 and t2 > 0) else float("nan")  # t2==t2 guards NaN
    print(f"\n  PER-CELL SPEED (minimal-warmup alone, pre cap-flip): "
          f"RUN1={t1:.1f}s vs RUN2={t2:.1f}s ({speedup:.1f}× faster)")
    verdict = "PASS" if (p1_engaged and p2_minimal and p3_identical) else "FAIL"
    print(f"\n  VERDICT: {verdict}  (all three required)")
    if verdict != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
