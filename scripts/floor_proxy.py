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


def floor_proxy(h: str) -> dict:
    tj = glob.glob(f"results/archive/{h}/*/trades.jsonl.gz")[0]
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
    }


def main() -> None:
    for h, name in [("65c0cf447168", "S1 sizing-5%"), ("de53399c8125", "combined-cloud")]:
        r = floor_proxy(h)
        pct = lambda v: f"{v / 100000 * 100:+.2f}%"  # noqa: E731
        print(f"\n=== {name} ({h}) ===")
        print(f"  REALIZED (closed):   ${r['realized']:>10,.0f}  {pct(r['realized'])}")
        print(f"  M2M (last-price):    ${r['m2m']:>10,.0f}  {pct(r['m2m'])}")
        print(f"  FLOOR-PROXY (stop):  ${r['floor_total']:>10,.0f}  {pct(r['floor_total'])}   "
              f"[{r['remarked']} remarked @ cloud-bottom, {r['missing']} missing→kept-m2m]")
        print(f"  open re-mark detail (sym, entry, cloud_bottom, m2m_pnl, floor_pnl), worst→best:")
        for row in r["detail"]:
            print(f"    {row}")


if __name__ == "__main__":
    main()
