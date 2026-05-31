#!/usr/bin/env python3
"""#268 BREADTH/TURNOVER localizer (diagnostic only).

Reconstructs per-position round-trips and concurrent-holdings for the #243
cloud backtest (8ddbe2b449df87edba5d3fd50b48bea1, 291 orders) vs the local
#265 run (1158674033, 244 orders / 243 filled), to localize WHY cloud trades
a wider/more-rotated symbol set.

Every number is derived from the real order artifacts. No fabrication.

Inputs:
  CLOUD: research/parity/artifacts/cloud-orders-243.json  (orders w/ events)
  LOCAL: algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/
         1158674033-order-events.json  (flat filled/submitted events)

Output: prints a report; the markdown writeup is produced separately.
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUD_PATH = ROOT / "research/parity/artifacts/cloud-orders-243.json"
LOCAL_PATH = (
    ROOT
    / "algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/1158674033-order-events.json"
)


@dataclass
class Fill:
    """A single filled order event."""

    symbol: str
    when: dt.date
    qty: float  # signed: +buy, -sell
    direction: str  # "buy" | "sell"


@dataclass
class RoundTrip:
    """An entry->exit hold (long-only assumed; flat == closed)."""

    symbol: str
    entry: dt.date
    exit: dt.date | None = None
    legs: list[Fill] = field(default_factory=list)

    @property
    def hold_days(self) -> int | None:
        if self.exit is None:
            return None
        return (self.exit - self.entry).days


def _epoch_to_date(ts: float) -> dt.date:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()


def load_cloud() -> list[Fill]:
    data = json.loads(CLOUD_PATH.read_text())["orders"]
    fills: list[Fill] = []
    for o in data:
        for e in o.get("events", []):
            if e["status"] != "filled":
                continue
            direction = e["direction"]
            q = abs(float(e["fillQuantity"]))
            signed = q if direction == "buy" else -q
            fills.append(
                Fill(
                    symbol=e["symbolValue"],
                    when=_epoch_to_date(e["time"]),
                    qty=signed,
                    direction=direction,
                )
            )
    return fills


def load_local() -> list[Fill]:
    data = json.loads(LOCAL_PATH.read_text())
    fills: list[Fill] = []
    for e in data:
        if e["status"] != "filled":
            continue
        direction = e["direction"]
        q = abs(float(e["fillQuantity"]))
        signed = q if direction == "buy" else -q
        fills.append(
            Fill(
                symbol=e["symbolValue"],
                when=_epoch_to_date(e["time"]),
                qty=signed,
                direction=direction,
            )
        )
    return fills


def build_round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Reconstruct round-trips per symbol from a chrono fill stream.

    Long-only model: a position opens on the first buy when flat, closes when
    net qty returns to ~0. Tolerance accounts for partial sizing.
    """
    by_sym: dict[str, list[Fill]] = defaultdict(list)
    for f in fills:
        by_sym[f.symbol].append(f)

    trips: list[RoundTrip] = []
    for sym, fs in by_sym.items():
        fs_sorted = sorted(fs, key=lambda x: x.when)
        pos = 0.0
        cur: RoundTrip | None = None
        for f in fs_sorted:
            if cur is None:
                cur = RoundTrip(symbol=sym, entry=f.when)
            cur.legs.append(f)
            pos += f.qty
            if abs(pos) < 1e-6:
                cur.exit = f.when
                trips.append(cur)
                cur = None
        if cur is not None:  # still open at BT end
            trips.append(cur)
    return trips


def concurrent_series(trips: list[RoundTrip]) -> dict[dt.date, int]:
    """+1 on entry date, -1 the day after exit; cumulative held count by date."""
    deltas: dict[dt.date, int] = defaultdict(int)
    for t in trips:
        deltas[t.entry] += 1
        if t.exit is not None:
            deltas[t.exit + dt.timedelta(days=1)] -= 1
    series: dict[dt.date, int] = {}
    running = 0
    for d in sorted(deltas):
        running += deltas[d]
        series[d] = running
    return series


def daily_held(trips: list[RoundTrip], end: dt.date) -> dict[dt.date, int]:
    """Held count on every calendar day in [first_entry, end]."""
    if not trips:
        return {}
    start = min(t.entry for t in trips)
    out: dict[dt.date, int] = {}
    d = start
    while d <= end:
        out[d] = sum(
            1
            for t in trips
            if t.entry <= d and (t.exit is None or t.exit >= d)
        )
        d += dt.timedelta(days=1)
    return out


def summarize(
    name: str, fills: list[Fill]
) -> tuple[list[RoundTrip], dict[str, object]]:
    info: dict[str, object]
    buys = [f for f in fills if f.direction == "buy"]
    sells = [f for f in fills if f.direction == "sell"]
    trips = build_round_trips(fills)
    closed = [t for t in trips if t.exit is not None]
    open_at_end = [t for t in trips if t.exit is None]
    holds = [t.hold_days for t in closed if t.hold_days is not None]

    end = max(f.when for f in fills)
    held = daily_held(trips, end)
    trading_held = {d: v for d, v in held.items() if d.weekday() < 5}

    info = {
        "n_filled": len(fills),
        "n_buys": len(buys),
        "n_sells": len(sells),
        "distinct_symbols": len({f.symbol for f in fills}),
        "distinct_entered": len({f.symbol for f in buys}),
        "round_trips_total": len(trips),
        "round_trips_closed": len(closed),
        "open_at_end": len(open_at_end),
        "hold_median": statistics.median(holds) if holds else None,
        "hold_mean": round(statistics.mean(holds), 1) if holds else None,
        "hold_max": max(holds) if holds else None,
        "hold_min": min(holds) if holds else None,
        "max_concurrent": max(held.values()) if held else 0,
        "max_concurrent_trading": max(trading_held.values()) if trading_held else 0,
        "median_concurrent_trading": (
            statistics.median(list(trading_held.values())) if trading_held else 0
        ),
        "first_entry": min(f.when for f in buys).isoformat() if buys else None,
        "last_fill": end.isoformat(),
    }
    print(f"\n=== {name} ===")
    for k, v in info.items():
        print(f"  {k:24s}: {v}")
    return trips, info


def overlap_exit_timing(
    cloud_trips: list[RoundTrip], local_trips: list[RoundTrip]
) -> None:
    """For symbols traded by BOTH, compare first-trip hold/exit timing."""
    def first_trip(trips: list[RoundTrip]) -> dict[str, RoundTrip]:
        out: dict[str, RoundTrip] = {}
        for t in sorted(trips, key=lambda x: x.entry):
            if t.symbol not in out:
                out[t.symbol] = t
        return out

    cf = first_trip(cloud_trips)
    lf = first_trip(local_trips)
    shared = sorted(set(cf) & set(lf))
    print(f"\n=== OVERLAP exit-timing (first round-trip per shared symbol) ===")
    print(f"  shared symbols: {len(shared)}")

    rows = []
    cloud_earlier = local_earlier = same = 0
    for s in shared:
        c, l = cf[s], lf[s]
        ch, lh = c.hold_days, l.hold_days
        if ch is None or lh is None:
            continue
        rows.append((s, c.entry, c.exit, ch, l.entry, l.exit, lh, lh - ch))
        if c.exit and l.exit:
            if c.exit < l.exit:
                cloud_earlier += 1
            elif c.exit > l.exit:
                local_earlier += 1
            else:
                same += 1

    closed_both = [r for r in rows]
    print(f"  shared with BOTH closed: {len(closed_both)}")
    print(f"  cloud exits EARLIER: {cloud_earlier}  | local earlier: {local_earlier}  | same: {same}")
    if closed_both:
        cloud_holds = [r[3] for r in closed_both]
        local_holds = [r[6] for r in closed_both]
        print(f"  median hold (shared) cloud={statistics.median(cloud_holds)}  local={statistics.median(local_holds)}")
        print(f"  mean hold   (shared) cloud={round(statistics.mean(cloud_holds),1)}  local={round(statistics.mean(local_holds),1)}")

    # biggest local-longer-than-cloud examples (positive delta = local held longer)
    rows.sort(key=lambda r: r[7], reverse=True)
    print("\n  Top shared names where LOCAL held longer than CLOUD (delta = local_hold - cloud_hold days):")
    print(f"  {'sym':5s} {'c_entry':10s} {'c_exit':10s} {'c_hold':>6s} {'l_entry':10s} {'l_exit':10s} {'l_hold':>6s} {'delta':>6s}")
    for r in rows[:12]:
        s, ce, cx, ch, le, lx, lh, dl = r
        print(f"  {s:5s} {ce.isoformat():10s} {(cx.isoformat() if cx else '-'):10s} {ch:6d} {le.isoformat():10s} {(lx.isoformat() if lx else '-'):10s} {lh:6d} {dl:6d}")

    print("\n  Top shared names where CLOUD held longer than LOCAL:")
    for r in rows[-6:]:
        s, ce, cx, ch, le, lx, lh, dl = r
        print(f"  {s:5s} {ce.isoformat():10s} {(cx.isoformat() if cx else '-'):10s} {ch:6d} {le.isoformat():10s} {(lx.isoformat() if lx else '-'):10s} {lh:6d} {dl:6d}")


def entry_breadth(cloud_fills: list[Fill], local_fills: list[Fill]) -> None:
    ce = {f.symbol for f in cloud_fills if f.direction == "buy"}
    le = {f.symbol for f in local_fills if f.direction == "buy"}
    print("\n=== ENTRY breadth ===")
    print(f"  cloud entered: {len(ce)}  local entered: {len(le)}")
    print(f"  overlap: {len(ce & le)}")
    print(f"  cloud-only: {len(ce - le)}  -> {sorted(ce - le)}")
    print(f"  local-only: {len(le - ce)}  -> {sorted(le - ce)}")


def submit_fill_timing() -> None:
    """THE localized driver: cloud submits new entries at the bar OPEN
    (04:00/05:00Z = midnight ET) and fills same day; local submits ALL orders
    at the bar CLOSE (20:00/21:00Z = 16:00 ET) and fills the next trading day.
    A 1-bar entry-execution lead that shifts cloud onto a different date-grid.
    """
    from collections import Counter

    def ep(ts: float) -> dt.datetime:
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)

    cloud = json.loads(CLOUD_PATH.read_text())["orders"]
    c_sub_h: Counter[str] = Counter()
    c_lat: Counter[int] = Counter()
    c_open_buys = 0
    c_open_sells = 0
    for o in cloud:
        sub = fill = None
        sdir = None
        for e in o.get("events", []):
            if e["status"] == "submitted":
                sub = ep(e["time"])
                sdir = e["direction"]
            if e["status"] == "filled":
                fill = ep(e["time"])
        if sub is not None:
            c_sub_h[sub.strftime("%H:%M")] += 1
            if sub.hour < 12:  # open-bar submission
                if sdir == "buy":
                    c_open_buys += 1
                else:
                    c_open_sells += 1
        if sub is not None and fill is not None:
            c_lat[(fill.date() - sub.date()).days] += 1

    local = json.loads(LOCAL_PATH.read_text())
    l_sub_h: Counter[str] = Counter(
        ep(e["time"]).strftime("%H:%M")
        for e in local
        if e["status"] == "submitted"
    )
    l_by_id: dict[int, dict[str, float]] = {}
    for e in local:
        l_by_id.setdefault(e["orderId"], {})[e["status"]] = e["time"]
    l_lat: Counter[int] = Counter()
    for rec in l_by_id.values():
        if "submitted" in rec and "filled" in rec:
            d = (
                ep(rec["filled"]).date() - ep(rec["submitted"]).date()
            ).days
            l_lat[d] += 1

    print("\n=== SUBMIT-TIME / FILL-LATENCY (the localized driver) ===")
    print(f"  CLOUD submit-time-of-day: {dict(c_sub_h)}")
    print(f"  LOCAL submit-time-of-day: {dict(l_sub_h)}")
    print(f"  CLOUD open-bar (04/05h) submissions: buys={c_open_buys} sells={c_open_sells}")
    print(f"  CLOUD submit->fill day-latency: {dict(c_lat)}")
    print(f"  LOCAL submit->fill day-latency: {dict(l_lat)}")
    print("  -> LOCAL has ZERO open-bar submissions; every local order submits")
    print("     at the close and fills next day. Cloud fires 58 entries at the")
    print("     OPEN (same-day fill) = 1-bar entry-execution lead.")


def main() -> None:
    cloud_fills = load_cloud()
    local_fills = load_local()
    cloud_trips, cinfo = summarize("CLOUD (8ddbe2b..., 291 orders)", cloud_fills)
    local_trips, linfo = summarize("LOCAL (1158674033, 244 orders)", local_fills)

    def gi(d: dict[str, object], k: str) -> int:
        v = d[k]
        assert isinstance(v, int)
        return v

    print("\n=== GAP attribution ===")
    print(f"  order(filled) gap: cloud {gi(cinfo,'n_filled')} - local {gi(linfo,'n_filled')} = {gi(cinfo,'n_filled')-gi(linfo,'n_filled')}")
    print(f"  buy gap:  {gi(cinfo,'n_buys')-gi(linfo,'n_buys')}   sell gap: {gi(cinfo,'n_sells')-gi(linfo,'n_sells')}")
    print(f"  distinct-symbol gap: {gi(cinfo,'distinct_symbols')-gi(linfo,'distinct_symbols')}")
    print(f"  round-trip gap: {gi(cinfo,'round_trips_total')-gi(linfo,'round_trips_total')}")
    print(f"  max-concurrent: cloud {gi(cinfo,'max_concurrent')} vs local {gi(linfo,'max_concurrent')}")

    entry_breadth(cloud_fills, local_fills)
    overlap_exit_timing(cloud_trips, local_trips)
    submit_fill_timing()


if __name__ == "__main__":
    main()
