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


def parse_decision_trace(log_path: Path) -> list[dict]:
    """Parse DECISIONTRACE|date|ticker|fate|score lines from a bt log.txt → records. The #348
    NON-TRADES substrate: every SCORED candidate's signal fate (passed/sub_min_score/parabolic)."""
    out = []
    for line in Path(log_path).read_text(errors="ignore").splitlines():
        i = line.find("DECISIONTRACE|")
        if i < 0:
            continue
        parts = line[i:].split("|")
        if len(parts) < 5:
            continue
        _tag, date, ticker, fate, score = parts[0], parts[1], parts[2], parts[3], parts[4]
        out.append({"date": date, "ticker": ticker, "fate": fate,
                    "score": int(score) if score.strip().lstrip("-").isdigit() else None})
    return out


def non_trade_outcomes(trace: list[dict], entered: set[str], window_end: _dt.date,
                       missed_threshold: float = 30.0) -> list[dict]:
    """For each SCORED-but-NOT-ENTERED candidate (the first day it scored), the forward peak return to
    window_end → MISSED_WINNER (peak >= missed_threshold) vs CORRECTLY_AVOIDED. Directly attacks entry
    discrimination: did the pipeline screen out names that would have won?"""
    # CASE NORMALISATION (mandatory): DECISIONTRACE tickers are LOWERCASE (ranked_candidates), the
    # trade-ledger `entered` symbols are UPPERCASE — compare via canonical_symbol_key on BOTH sides or
    # every entered name leaks back as a false MISSED_WINNER (the FIX3 .lower-vs-.value trap). Fail loud
    # if the join never collides (a case/key regression) rather than silently inflating the count.
    from engine.symbol_key import canonical_symbol_key  # noqa: PLC0415
    entered_keys = {canonical_symbol_key(s) for s in entered}
    trace_keys = {canonical_symbol_key(r["ticker"]) for r in trace}
    if entered_keys and not (entered_keys & trace_keys):
        raise RuntimeError(
            f"non_trade_outcomes: ZERO overlap between entered ({len(entered_keys)}) and traced "
            f"({len(trace_keys)}) keys — case/key mismatch would inflate missed-winners. Refuse.")
    first_seen: dict[str, dict] = {}
    for r in trace:
        if canonical_symbol_key(r["ticker"]) in entered_keys:
            continue  # it entered — a trade, not a non-trade
        tk = r["ticker"]
        if tk not in first_seen or r["date"] < first_seen[tk]["date"]:
            first_seen[tk] = r
    rows = []
    for tk, r in first_seen.items():
        ed = _dt.date.fromisoformat(r["date"])
        fwd = forward_return(tk, ed, window_end)
        rows.append({
            "ticker": tk, "first_scored": r["date"], "fate": r["fate"], "score": r["score"],
            "forward_peak_pct": None if fwd is None else round(fwd, 1),
            "verdict": ("NO_DATA" if fwd is None
                        else "MISSED_WINNER" if fwd >= missed_threshold else "correctly_avoided"),
        })
    rows.sort(key=lambda x: (x["forward_peak_pct"] is None, -(x["forward_peak_pct"] or 0)))
    return rows


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
    # Split: CLOSED trades = a real exit-quality leak (exit_px is a decision); CENSORED = open at
    # year-end (exit_px is the Dec-31 mark, NOT an exit) → report separately, never as one headline.
    closed = [r for r in rows if not r["censored"]]
    cens = [r for r in rows if r["censored"]]
    left_closed = sum(r["left_on_table_pct"] for r in closed)
    left_cens = sum(r["left_on_table_pct"] for r in cens)
    print(f"{h}: {len(rows)} trades ({len(closed)} closed, {len(cens)} censored) → {out}")
    print(f"  CLOSED left-on-table {left_closed:.0f}% (real exit-quality leak); "
          f"CENSORED {left_cens:.0f}% (open@year-end mark, not an exit). worst 8:")
    for r in rows[:8]:
        print(f"    {r['symbol']:6} entry {r['entry_dt']} realized {r['realized_pct']:+.1f}% "
              f"peak {r['peak_pct']:+.1f}% LEFT {r['left_on_table_pct']:+.1f}% (high {r['hold_high_date']})")


if __name__ == "__main__":
    main()
