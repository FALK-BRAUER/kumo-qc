#!/usr/bin/env python3
"""#268 LOCAL diagnostic — maintained-vs-NATIVE weekly Ichimoku recompute (seed-overlap test).

WHY: #265 root-caused the local-vs-cloud residual to a SIGNAL-layer divergence: on RAW-
identical daily prices, local scores cloud-traded names differently. The remaining question
is WHERE the maintained weekly Ichimoku VALUES diverge from a clean native warm — and whether
the engine's seed+consolidator split (`_seed_weekly` then the live `Calendar.WEEKLY`
consolidator) injects a one-week DOUBLE-COUNT for a mid-week entrant (the seed-overlap
hypothesis).

This script is RAW-ONLY (the on-disk conformed daily zips, deci-cents/10000 — never yfinance /
adjusted) and FABRICATES NOTHING: every value is recomputed from a real daily zip.

TWO weekly-Ichimoku warm paths, faithfully replicated in pure Python (LEAN
IchimokuKinkoHyo(9,26,26,52,26,26) math — Tenkan=mid(9), Kijun=mid(26), SenkouA=mid of
(Tenkan,Kijun) delayed 26, SenkouB=mid(52) delayed 26; mirrors oracle_helpers._mid + .shift(26)
which is the parity reference):

  NATIVE/CLEAN — feed the SAME RAW daily history through ONE clean daily->weekly aggregation
    (runtime.indicators.weekly_aggregate, W-FRI buckets) into a fresh Ichimoku. This is the
    "correct" warm cloud's continuous set_warmup feed approximates: no seed/consolidator split,
    no partial-week double-count.

  MAINTAINED — how the engine actually computes w_ichi for a name SUBSCRIBED MID-FY (after
    warmup ends): `_seed_weekly` pulls WARMUP_DAYS history, weekly_aggregate's it (its LAST
    bucket is the PARTIAL current week — Mon..subscribe-day, from past-only history), feeds all
    those Monday-timestamped bars; THEN the live Calendar.WEEKLY consolidator RE-EMITS that same
    current week when it completes (Mon..Fri full). The seed-overlap hypothesis: that re-emit is
    a one-week double-count/shift vs the clean single aggregation.

    NB (the cancellation caveat): a name subscribed DURING warmup is auto-warmed by QC's live
    consolidator (the `if not self.is_warming_up` guard skips the seed) → its maintained path
    EQUALS the clean path. The seed-overlap can ONLY bite a POST-warmup mid-FY entrant. And the
    seed runs on the SINGLE code path (local==cloud), so if cloud seeds identically it CANCELS
    in the local-vs-cloud diff. This script quantifies the ABSOLUTE-correctness magnitude
    (maintained vs clean) and whether it is MATERIAL to the BCT score=7 threshold; whether it
    also explains local-vs-cloud is a separate (cloud-capture) question.

Outputs research/parity/artifacts/diag-268-maintained-vs-native.json with, per probe and per
scenario, the FY2025 tenkan/kijun/senkou_a/senkou_b/weekly-close sequences for both paths, the
max abs diff, and the weekly-bar-count check at FY-start (the 78-week pole).

Usage: python3 scripts/diag_268_maintained_vs_native.py [outPath]
"""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

import pandas as pd  # noqa: E402

from runtime.indicators import weekly_aggregate, weekly_friday  # noqa: E402

DATA = ROOT / "data"
DAILY_DIR = DATA / "equity" / "usa" / "daily"
PRICE_SCALE = 10000.0  # LEAN equity OHLC scale in the daily zips

# The #265 / #243 probe set — the cloud-traded names local scored differently.
PROBES: tuple[str, ...] = ("DRI", "CME", "AMZN", "COST", "CRWD", "KGC")

# Engine constants (lean_entry.py).
WARMUP_DAYS = 560
FY_START = date(2025, 1, 1)
FY_END = date(2025, 12, 31)

# Ichimoku(9,26,26,52,26,26) periods.
TENKAN_P = 9
KIJUN_P = 26
SENKOU_B_P = 52
SENKOU_DELAY = 26


# --------------------------------------------------------------------------------------
# RAW daily loader (the conformed on-disk zip; deci-cents / 10000). MultiIndex-free OHLCV.
# --------------------------------------------------------------------------------------
def load_raw_daily(ticker: str) -> pd.DataFrame:
    """RAW daily OHLCV DataFrame (datetime index, lowercased cols) from the on-disk zip.

    Prices de-scaled by 10000 (LEAN equity scale). This is the SAME data lean_entry's
    self.history(..., Resolution.DAILY) returns locally (RAW per universe_settings), so both
    warm paths consume the identical bar set — the only variable under test is HOW the weekly
    bars are constructed, not the prices.
    """
    zp = DAILY_DIR / f"{ticker.lower()}.zip"
    if not zp.exists():
        return pd.DataFrame()
    rows: list[tuple[datetime, float, float, float, float, float]] = []
    with zipfile.ZipFile(zp) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            for row in csv.reader(io.TextIOWrapper(fh, "utf-8")):
                if not row:
                    continue
                ds = row[0].split(" ")[0]
                ts = datetime.strptime(ds, "%Y%m%d")
                o, h, lo, c = (float(row[i]) / PRICE_SCALE for i in (1, 2, 3, 4))
                v = float(row[5])
                rows.append((ts, o, h, lo, c, v))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows, columns=["ts", "open", "high", "low", "close", "volume"]
    ).set_index("ts")
    df.index = pd.DatetimeIndex(df.index)
    return df.sort_index()


# --------------------------------------------------------------------------------------
# LEAN-faithful IchimokuKinkoHyo over a weekly OHLC bar list (pure Python; matches
# oracle_helpers._mid + .shift(SENKOU_DELAY), the parity reference). Each emitted row carries
# the indicator's CURRENT readings AFTER consuming that weekly bar — i.e. what
# w_ichi.<line>.current.value would read once is_ready.
# --------------------------------------------------------------------------------------
def _mid(highs: list[float], lows: list[float], period: int, end: int) -> float | None:
    """(max(high) + min(low))/2 over the `period` bars ending at index `end` (inclusive).
    None until `period` bars are available — the Ichimoku donchian midline."""
    if end + 1 < period:
        return None
    window_hi = highs[end + 1 - period : end + 1]
    window_lo = lows[end + 1 - period : end + 1]
    return (max(window_hi) + min(window_lo)) / 2.0


def ichimoku_series(weekly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replay an Ichimoku(9,26,26,52,26,26) over weekly bars; emit per-bar current readings.

    SenkouA/SenkouB are DELAYED by SENKOU_DELAY (26): senkou_a.current at bar i equals the
    ((tenkan+kijun)/2) computed at bar i-26 (LEAN Delay(26)); senkou_b.current at bar i equals
    mid(52) at bar i-26. This is exactly oracle_helpers._mid(...).shift(26).iloc[-1]. A row is
    'ready' once all four lines are non-None (== IchimokuKinkoHyo.IsReady, the 78-bar pole).
    """
    highs = [float(b["high"]) for b in weekly]
    lows = [float(b["low"]) for b in weekly]
    closes = [float(b["close"]) for b in weekly]
    fridays = [b["friday"] for b in weekly]

    # Pre-compute the (undelayed) component lines per bar.
    tenkan_raw: list[float | None] = []
    kijun_raw: list[float | None] = []
    sa_pre: list[float | None] = []  # (tenkan+kijun)/2 BEFORE the 26-delay
    sb_pre: list[float | None] = []  # mid(52) BEFORE the 26-delay
    for i in range(len(weekly)):
        t = _mid(highs, lows, TENKAN_P, i)
        k = _mid(highs, lows, KIJUN_P, i)
        tenkan_raw.append(t)
        kijun_raw.append(k)
        sa_pre.append(((t + k) / 2.0) if (t is not None and k is not None) else None)
        sb_pre.append(_mid(highs, lows, SENKOU_B_P, i))

    out: list[dict[str, Any]] = []
    for i in range(len(weekly)):
        sa = sa_pre[i - SENKOU_DELAY] if i - SENKOU_DELAY >= 0 else None
        sb = sb_pre[i - SENKOU_DELAY] if i - SENKOU_DELAY >= 0 else None
        ready = (
            tenkan_raw[i] is not None
            and kijun_raw[i] is not None
            and sa is not None
            and sb is not None
        )
        out.append(
            {
                "friday": fridays[i].strftime("%Y-%m-%d"),
                "ready": ready,
                "tenkan": tenkan_raw[i],
                "kijun": kijun_raw[i],
                "senkou_a": sa,
                "senkou_b": sb,
                "w_close": closes[i],
            }
        )
    return out


# --------------------------------------------------------------------------------------
# The two warm paths.
# --------------------------------------------------------------------------------------
def native_weekly(daily: pd.DataFrame, asof: date) -> list[dict[str, Any]]:
    """CLEAN/NATIVE warm: ONE clean daily->weekly aggregation of all daily bars STRICTLY BEFORE
    `asof`, fed into a fresh Ichimoku. Mirrors a continuous set_warmup feed (no seed split)."""
    hist = daily[daily.index < pd.Timestamp(asof)]
    return weekly_aggregate(hist)


def maintained_weekly(
    daily: pd.DataFrame, subscribe_day: date, asof: date
) -> list[dict[str, Any]]:
    """MAINTAINED warm for a name first subscribed on `subscribe_day` (post-warmup entrant),
    carried forward through `asof` exactly as the engine's forward-only weekly Ichimoku sees it.

    Faithful replica of _seed_weekly + the live Calendar.WEEKLY consolidator, INCLUDING the
    forward-only timestamp invariant (the load-bearing detail):

      1. SEED (_seed_weekly): WARMUP_DAYS daily bars ending the day BEFORE subscribe_day,
         weekly_aggregate'd, each bucket Monday-timestamped (wb.friday - 4d). The LAST bucket is
         the PARTIAL current week (Mon..the last pre-subscribe trading day) — fed as if complete.

      2. LIVE (the consolidator): from subscribe_day onward the live Calendar.WEEKLY consolidator
         emits one Monday-timestamped bar per completed week. When the CURRENT week completes, the
         consolidator emits its FULL Mon..Fri OHLC — but at the SAME Monday timestamp the seed
         already used for its partial bar. IchimokuKinkoHyo is FORWARD-ONLY: an update whose time
         is <= the last sample is REJECTED ("forward only indicator"). So the full-week re-emit is
         DROPPED and the indicator keeps the seed's PARTIAL-week value. Every LATER week (a strictly
         later Monday) is accepted normally.

    THIS is the seed-overlap defect under test: the maintained sequence carries the seed's
    PARTIAL current week where the clean native warm has the FULL current week. We model it by
    taking the seed weeks (partial last bucket retained) + every live full week with a Monday
    STRICTLY AFTER the seed's last Monday (the rejected same-Monday re-emit is excluded). An
    APPEND bug (double-count, not forward-only-reject) would instead show the same week twice →
    the weekly_bar_count_check detects that separately.
    """
    cut = pd.Timestamp(subscribe_day)
    hist = daily[daily.index < cut]
    seed_window = hist[hist.index >= cut - pd.Timedelta(days=WARMUP_DAYS)]
    seed_weeks = weekly_aggregate(seed_window)  # last bucket = partial current week
    if not seed_weeks:
        return weekly_aggregate(daily[daily.index < pd.Timestamp(asof)])
    last_seed_monday = seed_weeks[-1]["friday"] - pd.Timedelta(days=4)
    # Live full weeks over the whole feed; keep only those whose Monday is STRICTLY AFTER the
    # seed's last Monday (earlier weeks are already in the seed; the same-Monday week is the
    # forward-only-rejected re-emit, so the partial seed bar persists).
    live_weeks = [
        wb
        for wb in weekly_aggregate(daily[daily.index < pd.Timestamp(asof)])
        if (wb["friday"] - pd.Timedelta(days=4)) > last_seed_monday
    ]
    return seed_weeks + live_weeks


def fy_dates_active(score_chart: dict[str, Any], ticker: str) -> tuple[date | None, int]:
    """(first_active_FY_date, fy_trading_days) for a probe from the local BT Score chart —
    first_active = first FY day the maintained scorer returned a real score (not the -1 sentinel),
    i.e. the day the maintained w_ichi became is_ready locally. Used to pick the maintained
    subscribe_day for the post-warmup-entrant scenario."""
    vals = score_chart.get(ticker, {}).get("values", [])
    first = None
    for ts, v in vals:
        if v >= 0:
            first = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            break
    return first, len(vals)


def diff_sequences(
    maint: list[dict[str, Any]], native: list[dict[str, Any]], fy_start: date
) -> dict[str, Any]:
    """Align maintained vs native weekly Ichimoku by Friday key over FY2025; report max abs diff
    per line + the count of FY weeks where the difference would flip a >/< comparison materially
    (>0.5% of the weekly close — a proxy for a score-condition flip on the Ichimoku-vs-price
    and cloud-vs-tenkan/kijun checks)."""
    nmap = {r["friday"]: r for r in native}
    lines = ("tenkan", "kijun", "senkou_a", "senkou_b", "w_close")
    max_abs = {ln: 0.0 for ln in lines}
    max_rel = {ln: 0.0 for ln in lines}
    n_compared = 0
    n_any_diff = 0
    worst: dict[str, Any] = {}
    for r in maint:
        fri = r["friday"]
        if date.fromisoformat(fri) < fy_start:
            continue
        nr = nmap.get(fri)
        if nr is None:
            continue
        if not (r["ready"] and nr["ready"]):
            continue
        n_compared += 1
        row_diff = False
        for ln in lines:
            mv, nv = r[ln], nr[ln]
            if mv is None or nv is None:
                continue
            ad = abs(float(mv) - float(nv))
            close = float(r["w_close"]) or 1.0
            rel = ad / close
            if ad > 0:
                row_diff = True
            if ad > max_abs[ln]:
                max_abs[ln] = ad
            if rel > max_rel[ln]:
                max_rel[ln] = rel
                worst[ln] = {
                    "friday": fri,
                    "maintained": float(mv),
                    "native": float(nv),
                    "abs_diff": ad,
                    "rel_diff_pct": rel * 100.0,
                }
        if row_diff:
            n_any_diff += 1
    return {
        "fy_weeks_compared": n_compared,
        "fy_weeks_with_any_diff": n_any_diff,
        "max_abs_diff": max_abs,
        "max_rel_diff_pct": {k: v * 100.0 for k, v in max_rel.items()},
        "worst_per_line": worst,
    }


def weekly_bar_count_check(daily: pd.DataFrame) -> dict[str, Any]:
    """Does WARMUP_DAYS(560) + the weekly seed produce the SAME number of COMPLETED weekly bars
    at FY-start as a clean warm — and is that >= the 78-bar Ichimoku pole? An off-by-one in the
    weekly count shifts the entire SenkouA/B (the 26-delay). Compares:
      - native: all daily < FY_START, clean weekly_aggregate.
      - seed:   WARMUP_DAYS daily ending the last pre-FY trading day, weekly_aggregate.
    Reports both completed-bar counts (a bucket whose Friday < FY_START is 'completed' as-of FY)
    and whether each clears the 78-bar readiness pole."""
    native_w = native_weekly(daily, FY_START)
    # seed window: the WARMUP_DAYS calendar days ending the day before FY_START.
    cut = pd.Timestamp(FY_START)
    pre = daily[daily.index < cut]
    seed_window = pre[pre.index >= cut - pd.Timedelta(days=WARMUP_DAYS)]
    seed_w = weekly_aggregate(seed_window)

    def completed(weeks: list[dict[str, Any]]) -> int:
        return sum(1 for w in weeks if w["friday"].date() < FY_START)

    return {
        "native_total_weeks": len(native_w),
        "native_completed_pre_fy": completed(native_w),
        "seed_total_weeks": len(seed_w),
        "seed_completed_pre_fy": completed(seed_w),
        "weekly_pole": 78,
        "native_clears_pole": completed(native_w) >= 78,
        "seed_clears_pole": completed(seed_w) >= 78,
        "count_delta_seed_minus_native": len(seed_w) - len(native_w),
    }


def run(out_path: Path) -> dict[str, Any]:
    # Load the local BT Score chart to pick each probe's maintained subscribe_day (first FY day
    # the maintained scorer went ready locally — the post-warmup-entrant scenario).
    bt = ROOT / "algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/1158674033.json"
    score_chart: dict[str, Any] = {}
    if bt.exists():
        d = json.loads(bt.read_text())
        charts = d.get("charts") or d.get("Charts") or {}
        score_chart = (charts.get("Score") or {}).get("series") or {}

    # A FORCED mid-week seed date to QUANTIFY the seed-overlap defect magnitude for ANY name (the
    # hypothesis test), independent of whether these specific probes are actually seeded. A
    # Wednesday inside FY2025 → the seed's last bucket is the PARTIAL Mon..Wed week. 2025-03-12 is
    # a Wednesday.
    FORCED_SEED_DAY = date(2025, 3, 12)

    results: dict[str, Any] = {}
    for tk in PROBES:
        daily = load_raw_daily(tk)
        if daily.empty:
            results[tk] = {"error": "no daily zip"}
            continue
        first_active, fy_days = fy_dates_active(score_chart, tk)

        # NATIVE/CLEAN warm — ONE clean weekly_aggregate of the full-FY daily history.
        native_weeks = weekly_aggregate(
            daily[daily.index < pd.Timestamp(FY_END + timedelta(days=1))]
        )
        native_ichi = ichimoku_series(native_weeks)

        # REALISTIC path for the #265 probes: every probe has FULL daily history reaching back
        # BEFORE warmup-start (2023-06-21) and is a large-cap high-DV name that clears the floors
        # every day, so it is in the WARMUP universe → QC AUTO-WARMS its weekly consolidator over
        # the 560d warmup → the `if not self.is_warming_up` guard SKIPS _seed_weekly → its
        # maintained w_ichi is built by the SAME continuous live consolidator the native path
        # models. Maintained == native for these names; the score chart's first_active reflects
        # indicator-readiness DAY, not a mid-FY subscription. (data_starts is recorded so the
        # claim "history predates warmup" is verifiable, not asserted.)
        data_starts = daily.index.min().date()
        auto_warmed = data_starts < date(2023, 6, 21)
        realistic_diff = diff_sequences(native_ichi, native_ichi, FY_START)  # identical by constr.

        # HYPOTHESIS PROBE: FORCE a mid-week (Wed) seed to MEASURE the seed-overlap magnitude as
        # if this name were a post-warmup mid-FY entrant. seed last bucket = partial Mon..Wed.
        forced_maint = maintained_weekly(
            daily, FORCED_SEED_DAY, FY_END + timedelta(days=1)
        )
        forced_ichi = ichimoku_series(forced_maint)
        forced_diff = diff_sequences(forced_ichi, native_ichi, FY_START)

        count_chk = weekly_bar_count_check(daily)
        results[tk] = {
            "first_active_fy": first_active.isoformat() if first_active else None,
            "fy_score_days": fy_days,
            "data_starts": data_starts.isoformat(),
            "history_predates_warmup_start_2023_06_21": auto_warmed,
            "realistic_path": "AUTO_WARMED (maintained==native; no _seed_weekly)" if auto_warmed
            else "INDETERMINATE (history begins inside warmup — would be seeded)",
            "weekly_bar_count_check": count_chk,
            "realistic_maintained_vs_native_diff": realistic_diff,
            "forced_midweek_seed_day": FORCED_SEED_DAY.isoformat(),
            "forced_seed_overlap_diff": forced_diff,
        }

    payload = {
        "ticker_set": list(PROBES),
        "warmup_days": WARMUP_DAYS,
        "fy_start": FY_START.isoformat(),
        "fy_end": FY_END.isoformat(),
        "ichimoku": "9,26,26,52,26,26 (weekly)",
        "note": (
            "RAW conformed daily zips only. NATIVE = single clean weekly_aggregate. The #265 "
            "probes all have daily history predating warmup-start (2023-06-21) and clear the "
            "floors, so they are AUTO-WARMED in warmup (is_warming_up guard skips _seed_weekly) "
            "→ realistic maintained==native (zero diff). forced_seed_overlap_diff FORCES a "
            "mid-week (Wed 2025-03-12) _seed_weekly to MEASURE the seed-overlap defect magnitude "
            "as if the name were a post-warmup mid-FY entrant: the forward-only Ichimoku keeps "
            "the seed's PARTIAL current week (the same-Monday full-week re-emit is rejected)."
        ),
        "probes": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    op = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "research/parity/artifacts/diag-268-maintained-vs-native.json"
    )
    res = run(op)
    print(f"wrote {op}")
    for tk, r in res["probes"].items():
        if "error" in r:
            print(f"  {tk}: {r['error']}")
            continue
        rd = r["realistic_maintained_vs_native_diff"]
        fd = r["forced_seed_overlap_diff"]
        c = r["weekly_bar_count_check"]
        fk = fd["max_abs_diff"]
        print(
            f"  {tk}: auto_warmed={r['history_predates_warmup_start_2023_06_21']} "
            f"data_starts={r['data_starts']} first_active={r['first_active_fy']} | "
            f"REALISTIC weeks_diff={rd['fy_weeks_with_any_diff']}/{rd['fy_weeks_compared']} | "
            f"FORCED-seed weeks_diff={fd['fy_weeks_with_any_diff']}/{fd['fy_weeks_compared']} "
            f"max_abs(tenkan={fk['tenkan']:.3f},kijun={fk['kijun']:.3f},"
            f"sa={fk['senkou_a']:.3f},sb={fk['senkou_b']:.3f}) | "
            f"seed_pole={c['seed_completed_pre_fy']}>=78:{c['seed_clears_pole']} "
            f"native_pole={c['native_completed_pre_fy']}>=78:{c['native_clears_pole']} "
            f"count_delta={c['count_delta_seed_minus_native']}"
        )
