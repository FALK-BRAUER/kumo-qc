"""#332 warmup-cache — the param-free indicator-TABLE builder (stage 2).

Runs the LEAN-faithful ports (daily Ichimoku + ADX(9) + SMA(200) + WeeklyIchimokuAsOf) over a
ticker's daily bars in ONE pass and records, per date, the ~14 scalars the 8-condition
`score_symbol_native` reads. PARAM-FREE: the indicators don't depend on cap/gap/vol, so one table
serves the whole grid. Fingerprint-keyed by (indicator_params_hash, data_fingerprint) so a LOCAL
table is reused only where the data is identical (never wrongly on cloud — the 83%-recon vendor delta).

RAM-SAFE BY CONSTRUCTION ([[feedback_ram_safe_parquet]] / the 160GB OOM lesson): STREAM per ticker —
read one ticker's daily zip, build its scalars, emit, free, next. NEVER pd.concat the universe; the
peak working set is ONE ticker's daily series (~1250 rows) + the indicator state (a few KB). The
driver caps parallelism + reports peak RSS.
"""
from __future__ import annotations

import datetime as _dt
import zipfile
from collections import deque
from pathlib import Path
from typing import Iterator

from sweeps.warmup_cache.lean_indicators import ADX, SMA, Ichimoku, RateOfChange, WeeklyIchimokuAsOf

# the cached scalars BctScoreFull reads (stable key order → consumption hook + parity gate agree).
# The first 14 feed the 8-condition score_symbol_native (golden-parity'd indicators); roc13 is the
# parabolic-block field BctScoreFull.evaluate reads separately (roc13 > parabolic_threshold → block).
# roc13 is validated by the LEAN-source formula ((c-c[13])/c[13]) + a deterministic unit test + the
# end-to-end gate (it materially affects which candidates block → exercised in trade-by-trade parity);
# it is NOT golden-file-validated (the spy_with_roc50 golden is a TA-Lib cross-ref, different convention).
SCALAR_FIELDS = (
    "d_price", "d_tenkan", "d_cloud_top", "ma200",
    "w_tenkan", "w_kijun", "w_senkou_a", "w_senkou_b", "w_close_0", "w_close_26",
    "adx_now", "plus_di", "minus_di", "adx_3back",
    "roc13",
)


def read_daily_zip(path: Path) -> Iterator[tuple[_dt.date, float, float, float, float, int]]:
    """STREAM a LEAN daily zip → (date, open, high, low, close, volume), RAW prices (÷10000). One row
    at a time — never materializes the whole file as a frame. Rows: 'YYYYMMDD HH:MM,O,H,L,C,V'."""
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            for raw in fh:
                line = raw.decode("ascii").strip()
                if not line:
                    continue
                parts = line.split(",")
                ts = parts[0][:8]
                d = _dt.date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
                o, h, l, c = (float(parts[i]) / 10000.0 for i in (1, 2, 3, 4))
                v = int(parts[5])
                yield d, o, h, l, c, v


def build_ticker_scalars(
    bars: Iterator[tuple[_dt.date, float, float, float, float, int]],
    *, adx_period: int = 9,
) -> Iterator[tuple[_dt.date, dict[str, float]]]:
    """Feed one ticker's daily bars (in date order) through the ports; yield (date, {14 scalars}) for
    every date where ALL indicators are ready (matches the live score's readiness gate). The weekly
    as-of is advanced inside (no look-ahead). adx_3back = the ADX value 3 trading days ago (the live
    adx_window[0]>adx_window[3] rising test)."""
    d_ichi = Ichimoku()
    sma200 = SMA(200)
    adx = ADX(period=adx_period)
    weekly = WeeklyIchimokuAsOf()
    roc13 = RateOfChange(13)
    adx_hist: deque[float] = deque(maxlen=4)  # [t-3 .. t] → adx_3back = adx_hist[0] when full

    for d, o, h, l, c in ((b[0], b[1], b[2], b[3], b[4]) for b in bars):
        d_ichi.update(h, l, c)
        sma200.update(c)
        adx.update(h, l, c)
        weekly.update(d, o, h, l, c)
        roc13.update(c)
        if not adx.is_ready or not weekly.is_ready:
            continue
        adx_hist.append(adx.adx)
        if not (d_ichi.is_ready and sma200.is_ready and roc13.is_ready and len(adx_hist) == 4):
            continue
        yield d, {
            "d_price": c,
            "d_tenkan": d_ichi.tenkan,
            "d_cloud_top": max(d_ichi.senkou_a, d_ichi.senkou_b),
            "ma200": sma200.value,
            "w_tenkan": weekly.tenkan,
            "w_kijun": weekly.kijun,
            "w_senkou_a": weekly.senkou_a,
            "w_senkou_b": weekly.senkou_b,
            "w_close_0": weekly.w_close(0),
            "w_close_26": weekly.w_close(26),
            "adx_now": adx.adx,
            "plus_di": adx.plus_di,
            "minus_di": adx.minus_di,
            "adx_3back": adx_hist[0],  # 3 back from current (window of 4: [t-3,t-2,t-1,t])
            "roc13": roc13.value,      # parabolic block (BctScoreFull): roc13 > parabolic_threshold → block
        }
