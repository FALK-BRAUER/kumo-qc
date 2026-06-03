"""#348 deep instrumentation — EXIT-LEAKAGE + per-window LOCAL HIGHS/LOWS + NON-TRADE forward outcome.

Three analyses (Falk methodology, epic #348), post-hoc over the daily bars + a config's trade ledger:
  (b) EXIT-LEAKAGE — per trade: the local HIGH during the hold vs the actual exit = left-on-table.
  (a) LOCAL EXTREMES — per name over a window: high/low + their dates (exit-quality + missed-winner).
  (c) NON-TRADE forward outcome — for a screened-out candidate, what it would have done (needs the
      decision-trace non-entered list from the engine emitter; this module provides the forward-outcome
      primitive `forward_return`, joined to that list by the caller / a later build step).

RAM-safe: one symbol's daily zip streamed at a time (never concat-all). Mirrors floor_proxy/export_
ledgers. Reuses floor_proxy._fy_full_cell (FY-full cell by backtest_id, NOT glob[0]).

Usage: python3 scripts/instrument_analysis.py <config_hash>   (default S1 65c0cf447168)
"""
from __future__ import annotations

import csv
import datetime as _dt
import gzip
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

from floor_proxy import _fy_full_cell  # noqa: E402  (shared FY-full cell selector)
from sweeps.warmup_cache.table_builder import read_daily_zip  # noqa: E402

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")
_OUT = Path("/tmp/ledgers")


def _bars(sym: str, start: _dt.date, end: _dt.date) -> list[tuple[_dt.date, float, float, float]]:
    """(date, high, low, close) for sym over [start, end] inclusive. Empty if no zip. Streamed."""
    zp = _DAILY / f"{sym.lower()}.zip"
    if not zp.exists():
        return []
    out = []
    for d, _o, h, l, c, _v in read_daily_zip(zp):
        if d < start:
            continue
        if d > end:
            break
        out.append((d, float(h), float(l), float(c)))
    return out


def local_extremes(sym: str, start: _dt.date, end: _dt.date):
    """(high, high_date, low, low_date) over the window; None if no data."""
    bars = _bars(sym, start, end)
    if not bars:
        return None
    hi = max(bars, key=lambda b: b[1])
    lo = min(bars, key=lambda b: b[2])
    return hi[1], hi[0], lo[2], lo[0]


def forward_return(sym: str, entry_date: _dt.date, horizon_end: _dt.date) -> float | None:
    """A non-trade 'would it have won': peak return from the close on entry_date to the window's local
    high through horizon_end. Uses the entry-date close as the hypothetical entry. None if no data."""
    bars = _bars(sym, entry_date, horizon_end)
    if not bars:
        return None
    entry_close = bars[0][3]
    if entry_close <= 0:
        return None
    peak = max(b[1] for b in bars)
    return (peak / entry_close - 1.0) * 100.0


def _trades(h: str) -> list[dict]:
    tj, _bt = _fy_full_cell(h)
    return [json.loads(x) for x in gzip.decompress(Path(tj).read_bytes()).decode().splitlines()]


def exit_leakage(h: str) -> list[dict]:
    """Per trade: local high DURING the hold [entry_dt, exit_dt] vs actual exit_px → left-on-table.
    left_pct = (hold_high - exit_px)/entry_px * 100 (the extra % of the entry stake the peak would have
    captured beyond where it actually exited). Censored (open-at-end) marked separately."""
    rows = []
    for t in _trades(h):
        ed = _dt.date.fromisoformat(t["entry_dt"][:10])
        xd = _dt.date.fromisoformat(t["exit_dt"][:10])
        ext = local_extremes(t["symbol"], ed, xd)
        entry_px = float(t["entry_px"]); exit_px = float(t["exit_px"])
        if ext is None or entry_px <= 0:
            continue
        hold_high, hi_date, _lo, _lod = ext
        left_pct = (hold_high - exit_px) / entry_px * 100.0
        rows.append({
            "symbol": t["symbol"], "entry_dt": t["entry_dt"][:10], "exit_dt": t["exit_dt"][:10],
            "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
            "hold_high": round(hold_high, 2), "hold_high_date": str(hi_date),
            "realized_pct": round((exit_px / entry_px - 1) * 100, 2),
            "peak_pct": round((hold_high / entry_px - 1) * 100, 2),
            "left_on_table_pct": round(left_pct, 2),
            "censored": bool(t.get("censored")), "exit_reason": t.get("exit_reason"),
        })
    rows.sort(key=lambda r: r["left_on_table_pct"], reverse=True)
    return rows


def main() -> None:
    h = sys.argv[1] if len(sys.argv) > 1 else "65c0cf447168"
    _OUT.mkdir(parents=True, exist_ok=True)
    rows = exit_leakage(h)
    if not rows:
        raise SystemExit(f"{h}: no exit-leakage rows (no trades / no daily data) — refuse to emit empty")
    out = _OUT / f"{h}_exit_leakage.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    tot_left = sum(r["left_on_table_pct"] for r in rows)
    print(f"{h}: {len(rows)} trades → {out}")
    print(f"  total left-on-table {tot_left:.0f}% of entry-stake (sum across trades); worst 8:")
    for r in rows[:8]:
        print(f"    {r['symbol']:6} entry {r['entry_dt']} realized {r['realized_pct']:+.1f}% "
              f"peak {r['peak_pct']:+.1f}% LEFT {r['left_on_table_pct']:+.1f}% (high {r['hold_high_date']})")


if __name__ == "__main__":
    main()
