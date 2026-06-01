"""tests/harness/realdata.py — shared real-data integration primitives (#260 G-DATA).

The local-LEAN real-data tests previously hand-rolled the SAME code in every file: the daily
zip parse, the coarse-row shape, the data-presence skip guard, and the QC-native indicator
value-wrappers (the `_Cur`/`_Ind`/`_Ichi`/`_Adx`/`_Window` shapes were triplicated across
`tests/integration/test_warm_before_score_realdata.py`, `tests/integration/fake_qc.py` and
`tests/phases/shared/test_score_symbol_native.py`). This module is the ONE home for them.

Two kinds of primitive live here:

  1. REAL on-disk loaders — daily zip, intraday 5-min trade zip, coarse CSV — returning the
     exact frames/rows the REAL engine code consumes. NO synthetic data.
  2. QC-native value WRAPPERS — the `.current.value` / `.is_ready` / RollingWindow shapes QC's
     compiled IchimokuKinkoHyo / ADX / SMA would expose. These are the ONLY fakes the chain
     test is permitted: QC's C# indicators are unavailable in the dev venv, but the VALUES
     placed in the wrappers are computed from REAL on-disk history via the REAL oracle math
     (`oracle_helpers._mid` / `_adx_wilder`) and the REAL seed aggregation
     (`runtime.indicators.weekly_aggregate`), and the logic under test is the REAL
     `score_symbol_native`. Faking the wrapper shape is NOT faking the chain.
"""
from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

import runtime.lean_entry as lean_entry
from phases.shared.oracle_helpers import _adx_wilder, _mid
from runtime.indicators import weekly_aggregate
from runtime.lean_entry import BctEngineAlgorithm

# ── data tree paths (the gitignored local LEAN tree, reached via the worktree data symlink) ──
_ROOT = Path(__file__).resolve().parents[2]
DATA_USA = _ROOT / "data" / "equity" / "usa"
DAILY_DIR = DATA_USA / "daily"
MINUTE_DIR = DATA_USA / "minute"
COARSE_DIR = DATA_USA / "fundamental" / "coarse"

# Seed window = BctEngineAlgorithm.WARMUP_DAYS (560 trading bars; the INT-form qc.history count).
WARMUP_DAYS: int = BctEngineAlgorithm.WARMUP_DAYS

# A liquid spread that survives the selection floors and has multi-year daily history on disk.
LIQUID = ("aapl", "msft", "spy")


# ======================================================================================
# Data-presence guards (a SKIP on absent data is a presence guard, never a silent pass).
# ======================================================================================
def have_daily_tree() -> bool:
    return DAILY_DIR.is_dir()


def have_coarse_tree() -> bool:
    return COARSE_DIR.is_dir() and any(COARSE_DIR.glob("2025*.csv"))


def have_minute_tree() -> bool:
    return MINUTE_DIR.is_dir()


def daily_available(ticker: str) -> bool:
    return (DAILY_DIR / f"{ticker}.zip").is_file()


def minute_available(ticker: str) -> bool:
    return (MINUTE_DIR / ticker).is_dir()


# ======================================================================================
# REAL on-disk loaders.
# ======================================================================================
def read_daily_zip(ticker: str) -> pd.DataFrame:
    """Real on-disk daily OHLCV → the lowercased, date-indexed frame the seed path consumes.
    LEAN daily zips are `yyyymmdd HH:MM,open,high,low,close,volume`, prices in deci-cents
    (/10000)."""
    zp = DAILY_DIR / f"{ticker}.zip"
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


def read_minute_trade_zip(ticker: str, ymd: str) -> pd.DataFrame:
    """Real on-disk intraday 5-min trade bars for one session → lowercased OHLCV frame, indexed
    by the bar's wall-clock time. LEAN minute trade zips hold `ms_since_midnight,o,h,l,c,v` with
    prices in deci-cents (/10000)."""
    zp = MINUTE_DIR / ticker / f"{ymd}_trade.zip"
    with zipfile.ZipFile(zp) as z:
        raw = z.read(z.namelist()[0]).decode()
    midnight = pd.Timestamp(dt.datetime.strptime(ymd, "%Y%m%d"))
    rows = []
    for ln in raw.strip().split("\n"):
        ms, o, h, lo, c, v = ln.split(",")
        rows.append((midnight + pd.Timedelta(milliseconds=int(ms)),
                     float(o) / 10000, float(h) / 10000, float(lo) / 10000,
                     float(c) / 10000, float(v)))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    return df.set_index("time")


class CoarseRow:
    """Real 8-col QC-native coarse row → the coarse-object shape `_coarse_selection` reads
    (`.symbol.value`, `.price`, `.dollar_volume`). Columns: SID,ticker,price,vol,dollar_volume,…"""

    def __init__(self, row: str) -> None:
        cols = row.split(",")
        self.symbol = _Sym(cols[1])
        self.price = float(cols[2])
        self.dollar_volume = float(cols[4])


def read_coarse_rows(ymd: str) -> list[CoarseRow]:
    """Real conformed coarse feed for one session → the list of coarse objects the selection
    gate consumes."""
    lines = [ln for ln in (COARSE_DIR / f"{ymd}.csv").read_text().splitlines() if ln]
    return [CoarseRow(r) for r in lines]


# ======================================================================================
# Selection-gate driver — drives the REAL `_coarse_selection`. Only the QC `Symbol` factory
# (None in the dev venv) is stubbed; every selection step (prefilter, maintained rolling-DV,
# apply_floors, rank_and_cap) is the REAL engine code. Mirrors tests/data/test_active_set_nonempty.
# ======================================================================================
class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


class _SymbolFactory:
    @staticmethod
    def create(ticker, _sectype, _market):  # mimics Symbol.create(ticker, EQUITY, USA)
        return _Sym(ticker)


def make_selection_algo(monkeypatch, when: dt.datetime) -> BctEngineAlgorithm:
    """A BctEngineAlgorithm wired to drive the REAL `_coarse_selection` over real coarse rows."""
    monkeypatch.setattr(lean_entry, "Symbol", _SymbolFactory)
    monkeypatch.setattr(lean_entry, "SecurityType", type("ST", (), {"EQUITY": 1}))
    monkeypatch.setattr(lean_entry, "Market", type("MK", (), {"USA": "usa"}))
    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally; initialize() not invoked
    algo._dv_windows = {}
    algo._dv_day_index = -1
    algo._ranked_today = []
    algo._trailing_dv = {}
    algo._bar_metrics = {}
    algo.time = when
    algo.logged = []
    algo.log = lambda m: algo.logged.append(m)  # type: ignore[method-assign,assignment]
    return algo


# ======================================================================================
# QC-native value WRAPPERS — the ONLY permitted fakes (the dev venv has no compiled QC
# indicators). VALUES are real (computed below from real history); shapes mimic QC's accessors.
# ======================================================================================
class _Cur:
    def __init__(self, v: float) -> None:
        self.value = float(v)


class _IndV:
    """A sub-indicator exposing `.current.value` (tenkan/kijun/senkou/+DI/-DI)."""

    def __init__(self, v: float) -> None:
        self.current = _Cur(v)


class _Scalar:
    """A maintained scalar with `.current.value` + `.is_ready` (sma200 / roc13)."""

    def __init__(self, v: float, *, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    """IchimokuKinkoHyo shape: tenkan/kijun/senkou_a/senkou_b each an `_IndV`, + `.is_ready`."""

    def __init__(self, t: float, k: float, sa: float, sb: float, *, ready: bool = True) -> None:
        self.tenkan = _IndV(t)
        self.kijun = _IndV(k)
        self.senkou_a = _IndV(sa)
        self.senkou_b = _IndV(sb)
        self.is_ready = ready


class _Adx:
    """ADX shape: `.current.value` + `.positive/negative_directional_index.current.value`."""

    def __init__(self, adx: float, pdi: float, ndi: float, *, ready: bool = True) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _IndV(pdi)
        self.negative_directional_index = _IndV(ndi)
        self.is_ready = ready


class _Window:
    """RollingWindow shape — newest at [0]; `.count` == len. (score_symbol_native reads
    w_close[0]/[26] and adx_window[0]/[3].)"""

    def __init__(self, values_newest_first: list[float]) -> None:
        self._v = [float(x) for x in values_newest_first]

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


class FakeQC:
    """Minimal QC stand-in exposing `securities[symbol].price` (the live price the scorer reads)."""

    def __init__(self, price: float, symbol: Any) -> None:
        self.securities = {symbol: type("S", (), {"price": float(price)})()}


def build_real_native_inputs(daily: pd.DataFrame) -> tuple[dict[str, Any], float]:
    """Compute the maintained-suite `ind` dict `score_symbol_native` reads, with REAL values from
    a real daily OHLCV frame — via the REAL oracle math and the REAL weekly seed aggregation.
    All inputs returned READY (the warm state). Wrapper SHAPES are QC-native fakes; the VALUES
    are real. Requires a full window (>=200 daily, >=78 weekly bars) for non-NaN structure —
    callers gate on `assert_can_warm` first."""
    h, lo, c = daily["high"], daily["low"], daily["close"]
    # daily ichimoku (oracle _mid: midpoint of rolling high/low)
    d_tenkan = _mid(h, lo, 9).iloc[-1]
    d_kijun = _mid(h, lo, 26).iloc[-1]
    d_sa = ((_mid(h, lo, 9) + _mid(h, lo, 26)) / 2).shift(26).iloc[-1]
    d_sb = _mid(h, lo, 52).shift(26).iloc[-1]
    # weekly ichimoku — from the REAL seed aggregation (runtime.indicators.weekly_aggregate)
    weekly = weekly_aggregate(daily)
    wdf = pd.DataFrame(weekly)
    wh, wl, wc = wdf["high"], wdf["low"], wdf["close"]
    w_tenkan = _mid(wh, wl, 9).iloc[-1]
    w_kijun = _mid(wh, wl, 26).iloc[-1]
    w_sa = ((_mid(wh, wl, 9) + _mid(wh, wl, 26)) / 2).shift(26).iloc[-1]
    w_sb = _mid(wh, wl, 52).shift(26).iloc[-1]
    w_close_newest_first = list(wc.iloc[::-1])
    # sma200, adx (oracle Wilder), price
    ma200 = c.rolling(200).mean().iloc[-1]
    adx, pdi, ndi = _adx_wilder(daily, period=9)
    adx_newest_first = list(adx.iloc[::-1])
    price = float(c.iloc[-1])

    ind = {
        "d_ichi": _Ichi(d_tenkan, d_kijun, d_sa, d_sb, ready=True),
        "w_ichi": _Ichi(w_tenkan, w_kijun, w_sa, w_sb, ready=True),
        "w_close": _Window(w_close_newest_first),
        "sma200": _Scalar(ma200, ready=True),
        "adx": _Adx(adx.iloc[-1], pdi.iloc[-1], ndi.iloc[-1], ready=True),
        "adx_window": _Window(adx_newest_first),
        "roc13": _Scalar(0.0, ready=True),  # value unused by the 8 conditions; readiness gates
    }
    return ind, price


def build_native_suite(
    *,
    d_ready: bool,
    w_ready: bool,
    sma_ready: bool,
    adx_ready: bool,
    roc_ready: bool,
    wclose_n: int,
    adxwin_n: int,
    price: float = 100.0,
) -> tuple[dict[str, Any], "FakeQC"]:
    """A MANUAL-value maintained suite (a real-plausible 8/8-pass value layout at price 100) with
    each input's READINESS / window-count set explicitly — the property-fuzz builder for the
    anti-mirage 'cold cannot score' invariant. The values are fixed; only readiness varies. This
    is the canonical home for the `_Cur`/`_Ichi`/`_Adx`/`_Window` shapes that were triplicated
    across the real-data tests."""
    ind = {
        "d_ichi": _Ichi(90.0, 88.0, 85.0, 80.0, ready=d_ready),
        "w_ichi": _Ichi(70.0, 60.0, 75.0, 65.0, ready=w_ready),
        "w_close": _Window([float(i) for i in range(wclose_n)]),
        "sma200": _Scalar(50.0, ready=sma_ready),
        "adx": _Adx(25.0, 30.0, 10.0, ready=adx_ready),
        "adx_window": _Window([float(i) for i in range(adxwin_n)]),
        "roc13": _Scalar(0.10, ready=roc_ready),
    }
    return ind, FakeQC(price=price, symbol="SYM")


# Which not-ready key flips which gate in score_symbol_native (the HALF-2 cold-cannot-score map).
_FLAGGED = ("d_ichi", "w_ichi", "sma200", "adx", "roc13")


def with_input_not_ready(daily: pd.DataFrame, key: str) -> tuple[dict[str, Any], float]:
    """The same REAL warm inputs, but ONE input forced not-ready — the cold control. Flipping a
    readiness flag (or shortening a window below its count gate) must make the scorer return
    None: 'cold cannot score'."""
    ind, price = build_real_native_inputs(daily)
    if key in _FLAGGED:
        ind[key].is_ready = False
    elif key == "w_close":
        ind[key] = _Window([1.0] * 10)  # count 10 < 27 → the w_close[26] gate trips
    elif key == "adx_window":
        ind[key] = _Window([1.0, 2.0, 3.0])  # count 3 < 4 → the adx 3-back gate trips
    else:  # pragma: no cover - guard against a typo'd key
        raise KeyError(f"unknown native input key: {key}")
    return ind, price
