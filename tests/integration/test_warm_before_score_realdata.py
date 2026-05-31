"""#264 — the REAL-DATA anti-mirage integration guard (the #259 "wakes up in October" fingerprint
must be IMPOSSIBLE).

THE MIRAGE (research/parity/first-divergence-diff-2025.md, #173): indicators that warmed LATE
"woke up in October" — a name was effectively scored off partial/cold state, producing the fake
−0.616 baseline. The anti-mirage invariant has TWO halves, both asserted here over REAL on-disk
data (the data symlink), distinguishing 'correctly not-yet-ready -> excluded' from 'silently
scored cold -> mirage' (the latter must be UNREACHABLE):

  HALF 1 (SEED CAN reach readiness): over a real liquid name's daily history, WARMUP_DAYS of bars
    replayed through the REAL seed path (runtime.indicators.weekly_aggregate, the manual weekly
    aggregation _seed_weekly uses) yields >= 78 weekly bars — i.e. the WEEKLY IchimokuKinkoHyo
    (the BINDING 78-week readiness, the longest pole) CAN warm from the seed alone. If it could
    not, a post-warmup entrant would be cold at its first score -> the mirage. The daily-suite
    poles (200d SMA, 78d daily-Ichimoku, ADX, ROC, the 27-deep weekly-close window) are all
    SHORTER than 78 weeks, so the weekly bar count is the load-bearing sufficiency check.

  HALF 2 (COLD CANNOT score): the maintained scorer is STRUCTURALLY incapable of emitting a score
    while any input is not-ready — a property fuzz over the readiness flags on REAL-derived value
    layouts confirms score_symbol_native returns None whenever ANY gate is not-ready, and a number
    ONLY when ALL are ready. This is the invariant that makes "scored cold" unreachable: there is
    no value combination of not-ready inputs that yields a score.

If the local data tree is absent (CI without the gitignored data/), HALF 1 SKIPS with a reason
(data-presence guard, not a silent pass) — matching tests/data/test_warmup_coarse.py. HALF 2 is
pure logic and always runs.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from phases.shared.oracle_helpers import score_symbol_native
from runtime.indicators import weekly_aggregate
from runtime.lean_entry import BctEngineAlgorithm

_ROOT = Path(__file__).resolve().parents[2]
_DAILY = _ROOT / "data" / "equity" / "usa" / "daily"

# A representative spread of liquid names that survive the selection floors (price>=10, DV>=100M)
# and have multi-year daily history on disk — the post-warmup-entrant candidates.
_LIQUID = ["aapl", "msft", "spy"]


def _available(ticker: str) -> bool:
    return (_DAILY / f"{ticker}.zip").is_file()


def _read_daily(ticker: str) -> pd.DataFrame:
    """Real on-disk daily OHLCV -> the lowercased frame the seed path consumes. LEAN daily zips
    are `yyyymmdd HH:MM,open,high,low,close,volume` with prices in deci-cents (/10000)."""
    zp = _DAILY / f"{ticker}.zip"
    with zipfile.ZipFile(zp) as z:
        raw = z.read(z.namelist()[0]).decode()
    rows = []
    for ln in raw.strip().split("\n"):
        ts, o, h, lo, c, v = ln.split(",")
        rows.append((ts.split(" ")[0], float(o) / 10000, float(h) / 10000,
                     float(lo) / 10000, float(c) / 10000, float(v)))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df.set_index("date")


# ======================================================================================
# HALF 1 — the SEED can reach the binding weekly-Ichimoku readiness from real history.
# ======================================================================================
@pytest.mark.skipif(not _DAILY.is_dir(), reason="local LEAN daily tree absent (gitignored data/)")
@pytest.mark.parametrize("ticker", _LIQUID)
def test_seed_reaches_weekly_ichimoku_readiness_real_data(ticker: str) -> None:
    if not _available(ticker):
        pytest.skip(f"{ticker}.zip absent on disk")
    df = _read_daily(ticker)
    # _seed_weekly pulls `self.history(sym, WARMUP_DAYS, Resolution.DAILY)` — the INT form of QC
    # History returns that many BARS (trading days), not calendar days. So the seed window is the
    # LAST WARMUP_DAYS (560) trading bars ~ 112 weeks, comfortably above the 78-week pole.
    window = df.iloc[-BctEngineAlgorithm.WARMUP_DAYS:]
    weekly = weekly_aggregate(window)
    # BINDING constraint: the weekly IchimokuKinkoHyo needs 78 completed weekly bars to be ready.
    # The seed must deliver >= 78 from the WARMUP_DAYS window — else a post-warmup entrant is
    # cold at its first score (the mirage). >= 78 proves the seed CAN warm the longest pole.
    assert len(weekly) >= 78, (
        f"{ticker}: WARMUP_DAYS seed produced only {len(weekly)} weekly bars "
        f"(< 78 weekly-Ichimoku readiness) — a post-warmup entrant would be COLD at first score"
    )
    # And the 27-deep weekly-close window (chikou cond 3, score_symbol_native needs w_close[26])
    # is trivially satisfied by >= 78 weekly closes.
    assert len(weekly) >= 27


@pytest.mark.skipif(not _DAILY.is_dir(), reason="local LEAN daily tree absent (gitignored data/)")
@pytest.mark.parametrize("ticker", _LIQUID)
def test_seed_reaches_daily_suite_readiness_real_data(ticker: str) -> None:
    if not _available(ticker):
        pytest.skip(f"{ticker}.zip absent on disk")
    df = _read_daily(ticker)
    # Same INT-form history semantics: last WARMUP_DAYS (560) trading bars.
    window = df.iloc[-BctEngineAlgorithm.WARMUP_DAYS:]
    # The daily-suite poles (all SHORTER than the 78-week weekly pole): 200d SMA, 78d daily
    # Ichimoku, ADX(9), ROC(13). The seed feeds one bar per trading day -> need >= 200 trading
    # days for the longest daily pole (sma200) to warm. WARMUP_DAYS=560 bars >> 200.
    assert len(window) >= 200, (
        f"{ticker}: only {len(window)} trading days in the WARMUP_DAYS window — the 200d SMA "
        f"(longest daily pole) cannot warm from the seed"
    )


# ======================================================================================
# HALF 2 — COLD CANNOT score: the maintained scorer never emits a number off a not-ready input.
# Property fuzz over the readiness flags (the anti-mirage structural invariant).
# ======================================================================================
class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, t: float, k: float, sa: float, sb: float, ready: bool) -> None:
        self.tenkan = _IndV(t)
        self.kijun = _IndV(k)
        self.senkou_a = _IndV(sa)
        self.senkou_b = _IndV(sb)
        self.is_ready = ready


class _IndV:
    def __init__(self, v: float) -> None:
        self.current = _Cur(v)


class _Adx:
    def __init__(self, adx: float, pdi: float, ndi: float, ready: bool) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _IndV(pdi)
        self.negative_directional_index = _IndV(ndi)
        self.is_ready = ready


class _Window:
    def __init__(self, n: int) -> None:
        self._v = [float(i) for i in range(n)]

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


class _QC:
    def __init__(self, price: float) -> None:
        self.securities = {"SYM": type("S", (), {"price": price})()}


def _build_ind(*, d_r: bool, w_r: bool, sma_r: bool, adx_r: bool, roc_r: bool,
               wclose_n: int, adxwin_n: int) -> dict[str, Any]:
    # Real-plausible value layout (8/8-pass shape at price 100); only the READINESS varies.
    return {
        "d_ichi": _Ichi(90.0, 88.0, 85.0, 80.0, ready=d_r),
        "w_ichi": _Ichi(70.0, 60.0, 75.0, 65.0, ready=w_r),
        "w_close": _Window(wclose_n),
        "sma200": _Ind(50.0, ready=sma_r),
        "adx": _Adx(25.0, 30.0, 10.0, ready=adx_r),
        "adx_window": _Window(adxwin_n),
        "roc13": _Ind(0.10, ready=roc_r),
    }


def test_cold_cannot_score_property_fuzz() -> None:
    # Exhaustive small fuzz: across all combinations of the 5 readiness flags + the two window
    # counts at their boundaries, a score is emitted IFF every gate is ready. No not-ready combo
    # ever yields a number -> "silently scored cold" is structurally UNREACHABLE.
    import itertools

    scored_when_not_all_ready = []
    for d_r, w_r, sma_r, adx_r, roc_r in itertools.product([True, False], repeat=5):
        for wclose_n in (26, 27):       # 26 = too short, 27 = exactly ready
            for adxwin_n in (3, 4):     # 3 = too short, 4 = exactly ready
                ind = _build_ind(d_r=d_r, w_r=w_r, sma_r=sma_r, adx_r=adx_r, roc_r=roc_r,
                                 wclose_n=wclose_n, adxwin_n=adxwin_n)
                r = score_symbol_native(_QC(100.0), "SYM", ind)
                all_ready = (d_r and w_r and sma_r and adx_r and roc_r
                             and wclose_n >= 27 and adxwin_n >= 4)
                if r is not None and not all_ready:
                    scored_when_not_all_ready.append(
                        (d_r, w_r, sma_r, adx_r, roc_r, wclose_n, adxwin_n)
                    )
                if all_ready:
                    assert r is not None, "fully-ready set must score (sanity)"
    assert scored_when_not_all_ready == [], (
        f"MIRAGE: scorer emitted a score on a NOT-fully-ready input: {scored_when_not_all_ready}"
    )
