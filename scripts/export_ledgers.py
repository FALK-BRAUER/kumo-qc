"""#339 — export full TRADE LEDGERS + the FY-end OPEN BOOK to /tmp/ledgers/ for HQ trade-level analysis.

Standing tool (every run going forward). Reads each config's archive trades.jsonl.gz → per-trade CSV;
plus the S1 FY-end OPEN BOOK, each open position CLASSIFIED via FY-end daily Ichimoku:
  RUNNER          = above Tenkan (trending — trail's job, never rotate)
  DEAD-GREEN-FLAT = PnL>0, below Tenkan, above Kijun (rotation-v2's evict target)
  DIP             = underwater (<=entry), above Kijun (let recover to stop)
  LOSER           = below/at Kijun (broken — stop's job)
RAM-safe (per-symbol Ichimoku streamed). Usage: python3 scripts/export_ledgers.py
"""
from __future__ import annotations

import csv
import datetime as _dt
import glob
import gzip
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from sweeps.warmup_cache.lean_indicators import Ichimoku  # noqa: E402
from sweeps.warmup_cache.table_builder import read_daily_zip  # noqa: E402

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")
_OUT = Path("/tmp/ledgers")
_CONFIGS = {"S1_sizing5": "65c0cf447168", "combined_cloud": "de53399c8125", "RUN_R_rotation": "6432fc649c54"}


def _fy_full_bt_ids(h: str) -> set[str]:
    """The backtest_ids that ran the fy2025_full window (NOT the quarter cells) — map via the run_dir."""
    ids = set()
    for bt in glob.glob(f"sweeps/runs/{h}/fy2025_full/backtests/*/"):
        for j in glob.glob(bt + "*.json"):
            if Path(j).stem.isdigit():
                ids.add(Path(j).stem)
    return ids


def _trades(h: str) -> list[dict]:
    """Trades from the FY-FULL cell specifically (a multi-cell archive also has quarter cells; the
    latest-mtime would be a quarter → wrong book). Match the archive cell whose backtest_id ran fy_full."""
    fy_ids = _fy_full_bt_ids(h)
    cells = glob.glob(f"results/archive/{h}/*/")
    chosen = None
    for c in cells:
        rj = Path(c) / "result.json"
        if rj.exists() and str(json.loads(rj.read_text()).get("backtest_id")) in fy_ids:
            chosen = c
            break
    if chosen is None:  # fallback: single-cell archive (no quarters) → newest
        tj = sorted(glob.glob(f"results/archive/{h}/*/trades.jsonl.gz"), key=lambda p: Path(p).stat().st_mtime)
        chosen = str(Path(tj[-1]).parent) + "/" if tj else None
    if chosen is None:
        return []
    tjs = glob.glob(chosen + "trades.jsonl.gz")
    if not tjs:
        return []
    return [json.loads(x) for x in gzip.decompress(Path(tjs[0]).read_bytes()).decode().splitlines()]


def _ichi_at(sym: str, asof: _dt.date):
    """FY-end daily (tenkan, kijun, cloud_bottom) — the last bar <= asof. None if no data."""
    zp = _DAILY / f"{sym.lower()}.zip"
    if not zp.exists():
        return None
    ich = Ichimoku()
    out = None
    for d, _o, h, l, c, _v in read_daily_zip(zp):
        if d > asof:
            break
        ich.update(h, l, c)
        if ich.is_ready:
            out = (ich.tenkan, ich.kijun, min(ich.senkou_a, ich.senkou_b))
    return out


def _export_trades(name: str, h: str) -> int:
    trades = _trades(h)
    if not trades:
        return 0
    cols = ["ticker", "entry_date", "entry_px", "exit_date", "exit_px", "exit_reason", "pnl_pct",
            "pnl_usd", "hold_days", "mfe", "mae", "censored", "decision_score", "side"]
    with (_OUT / f"{name}_{h}_trades.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in trades:
            dur = t.get("duration_sec")
            w.writerow([
                t.get("symbol"), (t.get("entry_dt") or "")[:10], t.get("entry_px"),
                (t.get("exit_dt") or "")[:10], t.get("exit_px"), t.get("exit_reason"),
                round(t["ret"] * 100, 3) if t.get("ret") is not None else "",
                round(t["pnl"], 2) if t.get("pnl") is not None else "",
                round(dur / 86400, 1) if dur else "", t.get("mfe"), t.get("mae"),
                t.get("censored"), t.get("decision_score"), t.get("side"),
            ])
    return len(trades)


def _export_open_book(name: str, h: str) -> int:
    opens = [t for t in _trades(h) if t.get("censored")]
    with (_OUT / f"{name}_{h}_openbook.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "entry_px", "last_px", "tenkan", "kijun", "cloud_bottom",
                    "pnl_pct", "days_held", "classification"])
        for t in opens:
            ed = _dt.date.fromisoformat(t["exit_dt"][:10])
            ind = _ichi_at(t["symbol"], ed)
            entry, last = float(t["entry_px"]), float(t["exit_px"])
            pnl_pct = (last / entry - 1) * 100 if entry else 0.0
            if ind is None:
                cls, tk, kj, cb = "NO_DATA", "", "", ""
            else:
                tk, kj, cb = ind
                if last >= tk:
                    cls = "RUNNER"
                elif last <= entry:
                    cls = "DIP" if last > kj else "LOSER"
                elif last <= kj:
                    cls = "LOSER"
                else:
                    cls = "DEAD_GREEN_FLAT"
            dur = t.get("duration_sec")
            w.writerow([t["symbol"], round(entry, 2), round(last, 2),
                        round(tk, 2) if tk != "" else "", round(kj, 2) if kj != "" else "",
                        round(cb, 2) if cb != "" else "", round(pnl_pct, 2),
                        round(dur / 86400, 1) if dur else "", cls])
    return len(opens)


def main() -> None:
    _OUT.mkdir(parents=True, exist_ok=True)
    for name, h in _CONFIGS.items():
        n = _export_trades(name, h)
        print(f"{name} ({h}): {n} trades → /tmp/ledgers/{name}_{h}_trades.csv")
    nb = _export_open_book("S1_sizing5", "65c0cf447168")
    print(f"S1 open book: {nb} open positions classified → /tmp/ledgers/S1_sizing5_65c0cf447168_openbook.csv")


if __name__ == "__main__":
    main()
