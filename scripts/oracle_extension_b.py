"""B-ORACLE (HQ) — pre-flight gate for direction B (extension-at-entry filter). Before BUILDING B,
measure whether the Jan-2025 LOSERS entered more EXTENDED than the Jan-2025 MONSTERS. If separable
(losers measurably more extended above their own cloud-top/kijun at entry) → B has a shot, build it.
If same (losers ≈ monsters) → it's the #349 coin-flip (no entry feature discriminates), B is dead on
arrival → skip. Pure read-only: reconstruct S1 FY entries from order-events, compute Ichimoku at the
entry bar from daily data. No BT, no machine.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
from collections import defaultdict
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parents[1])]
from sweeps.warmup_cache.lean_indicators import Ichimoku  # noqa: E402
from sweeps.warmup_cache.table_builder import read_daily_zip  # noqa: E402

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")


def entries_from_s1():
    d = glob.glob("sweeps/runs_340fy/matrix_sz050_off/fy2025/*/fy2025")
    oe = glob.glob(d[0] + "/backtests/*/*-order-events.json")[0]
    ev = json.loads(open(oe).read()); ev = ev.get("orderEvents", ev) if isinstance(ev, dict) else ev
    fills = defaultdict(list)
    for e in ev:
        if str(e.get("status", "")).lower() != "filled":
            continue
        s = e.get("symbol", {}); s = s.get("value", s) if isinstance(s, dict) else s
        n = str(s).split(" ")[0]
        t = float(e.get("time") or e.get("utcTime") or 0)
        fills[n].append((t, float(e.get("fillQuantity", 0)), float(e.get("fillPrice", 0))))
    out = {}
    for n, fl in fills.items():
        fl.sort()
        buys = [(t, q, p) for t, q, p in fl if q > 0]
        if not buys:
            continue
        bvol = sum(q for _, q, _ in buys); svol = sum(-q for _, q, _ in fl if _ and False) or sum(-q for t, q, p in fl if q < 0)
        ed = _dt.datetime.utcfromtimestamp(buys[0][0]).date()
        closed = svol >= bvol * 0.99
        out[n] = {"entry": ed, "closed": closed}
    return out


def extension_at(sym: str, asof: _dt.date):
    """(price, cloud_top, kijun, ext_cloud_pct, ext_kijun_pct) at asof from daily Ichimoku, or None."""
    zp = _DAILY / f"{sym.lower()}.zip"
    if not zp.exists():
        return None
    ich = Ichimoku()
    last = None
    for d, _o, h, l, c, _v in read_daily_zip(zp):
        ich.update(h, l, c)
        if d <= asof and ich.is_ready:
            ct = max(ich.senkou_a, ich.senkou_b); kj = ich.kijun
            last = (c, ct, kj, (c - ct) / ct * 100.0 if ct else None, (c - kj) / kj * 100.0 if kj else None)
        if d > asof:
            break
    return last


def main():
    ent = entries_from_s1()
    jan = {n: v for n, v in ent.items() if v["entry"].strftime("%Y-%m") == "2025-01"}
    losers = {n: v for n, v in jan.items() if v["closed"]}
    monsters = {n: v for n, v in jan.items() if not v["closed"]}
    print(f"Jan-2025 entries: {len(losers)} closed-losers, {len(monsters)} held-monsters\n")
    rows = {"LOSER": [], "MONSTER": []}
    for grp, names in (("LOSER", losers), ("MONSTER", monsters)):
        print(f"=== {grp}S ===")
        for n, v in sorted(names.items()):
            x = extension_at(n, v["entry"])
            if x is None:
                print(f"  {n:6} entry {v['entry']} — no daily data"); continue
            print(f"  {n:6} entry {v['entry']}  px {x[0]:.2f}  ext-vs-cloudtop {x[3]:+.1f}%  ext-vs-kijun {x[4]:+.1f}%")
            if x[3] is not None and x[4] is not None:
                rows[grp].append((x[3], x[4]))
    print()
    for grp in ("LOSER", "MONSTER"):
        r = rows[grp]
        if not r:
            continue
        ec = sorted(v[0] for v in r); ek = sorted(v[1] for v in r)
        med = lambda a: a[len(a) // 2]
        print(f"{grp:8} n={len(r)}  cloud-ext median {med(ec):+.1f}% mean {sum(ec)/len(ec):+.1f}% range[{ec[0]:+.1f},{ec[-1]:+.1f}]  |  kijun-ext median {med(ek):+.1f}% mean {sum(ek)/len(ek):+.1f}%")
    print("\nVERDICT: losers MORE extended (separable) → build B. losers ≈ monsters → #349 coin-flip, SKIP B.")


if __name__ == "__main__":
    main()
