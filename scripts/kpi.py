"""Standard run KPI + leaderboard — realised / unrealised / FLOOR-PROXY.

The let-run-correct reporting block. A let-winners-run book on a finite backtest ALWAYS shows a
negative REALISED tail (losers closed) + a big UNREALISED open book (winners still riding, marked at
last = censored-high). Neither is the truth:
  - M2M Net = realised + unrealised@last  (overstates — open winners marked at the peak)
  - FLOOR-PROXY = realised + open re-marked at the cloud-bottom stop = the BANKABLE value, the metric
    to rank on (the edge lives in the open book; rank by what you could actually bank).

Every run reports this block; the leaderboard ranks by floor-proxy. Drop-in for any local runner:
    from kpi import report_and_log
    report_and_log(run_dir, label, sharpe=m.sharpe, net_pct=m.ret_pct, dd_pct=m.dd_pct, fills=m.orders,
                   config_hash=cfg.config_hash, window=w.name, stamp="2026-06-05T14:00")
"""
from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path[:0] = [str(_ROOT / "scripts")]
from realized_ledger import ledger  # noqa: E402

BOARD = _ROOT / "results" / "leaderboard.csv"
FIELDS = ["stamp", "label", "config_hash", "window", "sharpe", "net_pct",
          "realized_pct", "unreal_pct", "floor_pct", "dd_pct", "fills", "open"]


def compute_kpi(run_dir, label: str, *, sharpe: float, net_pct: float, dd_pct: float, fills: int,
                config_hash: str = "", window: str = "fy2025_full",
                asof: _dt.date | None = None, stamp: str = "") -> dict:
    """The standard KPI row — combines the trio (from the adapter metrics) with the realised/
    unrealised/floor-proxy split (from the run's order-events). unreal@last = M2M Net − realised."""
    asof = asof or _dt.date(2025, 12, 31)
    le = ledger(Path(run_dir), asof)
    realized_pct = round(le["realized_pct"], 1)
    floor_pct = round(le["floor_pct"], 1)
    unreal_pct = round(net_pct - realized_pct, 1)   # M2M Net = realised + unreal@last
    return {"stamp": stamp, "label": label, "config_hash": config_hash, "window": window,
            "sharpe": round(sharpe, 3), "net_pct": round(net_pct, 1),
            "realized_pct": realized_pct, "unreal_pct": unreal_pct, "floor_pct": floor_pct,
            "dd_pct": round(dd_pct, 1), "fills": fills, "open": le["n_open"]}


def print_kpi(k: dict) -> None:
    """The standard one-line KPI block printed by every run."""
    print(f"  {k['label']}: Sharpe {k['sharpe']:+.3f} | Net {k['net_pct']:+.1f}% "
          f"(realised {k['realized_pct']:+.1f}% + unreal {k['unreal_pct']:+.1f}%) | "
          f"FLOOR-PROXY {k['floor_pct']:+.1f}% | DD {k['dd_pct']:.1f}% | fills {k['fills']} open {k['open']}",
          flush=True)


def append_leaderboard(k: dict, board: Path = BOARD) -> None:
    board.parent.mkdir(parents=True, exist_ok=True)
    # PARALLEL-SAFE: N concurrent cell-PROCESSES (run_fleet) append here. flock the header-check +
    # write so two processes can't interleave a partial row or double the header (the row-corruption
    # race the cap-2 byte-identical test guards against). Advisory lock, held only for the ~µs write
    # (never during the lean run) → no contention cost. `new` is judged by f.tell()==0 INSIDE the lock
    # (not exists()-before-open) so a racing creator can't make both writers think they're first.
    import fcntl
    with board.open("a", newline="") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if f.tell() == 0:
                w.writeheader()
            w.writerow({key: k.get(key, "") for key in FIELDS})
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def report_and_log(run_dir, label: str, *, board: Path = BOARD, **kw) -> dict:
    """Compute → print → append to the leaderboard. The single call a runner makes per cell."""
    k = compute_kpi(run_dir, label, **kw)
    print_kpi(k)
    append_leaderboard(k, board)
    return k


def print_leaderboard(board: Path = BOARD, window: str = "fy2025_full") -> None:
    """Ranked by FLOOR-PROXY (the bankable, let-run-correct metric) — not M2M."""
    if not board.exists():
        print("(empty leaderboard)")
        return
    rows = [r for r in csv.DictReader(board.open()) if not window or r["window"] == window]
    rows.sort(key=lambda r: float(r["floor_pct"] or -1e9), reverse=True)
    print(f"=== LEADERBOARD ({window}) — ranked by FLOOR-PROXY (bankable, not M2M) ===", flush=True)
    print(f"  {'label':28} {'Sharpe':>7} {'Net%':>7} {'realₚ%':>7} {'unrealₚ%':>8} {'FLOOR%':>7} {'DD%':>6} {'fills':>5}", flush=True)
    for r in rows:
        print(f"  {r['label'][:28]:28} {r['sharpe']:>7} {r['net_pct']:>7} {r['realized_pct']:>7} "
              f"{r['unreal_pct']:>8} {r['floor_pct']:>7} {r['dd_pct']:>6} {r['fills']:>5}", flush=True)


if __name__ == "__main__":
    print_leaderboard()
