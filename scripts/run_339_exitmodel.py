"""#339-RUN1 EXIT-MODEL SCREEN — prover-gated loser-exit E1/E2/E3 on FY. The lever that fixes the
realized -15.2% loser tail WITHOUT touching the winners (the prover-gate exempts proved monsters).
trim+cache fast infra. Judged on the realized-loser-tail + the trio + survival-ledger (HOOD/KGC sells
must = 0 — provers are exempt) vs S1 (1.025/+27.7%/DD19.4%/55, realized -15.2%).

config_hash is base_module-independent (SweepConfig sees only choices/warmup/continuous_weekly) → the
3 variants share a hash; each runs in its own runs_root (sweeps/runs_339exit/<variant>/). We read the
realized/trade detail from each variant's OWN order-events (distinct dir) — no shared-archive collision.

Usage: python3 scripts/run_339_exitmodel.py [e1|e2|e3 ...]   (default: e1 e2 e3)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402
from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig, Window  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
RUNS = _ROOT / "sweeps" / "runs_339exit"
FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)

VARIANTS = [
    ("e1", "strategies.exit_e1", "prover-gated fixed -8%"),
    ("e2", "strategies.exit_e2", "prover-gated weekly-Kijun"),
    ("e3", "strategies.exit_e3", "prover-gated weekly-cloud-top"),
]


def _realized_and_monster_sells(run_dir: Path) -> tuple[int, int, dict]:
    """(loser_exit_cuts, monster_sell_check) from the variant's order-events + log. Returns
    (n_fills, n_loser_exits, {HOOD/KGC sell counts})."""
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not bts:
        return 0, 0, {}
    bt = bts[0]
    oe = next(bt.glob("*-order-events.json"), None)
    log = bt / "log.txt"
    n_fills = 0
    monster = {}
    if oe is not None:
        ev = json.loads(oe.read_text())
        ev = ev.get("orderEvents", ev) if isinstance(ev, dict) else ev
        for e in ev:
            if str(e.get("status", "")).lower() != "filled":
                continue
            n_fills += 1
            s = e.get("symbol", {}); s = s.get("value", s) if isinstance(s, dict) else s
            if str(s) in ("HOOD", "KGC") and float(e.get("fillQuantity", 0)) < 0:
                monster[str(s)] = monster.get(str(s), 0) + 1
    n_loser = 0
    if log.exists():
        try:
            n_loser = log.read_text(errors="ignore").count("LOSER_EXIT_")
        except OSError:
            pass
    return n_fills, n_loser, monster


def main() -> None:
    sel = [a.lower() for a in sys.argv[1:]] or ["e1", "e2", "e3"]
    rows = []
    print(f"=== #339-RUN1 EXIT-MODEL SCREEN — {sel} on FY vs S1 1.025/+27.7%/DD19.4%/55 (realized -15.2%) ===", flush=True)
    for vkey, vmod, vlabel in VARIANTS:
        if vkey not in sel:
            continue
        sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}), "base_module": vmod}
        adapter = make_local_run(runs_root=RUNS / vkey, warmup_gate=None, ensure_weekly_cache_fp=_FP)
        print(f"\n--- {vkey} [{vlabel}] FY ---", flush=True)
        m = adapter(TRIM, FY)
        # STANDARD KPI (realised/unrealised/floor-proxy) → printed + logged to the leaderboard.
        from kpi import report_and_log  # noqa: E402
        cell = RUNS / vkey / TRIM.config_hash / FY.name
        k = report_and_log(cell, f"#339 {vkey} {vlabel}", sharpe=m.sharpe, net_pct=m.ret_pct,
                           dd_pct=m.dd_pct, fills=m.orders, config_hash=TRIM.config_hash,
                           window=FY.name, stamp="2026-06-05")
        _, _, monster = _realized_and_monster_sells(RUNS / vkey)
        msell = ", ".join(f"{kk}={vv}" for kk, vv in monster.items()) or "0 (monsters exempt ✓)"
        print(f"    monster-sells: {msell}", flush=True)
        rows.append((vkey, m.sharpe, m.ret_pct, m.dd_pct, m.orders, k["realized_pct"], k["floor_pct"], msell))

    print(f"\n=== EXIT-MODEL GRID — vs S1 1.025/+27.7%/DD19.4%/55 (WIN = Ret/Sharpe↑, monsters survive, loser-tail↓) ===", flush=True)
    for vkey, sh, rt, dd, od, nf, nl, msell in rows:
        print(f"  {vkey}: {sh:+.3f}/{rt:+.1f}%/DD{dd:.1f}%/{od}ord  fills={nf} loser-cuts={nl}  monster-sells={msell}", flush=True)
    print(f"\nDIRS: {RUNS}/<variant>/ — order-events + LOSER_EXIT_<variant> log lines (what got cut + at what %).", flush=True)


if __name__ == "__main__":
    main()
