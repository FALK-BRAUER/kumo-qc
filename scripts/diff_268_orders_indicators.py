"""#268 root-cause localization via the RELIABLE channel (cloud ORDERS + local indicators).

Resolves the two surviving #268 candidates without waiting on the flaky /chart/read capture:

  (d) SPY-MA200 REGIME-TIMING — does cloud BUY on dates local's regime gate BLOCKS?
      Local regime-blocked days := dates where local Regime/spy_close < Regime/spy_ma200.
      Count cloud BUY orders that land on a local-blocked day. Each such order is a day
      where cloud's regime was OPEN while local's was CLOSED => a regime-timing divergence.

  (c) SCORING / conformed-vs-native bar-set — does local SCORE the cloud-traded probe names
      below the qualify threshold (7) on cloud's BUY dates?
      For each probe (DRI/CME/AMZN/COST/CRWD/KGC): find cloud's BUY date(s) from the orders,
      read local Score/<probe> on that date. score < 7 (or -1 sentinel = not active) on a
      cloud-buy date => local did NOT qualify the name cloud bought => scoring divergence.
      Per #268-local, local maintained-indicators == clean local recompute, so a <7 local
      score on a cloud-buy date points to the INPUT DATA (conformed daily vs QC-native daily
      bar set), not a local compute bug.

Inputs (all REAL artifacts; nothing fabricated):
  research/parity/artifacts/cloud-orders-243.json     (291 cloud orders, this run)
  research/parity/artifacts/local-indicators-243.json (local FY2025 series, 497 pts each)
  research/parity/artifacts/cloud-indicators-243.json  (OPTIONAL; the direct cloud series diff
                                                         if the capture has landed)

Diagnostic only. RAW. No champion/dist/src touched.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ART = Path(__file__).resolve().parents[1] / "research" / "parity" / "artifacts"
CLOUD_ORDERS = ART / "cloud-orders-243.json"
LOCAL_IND = ART / "local-indicators-243.json"
CLOUD_IND = ART / "cloud-indicators-243.json"

QUALIFY_THRESHOLD = 7  # Score >= 7 qualifies; -1 = sentinel (name not active that day)
PROBES = ["DRI", "CME", "AMZN", "COST", "CRWD", "KGC"]
DIR_BUY = 0  # OrderDirection.Buy


def _date_of(epoch_seconds: float) -> dt.date:
    """Local chart timestamps are US/Eastern wall-clock epoch seconds; take the UTC calendar
    date of the sample. Both sides use the same convention, so date-keying is consistent."""
    return dt.datetime.fromtimestamp(epoch_seconds, tz=dt.timezone.utc).date()


def _series_by_date(points: list[list[float]]) -> dict[dt.date, float]:
    """Collapse [epoch, value] points to a {date: value} map (last sample of a date wins)."""
    out: dict[dt.date, float] = {}
    for ts, val in points:
        out[_date_of(ts)] = val
    return out


def load_local() -> dict[str, Any]:
    d: dict[str, Any] = json.loads(LOCAL_IND.read_text())
    return d


def load_cloud_orders() -> list[dict[str, Any]]:
    d = json.loads(CLOUD_ORDERS.read_text())
    orders: list[dict[str, Any]] = d["orders"] if isinstance(d, dict) else d
    return orders


def cloud_buy_dates_by_symbol(orders: list[dict[str, Any]]) -> dict[str, list[dt.date]]:
    out: dict[str, list[dt.date]] = {}
    for o in orders:
        if o.get("direction") != DIR_BUY:
            continue
        sym = o["symbol"]["value"]
        # order 'time' is ISO UTC; the QC fill date is its calendar date
        d = dt.datetime.fromisoformat(o["time"].replace("Z", "+00:00")).date()
        out.setdefault(sym, []).append(d)
    for sym in out:
        out[sym].sort()
    return out


def main() -> None:
    local = load_local()
    charts = local["charts"]
    orders = load_cloud_orders()

    spy_close = _series_by_date(charts["Regime"]["spy_close"])
    spy_ma200 = _series_by_date(charts["Regime"]["spy_ma200"])
    n_qual = _series_by_date(charts["Signal"]["n_qualifying"])
    scores = {p: _series_by_date(charts["Score"][p]) for p in PROBES}

    # local regime-blocked days: spy_close < spy_ma200 (both present that date)
    local_dates = sorted(d for d in spy_close if d in spy_ma200)
    blocked = [d for d in local_dates if spy_close[d] < spy_ma200[d]]
    blocked_set = set(blocked)

    buys_by_sym = cloud_buy_dates_by_symbol(orders)
    all_buys = [(sym, d) for sym, ds in buys_by_sym.items() for d in ds]

    # ---- (d) regime-timing ----
    buys_on_blocked = [(sym, d) for (sym, d) in all_buys if d in blocked_set]
    # cluster the blocked window
    blk_first = blocked[0] if blocked else None
    blk_last = blocked[-1] if blocked else None

    # ---- (c) scoring on cloud-buy dates ----
    probe_rows: list[dict[str, Any]] = []
    for p in PROBES:
        sc = scores[p]
        bdates = buys_by_sym.get(p, [])
        for bd in bdates:
            # nearest local score on/just-before the buy date (local series is daily)
            val = sc.get(bd)
            note = "exact-date"
            if val is None:
                prior = [d for d in sc if d <= bd]
                if prior:
                    nd = max(prior)
                    val = sc[nd]
                    note = f"nearest-prior {nd.isoformat()}"
                else:
                    note = "no-local-sample"
            qualified = val is not None and val >= QUALIFY_THRESHOLD
            probe_rows.append({
                "probe": p, "cloud_buy_date": bd.isoformat(),
                "local_score": val, "note": note,
                "local_qualified(>=7)": qualified,
                "local_regime_blocked": bd in blocked_set,
                "local_spy_close": spy_close.get(bd),
                "local_spy_ma200": spy_ma200.get(bd),
                "local_n_qualifying": n_qual.get(bd),
            })

    # optional direct cloud-series diff (only if capture landed)
    cloud_ma_diff: dict[str, Any] | None = None
    if CLOUD_IND.exists():
        try:
            cl = json.loads(CLOUD_IND.read_text())
            cch = cl.get("charts", {})
            if "Regime" in cch and "spy_ma200" in cch["Regime"]:
                c_ma = _series_by_date(cch["Regime"]["spy_ma200"])
                c_close = _series_by_date(cch["Regime"].get("spy_close", []))
                common = sorted(set(c_ma) & set(spy_ma200))
                gaps = [abs(c_ma[d] - spy_ma200[d]) for d in common]
                c_blocked = {d for d in common if d in c_close and c_close[d] < c_ma[d]}
                cloud_ma_diff = {
                    "landed": True,
                    "common_dates": len(common),
                    "max_ma200_abs_gap": max(gaps) if gaps else None,
                    "mean_ma200_abs_gap": (sum(gaps) / len(gaps)) if gaps else None,
                    "cloud_blocked_days": len(c_blocked),
                    "local_blocked_days": len(blocked_set),
                    "block_days_differ": len(c_blocked ^ blocked_set),
                }
        except Exception as e:  # noqa: BLE001 — diagnostic, never crash on a partial capture
            cloud_ma_diff = {"landed": "partial/unreadable", "error": str(e)}

    report = {
        "backtest": json.loads(CLOUD_ORDERS.read_text()).get("backtestId")
        if isinstance(json.loads(CLOUD_ORDERS.read_text()), dict) else None,
        "totals": {
            "cloud_orders": len(orders),
            "cloud_buys": len(all_buys),
            "cloud_sells": len(orders) - len(all_buys),
            "local_total_orders": local["trio_inert_confirm"]["total_orders"],
            "local_trio": local["trio_inert_confirm"],
        },
        "d_regime_timing": {
            "local_blocked_day_count": len(blocked_set),
            "local_blocked_window": [blk_first.isoformat() if blk_first else None,
                                     blk_last.isoformat() if blk_last else None],
            "cloud_buys_on_local_blocked_days": len(buys_on_blocked),
            "share_of_cloud_buys": (len(buys_on_blocked) / len(all_buys)) if all_buys else None,
            "examples": [{"symbol": s, "date": d.isoformat(),
                          "spy_close": spy_close.get(d), "spy_ma200": spy_ma200.get(d)}
                         for s, d in buys_on_blocked[:20]],
            "cloud_indicators_direct_diff": cloud_ma_diff,
        },
        "c_scoring": {
            "qualify_threshold": QUALIFY_THRESHOLD,
            "probe_rows": probe_rows,
            "summary": {
                p: {
                    "cloud_buy_dates": [d.isoformat() for d in buys_by_sym.get(p, [])],
                    "any_buy": bool(buys_by_sym.get(p)),
                } for p in PROBES
            },
        },
    }

    out = ART / "268-diff-orders-vs-local-indicators.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
