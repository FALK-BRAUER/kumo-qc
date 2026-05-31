#!/usr/bin/env python3
"""#265 residual parity diff — new-local vs new-cloud full-FY2025 (post-#259 warmup fix).

#173 protocol, applied to the RESIDUAL that remains after the warmup mirage is closed.
Both sides now warm (local ACTIVE_SET 614-900 in warmup; cloud always warm). The remaining
divergence (local trades ~93 symbols, cloud ~118) is localized here to ONE of three layers:

  SELECTION (vendor-breadth) — the cloud-only gap name is ABSENT from local's conform-coarse
      on every day it could have entered. Local literally never saw it → IRREDUCIBLE vendor
      difference (local conform-coarse != QC-native coarse breadth).
  SELECTION (floors)         — the name IS in local's coarse but never passes the floors
      (close>=10 AND trailing-20d-mean-DV>=100M) on a candidate day → a metric/floor delta.
  SIGNAL/SIZING              — the name passes floors locally (made _ranked_today) on a day
      cloud traded it, but local never scored it >=7 / never sized it → signal or sizing
      divergence (NOT a data-breadth gap).

It does NOT call the cloud API; cloud orders come from a saved JSON (orders/read dump). Local
comes from the BT order-events.json + the on-disk conform-coarse (replayed through the IDENTICAL
selection-gate code: update_dv_windows -> apply_floors -> rank_and_cap).

Usage:
  python3 scripts/residual_parity_diff.py \
      --local-bt algorithm/v2_champion_asis/backtests/<ts> \
      --cloud-orders /tmp/cloud_orders_265.json \
      [--out research/parity/residual-data-2025.json]

FAIL-LOUD: aborts (exit 2) if any artifact is missing/empty — never silently proceeds on a
partial set (Falk's data-integrity mandate).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from runtime.universe_select import (  # noqa: E402
    DvWindow,
    apply_floors,
    rank_and_cap,
    rolling_dv_mean,
)

# Selection-gate constants — MUST match dist/lean_entry.BctEngineAlgorithm (pinned here; the
# test test_residual_diff_constants_pinned asserts they still match the live code).
PREFILTER_DV = 25_000_000.0
MIN_PRICE = 10.0
MIN_AVG_DOLLAR_VOLUME = 100_000_000.0
COARSE_MAX = 9999
ADV_WINDOW = 20

_COARSE_DIR = _ROOT / "data" / "equity" / "usa" / "fundamental" / "coarse"
# The warmup span start (matches conform_coarse._WARMUP_START); the rolling-DV window must be
# warmed over the SAME warmup the BT used, so the trailing means match the live run.
_WARMUP_START = "20230620"
_FY_START = "20250101"
_FY_END = "20251231"


def _die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(2)


# ── local: traded symbols from order-events.json ──────────────────────────────


def local_traded_symbols(bt_dir: Path) -> tuple[set[str], dict[str, str]]:
    """Return (uppercase traded tickers, {ticker -> first BUY date 'YYYY-MM-DD'}) from the
    local BT order-events.json. A 'traded' symbol = one with at least one FILLED event."""
    evs = sorted(bt_dir.glob("*-order-events.json"))
    if not evs:
        _die(f"no *-order-events.json in {bt_dir}")
    data = json.loads(evs[0].read_text())
    if not data:
        _die(f"order-events.json empty in {bt_dir} — 0 trades (mirage guard)")
    import datetime as dt

    traded: set[str] = set()
    first_buy: dict[str, str] = {}
    for e in data:
        if e.get("status") != "filled":
            continue
        sym = str(e.get("symbolValue", "")).upper()
        if not sym:
            continue
        traded.add(sym)
        if e.get("direction") == "buy":
            t = e.get("time")
            day = dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%Y-%m-%d") if t else ""
            if day and (sym not in first_buy or day < first_buy[sym]):
                first_buy[sym] = day
    if not traded:
        _die(f"0 FILLED symbols in {bt_dir} — local produced no trades (mirage guard)")
    return traded, first_buy


# ── cloud: traded symbols from saved orders dump ──────────────────────────────


def cloud_traded_symbols(orders_json: Path) -> tuple[set[str], dict[str, str]]:
    """Return (uppercase traded tickers, {ticker -> first BUY date}) from a saved QC
    /backtests/orders/read dump (the `orders` list)."""
    raw = json.loads(orders_json.read_text())
    orders = raw.get("orders", raw) if isinstance(raw, dict) else raw
    if not orders:
        _die(f"cloud orders empty in {orders_json}")
    import datetime as dt

    traded: set[str] = set()
    first_buy: dict[str, str] = {}
    for o in orders:
        sym_obj = o.get("symbol", {})
        sym = str(sym_obj.get("value") if isinstance(sym_obj, dict) else o.get("symbolValue", "")).upper()
        if not sym:
            continue
        # status 3 == Filled in QC; also accept string 'filled'
        st = o.get("status")
        filled = st in (3, "filled", "Filled") or (o.get("quantity") and st not in (5, "canceled"))
        if not filled:
            continue
        traded.add(sym)
        qty = o.get("quantity", 0)
        if qty and float(qty) > 0:
            t = o.get("time")
            day = ""
            if isinstance(t, (int, float)):
                day = dt.datetime.fromtimestamp(float(t), dt.timezone.utc).strftime("%Y-%m-%d")
            elif isinstance(t, str):
                day = t[:10]
            if day and (sym not in first_buy or day < first_buy[sym]):
                first_buy[sym] = day
    if not traded:
        _die(f"0 traded symbols parsed from cloud orders {orders_json}")
    return traded, first_buy


# ── local selection-gate replay (offline reconstruction) ──────────────────────


def _session_days() -> list[str]:
    days = sorted(p.stem for p in _COARSE_DIR.glob("*.csv") if p.stem.isdigit())
    return [d for d in days if d >= _WARMUP_START]


def _parse_coarse(ymd: str) -> dict[str, tuple[float, float]]:
    """{ticker_lower -> (close, single_day_dv)} from one 8-col headerless QC-native coarse file.
    cols: SID,ticker,close,vol,dollarVol,hasFund,priceFactor,split"""
    fp = _COARSE_DIR / f"{ymd}.csv"
    if not fp.is_file():
        return {}
    out: dict[str, tuple[float, float]] = {}
    for ln in fp.read_text().strip().split("\n"):
        if not ln or ln.startswith("Symbol,Price"):  # skip any stale header
            continue
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        try:
            out[parts[1].lower()] = (float(parts[2]), float(parts[4]))
        except (ValueError, IndexError):
            continue
    return out


def replay_ranked_universe() -> dict[str, set[str]]:
    """Replay the IDENTICAL selection gate (update_dv_windows -> apply_floors -> rank_and_cap)
    over the full warmup+FY span. Returns {FY-day 'YYYY-MM-DD' -> set(uppercase ranked tickers)}
    for the LIVE FY2025 days only (warmup days only warm the rolling-DV windows)."""
    windows: dict[str, DvWindow] = {}
    day_index = 0
    out: dict[str, set[str]] = {}
    for ymd in _session_days():
        coarse = _parse_coarse(ymd)
        if not coarse:
            continue
        day_index += 1
        coarse_dv = {t: dv for t, (_, dv) in coarse.items()}
        # update_dv_windows (in place)
        for ticker, sdv in coarse_dv.items():
            w = windows.get(ticker)
            if w is None:
                w = DvWindow(dv=deque(maxlen=ADV_WINDOW))
                windows[ticker] = w
            w.dv.append(float(sdv))
            w.last_seen = day_index
        stale = [t for t, w in windows.items() if day_index - w.last_seen >= ADV_WINDOW]
        for t in stale:
            del windows[t]
        # prefilter -> bar_metrics -> floors -> rank
        bar_metrics: dict[str, tuple[float, float]] = {}
        for ticker, (close, sdv) in coarse.items():
            if sdv < PREFILTER_DV:
                continue
            bar_metrics[ticker] = (close, rolling_dv_mean(windows[ticker].dv))
        eligible = apply_floors(
            bar_metrics, min_price=MIN_PRICE, min_avg_dollar_volume=MIN_AVG_DOLLAR_VOLUME,
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=COARSE_MAX)
        if _FY_START <= ymd <= _FY_END:
            day = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            out[day] = {t.upper() for t in ranked}
    if not out:
        _die("replay produced no FY2025 ranked days — coarse data missing?")
    return out


def coarse_universe_union(ranked_by_day: dict[str, set[str]]) -> set[str]:
    u: set[str] = set()
    for s in ranked_by_day.values():
        u |= s
    return u


# ── classify the cloud-only gap names ─────────────────────────────────────────


def classify_gap(
    cloud_only: set[str],
    cloud_first_buy: dict[str, str],
    ranked_by_day: dict[str, set[str]],
    local_coarse_union: set[str],
) -> dict[str, dict[str, object]]:
    """For each cloud-only symbol, classify the layer of divergence."""
    # also build the per-day raw coarse presence (regardless of floors) over FY
    fy_days = sorted(ranked_by_day)
    result: dict[str, dict[str, object]] = {}
    for sym in sorted(cloud_only):
        low = sym.lower()
        in_coarse = sym in local_coarse_union or low in local_coarse_union
        # did it ever pass floors (appear in any FY ranked day)?
        passed_floors_days = [d for d in fy_days if sym in ranked_by_day[d]]
        # presence in raw coarse near the cloud buy day
        buy_day = cloud_first_buy.get(sym, "")
        passed_on_buyday = bool(buy_day) and any(
            sym in ranked_by_day.get(d, set()) for d in fy_days if d >= buy_day[:7]  # same/after buy month
        )
        if passed_floors_days:
            layer = "SIGNAL_OR_SIZING"  # in ranked universe but not traded locally
        elif _raw_coarse_presence(sym):
            layer = "SELECTION_FLOORS"  # in coarse but never cleared floors
        else:
            layer = "SELECTION_VENDOR_BREADTH"  # never in local coarse at all
        result[sym] = {
            "layer": layer,
            "cloud_first_buy": buy_day,
            "in_local_ranked_any_day": bool(passed_floors_days),
            "n_ranked_days": len(passed_floors_days),
            "passed_floors_on_or_after_buymonth": passed_on_buyday,
        }
    return result


_RAW_PRESENCE_CACHE: dict[str, bool] = {}


def _raw_coarse_presence(sym: str) -> bool:
    """Did the ticker appear in ANY FY2025 raw coarse file (regardless of floors)?"""
    if not _RAW_PRESENCE_CACHE:
        union: set[str] = set()
        for ymd in _session_days():
            if not (_FY_START <= ymd <= _FY_END):
                continue
            for t in _parse_coarse(ymd):
                union.add(t.upper())
        _RAW_PRESENCE_CACHE["__union__"] = bool(union)  # marker
        for t in union:
            _RAW_PRESENCE_CACHE[t] = True
    return _RAW_PRESENCE_CACHE.get(sym.upper(), False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-bt", required=True, type=Path)
    ap.add_argument("--cloud-orders", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if not args.local_bt.is_dir():
        _die(f"--local-bt not a dir: {args.local_bt}")
    if not args.cloud_orders.is_file():
        _die(f"--cloud-orders not found: {args.cloud_orders}")
    if not _COARSE_DIR.is_dir():
        _die(f"coarse dir absent: {_COARSE_DIR}")

    local_syms, local_first = local_traded_symbols(args.local_bt)
    cloud_syms, cloud_first = cloud_traded_symbols(args.cloud_orders)

    print("=== replaying local selection gate over warmup+FY (offline) ===")
    ranked_by_day = replay_ranked_universe()
    coarse_union = coarse_universe_union(ranked_by_day)

    overlap = local_syms & cloud_syms
    cloud_only = cloud_syms - local_syms
    local_only = local_syms - cloud_syms

    gap = classify_gap(cloud_only, cloud_first, ranked_by_day, coarse_union)
    layers: dict[str, int] = {}
    for v in gap.values():
        layer = str(v["layer"])
        layers[layer] = layers.get(layer, 0) + 1

    summary = {
        "local_traded_count": len(local_syms),
        "cloud_traded_count": len(cloud_syms),
        "overlap": len(overlap),
        "cloud_only": len(cloud_only),
        "local_only": len(local_only),
        "cloud_only_by_layer": layers,
        "local_ranked_universe_union_size": len(coarse_union),
        "fy_ranked_days": len(ranked_by_day),
    }
    out = {
        "summary": summary,
        "overlap_symbols": sorted(overlap),
        "cloud_only_symbols": sorted(cloud_only),
        "local_only_symbols": sorted(local_only),
        "gap_classification": gap,
    }
    print(json.dumps(summary, indent=2))
    print("\n=== cloud-only gap by layer ===")
    for layer in ("SELECTION_VENDOR_BREADTH", "SELECTION_FLOORS", "SIGNAL_OR_SIZING"):
        names = sorted(s for s, v in gap.items() if str(v["layer"]) == layer)
        print(f"  {layer}: {len(names)}  e.g. {names[:12]}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
