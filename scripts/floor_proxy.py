"""#339 STOP-FLOOR PROXY (HQ's decisive number) — dissolves the M2M-vs-realized fork.

A let-winners-run book on a finite backtest ALWAYS shows negative-realized (losers closed) +
big-unrealized (winners still riding, marked at LAST price = censored-high). Neither is the truth.
The bankable proxy: re-mark each OPEN (censored) position at its CURRENT TRAILING STOP — the daily
cloud-bottom (min Senkou A/B), where CloudAdherenceTrail/CloudProtectiveStop would exit it — instead
of last price. Sum → what the strategy actually pockets if every open winner stopped out today.

- floor-proxy stays STRONG (≈M2M) → winners have real locked-in gains below them → #270 edge GENUINE.
- floor-proxy COLLAPSES toward realized → M2M is air (peaks never banked) → edge illusory → sT10e.

Computes for S1 (65c0cf447168) + combined-cloud (de53399c8125). RAM-safe (one symbol streamed).
"""
from __future__ import annotations

import datetime as _dt
import glob
import gzip
import json
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / "src")]

from sweeps.warmup_cache.lean_indicators import Ichimoku  # noqa: E402
from sweeps.warmup_cache.table_builder import read_daily_zip  # noqa: E402

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")


def cloud_bottom_at(sym: str, asof: _dt.date) -> float | None:
    """Daily cloud bottom (min Senkou A/B) on the last bar <= asof — the trailing-stop level."""
    zp = _DAILY / f"{sym.lower()}.zip"
    if not zp.exists():
        return None
    ich = Ichimoku()
    last = None
    for d, _o, h, l, c, _v in read_daily_zip(zp):
        if d > asof:
            break
        ich.update(h, l, c)
        if ich.is_ready:
            last = min(ich.senkou_a, ich.senkou_b)
    return last


def _fy_full_cell(h: str) -> tuple[str, str]:
    """The archive cell that ran the fy2025_full window — NOT glob[0] (alphabetical → grabs a quarter
    cell once the sweep adds w1-w4, the bug that mis-read S1 as a -17% quarter). Match the archive
    cell whose result.json backtest_id is the one under sweeps/runs/{h}/fy2025_full/. Returns
    (trades_path, backtest_id) for transparency. Fail loud if it can't be identified unambiguously."""
    fy_ids = set()
    for bt in glob.glob(f"sweeps/runs/{h}/fy2025_full/backtests/*/"):
        for j in glob.glob(bt + "*.json"):
            if Path(j).stem.isdigit():
                fy_ids.add(Path(j).stem)
    cells = glob.glob(f"results/archive/{h}/*/")
    matches = []
    for c in cells:
        rj = Path(c) / "result.json"
        if not rj.exists():
            continue
        bid = str(json.loads(rj.read_text()).get("backtest_id"))
        if bid in fy_ids:
            matches.append((c, bid))
    # HARD-ASSERT the FY-full cell by backtest_id. NO len(cells)==1 silent fallback: a lone QUARTER
    # cell (FY-full not yet archived) would otherwise masquerade as the FY-full floor — the exact
    # silent-wrong-cell bug this function exists to kill. If it can't be identified, refuse to guess.
    if len(matches) != 1:
        raise RuntimeError(f"{h}: cannot pick FY-full cell unambiguously (fy_ids={sorted(fy_ids)}, "
                           f"matches={[m[1] for m in matches]}, cells={len(cells)}) — refuse to guess. "
                           f"Ensure sweeps/runs/{h}/fy2025_full/backtests/ has the FY-full run.")
    c, bt = matches[0]
    tjs = glob.glob(c + "trades.jsonl.gz")
    if not tjs:
        raise RuntimeError(f"{h}: FY-full cell {c} has no trades.jsonl.gz")
    return tjs[0], bt


def floor_proxy(h: str) -> dict:
    tj, bt = _fy_full_cell(h)
    trades = [json.loads(x) for x in gzip.decompress(Path(tj).read_bytes()).decode().splitlines()]
    realized = sum(t["pnl"] for t in trades if not t.get("censored"))
    m2m = sum(t["pnl"] for t in trades)
    floor_unreal = 0.0
    remarked = missing = 0
    detail = []
    for t in trades:
        if not t.get("censored"):
            continue
        ed = _dt.date.fromisoformat(t["exit_dt"][:10])
        cb = cloud_bottom_at(t["symbol"], ed)
        if cb is None:
            missing += 1
            floor_unreal += t["pnl"]  # fallback: keep its m2m mark if no daily data
            continue
        fp = t["qty"] * (cb - t["entry_px"])  # long: bankable if stopped at cloud-bottom today
        floor_unreal += fp
        remarked += 1
        detail.append((t["symbol"], round(t["entry_px"], 2), round(cb, 2), round(t["pnl"], 0), round(fp, 0)))
    return {
        "realized": realized, "m2m": m2m, "floor_total": realized + floor_unreal,
        "remarked": remarked, "missing": missing, "detail": sorted(detail, key=lambda x: x[4]),
        "bt": bt,
    }


def main() -> None:
    for h, name in [("65c0cf447168", "S1 sizing-5%"), ("de53399c8125", "combined-cloud"),
                    ("66801c5c1fcd", "rotation-v2 (S1+RotationV2)"),
                    ("6ee62f5d019a", "#342 regime-gate (S1+SpyIchimoku)")]:
        r = floor_proxy(h)
        pct = lambda v: f"{v / 100000 * 100:+.2f}%"  # noqa: E731
        print(f"\n=== {name} ({h}) === [FY-full cell bt={r['bt']}]")
        print(f"  REALIZED (closed):   ${r['realized']:>10,.0f}  {pct(r['realized'])}")
        print(f"  M2M (last-price):    ${r['m2m']:>10,.0f}  {pct(r['m2m'])}")
        print(f"  FLOOR-PROXY (stop):  ${r['floor_total']:>10,.0f}  {pct(r['floor_total'])}   "
              f"[{r['remarked']} remarked @ cloud-bottom, {r['missing']} missing→kept-m2m]")
        print(f"  open re-mark detail (sym, entry, cloud_bottom, m2m_pnl, floor_pnl), worst→best:")
        for row in r["detail"]:
            print(f"    {row}")


if __name__ == "__main__":
    main()
