"""#339-RUN1 realized + floor-proxy ledger — computed DIRECTLY from a run's order-events (FIFO buy/sell
match), bypassing the shared-trim-config_hash archive collision that broke floor_proxy(hash). For each
variant: REALIZED P&L (closed trades) + FLOOR-PROXY (open positions re-marked at their cloud-bottom
stop, reusing floor_proxy.cloud_bottom_at) + the open-monster check.

Usage: python3 scripts/realized_ledger.py <run_dir> [asof YYYY-MM-DD]
  run_dir = sweeps/runs_339exit/<variant>/<hash>/fy2025_full   (or any cell dir with backtests/)
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from collections import defaultdict, deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "scripts")]
import floor_proxy as fp  # noqa: E402  (cloud_bottom_at)

_CAPITAL = 100_000.0


def _fills(run_dir: Path) -> list[tuple]:
    # robust to either a CELL dir (has backtests/<ts>/) or a backtests/<ts> dir directly (has the json).
    oe = next(run_dir.glob("*-order-events.json"), None)
    if oe is None:
        bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
        oe = next(bts[0].glob("*-order-events.json"), None) if bts else None
    if oe is None:
        return []
    ev = json.loads(oe.read_text())
    ev = ev.get("orderEvents", ev) if isinstance(ev, dict) else ev
    out = []
    for e in ev:
        if str(e.get("status", "")).lower() != "filled":
            continue
        s = e.get("symbol", {}); s = s.get("value", s) if isinstance(s, dict) else s
        out.append((str(e.get("time", e.get("utcTime", ""))), str(s),
                    float(e.get("fillQuantity", 0)), float(e.get("fillPrice", 0))))
    out.sort()  # by time
    return out


def ledger(run_dir: Path, asof: _dt.date) -> dict:
    lots: dict[str, deque] = defaultdict(deque)   # sym → deque([qty, price])
    realized = 0.0
    realized_losers = 0.0
    for _t, sym, qty, price in _fills(run_dir):
        if qty > 0:
            lots[sym].append([qty, price])
        else:
            sell = -qty
            while sell > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                matched = min(sell, lot[0])
                pnl = matched * (price - lot[1])
                realized += pnl
                if pnl < 0:
                    realized_losers += pnl
                lot[0] -= matched; sell -= matched
                if lot[0] <= 1e-9:
                    lots[sym].popleft()
    # open positions → re-mark at cloud-bottom (the floor); fall back to entry if no cloud data
    floor_unreal = 0.0
    open_pos = {}
    for sym, dq in lots.items():
        q = sum(l[0] for l in dq)
        if q <= 1e-9:
            continue
        cost = sum(l[0] * l[1] for l in dq)
        avg = cost / q
        cb = fp.cloud_bottom_at(sym.split(" ")[0], asof)  # strip the LEAN SID suffix → bare ticker
        mark = cb if cb is not None else avg
        floor_unreal += q * (mark - avg)
        open_pos[sym] = (q, round(avg, 2), None if cb is None else round(cb, 2))
    return {
        "realized": realized, "realized_pct": realized / _CAPITAL * 100.0,
        "realized_losers": realized_losers, "realized_losers_pct": realized_losers / _CAPITAL * 100.0,
        "floor_total": realized + floor_unreal, "floor_pct": (realized + floor_unreal) / _CAPITAL * 100.0,
        "n_open": len(open_pos), "open_pos": open_pos,
    }


def main() -> None:
    run_dir = Path(sys.argv[1])
    asof = _dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else _dt.date(2025, 12, 31)
    r = ledger(run_dir, asof)
    print(f"{run_dir.parent.parent.name if run_dir.name=='fy2025_full' else run_dir.name}:")
    print(f"  REALIZED:        ${r['realized']:>11,.0f}  ({r['realized_pct']:+.1f}%)   vs S1 -15.2%")
    print(f"  realized LOSERS: ${r['realized_losers']:>11,.0f}  ({r['realized_losers_pct']:+.1f}%)  (the tail)")
    print(f"  FLOOR-PROXY:     ${r['floor_total']:>11,.0f}  ({r['floor_pct']:+.1f}%)   vs S1 +21.13%   [open re-marked @cloud-bottom]")
    print(f"  open positions:  {r['n_open']}")


if __name__ == "__main__":
    main()
