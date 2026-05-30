"""Indicator lifecycle helpers (#213c) — the pure, golden-masterable pieces.

The per-symbol indicator PLUMBING (QC native ichimoku/sma + a weekly consolidator) lives
in runtime.lean_entry (QC runtime). The one piece that is pure Python — and parity-critical
— is the manual daily->weekly aggregation. It is carved EXACTLY from the legacy champion's
_seed_weekly (algorithm/performance_bct/main.py): the proven workaround for the QC-cloud
DataFrame.resample() 5-minute timeout (commit 8048c29). Reproduce faithfully; do NOT
re-optimize (honest baseline first).

INDICATOR_KEYS is the documented contract of qc._indicators[symbol] — the lifecycle
populates exactly these; the phases (bct_score_full pre-filter, kijun_g3_exits) read them.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

# The exact contract of qc._indicators[symbol]. Lifecycle populates ALL of these; phases
# read a subset. consolidator is retained so on_securities_changed can dispose it.
#   d_ichi     daily IchimokuKinkoHyo (conditions 5,6: daily>cloud, daily>tenkan)
#   w_ichi     weekly IchimokuKinkoHyo (conditions 1,2,4: weekly>cloud, tenkan>kijun, green)
#   w_close    RollingWindow[float](28) weekly closes (condition 3: chikou vs 26 completed wks)
#   sma200     daily SMA(200) (condition 8: price>200MA)
#   adx        daily ADX(9) (condition 7: adx>=20, +DI>-DI)            [#213f maintained]
#   adx_window RollingWindow[float](5) of ADX values (condition 7: adx_rising = [0]>[3]) [#213f]
#   roc13      daily ROC(13) (parabolic entry block: 13-day run > threshold) [#213f maintained]
#   consolidator  weekly TradeBarConsolidator (disposed on unsubscribe)
# #213f added adx/adx_window/roc13 so the SIGNAL reads maintained indicators O(1)/candidate
# (zero per-bar history → no 10s isolator timeout). NOTE: maintained ADX/ROC are NEW design
# (legacy computed ADX via per-bar history, fit only because its universe was ~326); no
# legacy template — the QC wiring (adx.updated → window; roc convention) is integration-
# verified on the LEAN run, flagged for confirmation.
INDICATOR_KEYS: tuple[str, ...] = (
    "d_ichi", "w_ichi", "w_close", "sma200", "adx", "adx_window", "roc13", "consolidator",
)


def weekly_friday(ts: pd.Timestamp) -> pd.Timestamp:
    """The Friday of ts's week, normalized — the weekly bucket key. Exact legacy rule:
    ts + (4 - weekday) % 7 days, normalized to midnight (Mon..Sun -> that week's Friday)."""
    return (ts + pd.Timedelta(days=(4 - ts.weekday()) % 7)).normalize()


def weekly_aggregate(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """Aggregate a daily OHLCV frame into weekly (W-FRI) bars — the manual aggregation the
    legacy champion uses INSTEAD of df.resample (the QC-cloud timeout fix). Returns weekly
    bars in chronological order, each {friday, open, high, low, close, volume}.

    Rules (exact carve): first daily bar of a Friday-week sets OHLCV; subsequent bars in the
    same week extend high/low, overwrite close (last), accumulate volume. open is the FIRST
    day's open. Same result as resample('W-FRI').agg(first/max/min/last/sum), without the
    pandas-resample overhead that trips the cloud 5-min limit.

    Expects lowercased columns {open, high, low, close, volume} and a datetime index. Returns
    [] if columns are missing or the frame is empty.
    """
    if daily is None or daily.empty:
        return []
    cols = {"open", "high", "low", "close", "volume"}
    if not cols.issubset(daily.columns):
        return []

    weeks: dict[pd.Timestamp, dict[str, Any]] = {}
    for ts, row in daily.iterrows():
        friday = weekly_friday(ts)
        if friday not in weeks:
            weeks[friday] = {
                "friday": friday,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
            }
        else:
            w = weeks[friday]
            w["high"] = max(w["high"], float(row["high"]))
            w["low"] = min(w["low"], float(row["low"]))
            w["close"] = float(row["close"])  # last close wins
            w["volume"] += int(row["volume"])
    # Chronological by Friday — matches legacy `for time in sorted(weeks)` unconditionally
    # (not reliant on the input index being pre-sorted).
    return [weeks[f] for f in sorted(weeks)]
