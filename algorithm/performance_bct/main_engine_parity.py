"""
Engine-integrated algorithm for ARCH-C parity proof.
Identical to BCTPerformanceAlgorithm except _rebalance uses StrategyEngine.
Target: ±0.01 Sharpe vs baseline-oracle-v0 (1.079 local FY2025).

Usage:
  cp main_engine_parity.py main.py && bash scripts/lean-bt.sh algorithm/performance_bct FY2025-engine
  cp main_oracle_backup.py main.py  # restore oracle
"""
from __future__ import annotations
import sys
from pathlib import Path

# Add src/ to path so engine + phases are importable from LEAN
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import oracle base (contains all Initialize/indicator logic)
# Import as a module to avoid name collision
import importlib.util
_oracle_spec = importlib.util.spec_from_file_location("oracle_main", Path(__file__).parent / "main.py")

# Re-export all oracle helpers for LEAN compatibility
import json
from datetime import timedelta
from typing import Any

from AlgorithmImports import *  # noqa: F401,F403

import numpy as np
import pandas as pd

from engine.context import PhaseContext
from main_champion_asis import build_engine


# Copy oracle helper functions (identical to oracle — needed by oracle_helpers.py import)
_WEEKLY_BARS = 130
_DAILY_BARS = 700


def _mid(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def _adx_wilder(df: pd.DataFrame, period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    h, lo, c = df["high"], df["low"], df["close"]
    pc, ph, pl = c.shift(1), h.shift(1), lo.shift(1)
    tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    up = h - ph
    dn = pl - lo
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up.values, 0.0), index=df.index, dtype=float)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn.values, 0.0), index=df.index, dtype=float)
    a = 1.0 / period
    atr = tr.ewm(alpha=a, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=a, adjust=False).mean() / atr
    minus_di = 100.0 * minus_dm.ewm(alpha=a, adjust=False).mean() / atr
    denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / denom
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx, plus_di, minus_di


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    weekly = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return weekly.dropna(subset=["close"])


def _fetch_ohlcv(algorithm: Any, symbol: Any, bars: int, resolution: Any) -> pd.DataFrame:
    try:
        df = algorithm.History([symbol], bars, resolution)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.index, pd.MultiIndex):
        df = df.droplevel(0)
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return pd.DataFrame()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def score_symbol(algorithm: Any, symbol: Any) -> dict[str, Any] | None:
    daily = _fetch_ohlcv(algorithm, symbol, _DAILY_BARS, Resolution.DAILY)
    if len(daily) < 230:
        return None
    weekly = _resample_weekly(daily)
    if len(weekly) < 78:
        return None
    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun  = _mid(weekly["high"], weekly["low"], 26)
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)
    w_price = weekly["close"].iloc[-1]
    w_cloud_a_now = w_cloud_a.iloc[-1]; w_cloud_b_now = w_cloud_b.iloc[-1]
    w_tenkan_now = w_tenkan.iloc[-1]; w_kijun_now = w_kijun.iloc[-1]
    w_price_26_ago = weekly["close"].iloc[-27]
    d_tenkan = _mid(daily["high"], daily["low"], 9)
    d_kijun  = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)
    d_cloud_b = _mid(daily["high"], daily["low"], 52).shift(26)
    d_price = daily["close"].iloc[-1]; d_tenkan_now = d_tenkan.iloc[-1]
    d_cloud_a_now = d_cloud_a.iloc[-1]; d_cloud_b_now = d_cloud_b.iloc[-1]
    ma200 = daily["close"].rolling(200).mean().iloc[-1]
    adx, plus_di, minus_di = _adx_wilder(daily, period=9)
    adx_now = adx.iloc[-1]; plus_di_now = plus_di.iloc[-1]; minus_di_now = minus_di.iloc[-1]
    adx_rising = bool(adx.iloc[-1] > adx.iloc[-4])
    critical = [w_cloud_a_now, w_cloud_b_now, w_tenkan_now, w_kijun_now, w_price_26_ago,
                d_cloud_a_now, d_cloud_b_now, d_tenkan_now, ma200, adx_now, plus_di_now, minus_di_now]
    if any(pd.isna(v) for v in critical):
        return None
    conditions = [
        bool(w_price > max(w_cloud_a_now, w_cloud_b_now)),
        bool(w_tenkan_now > w_kijun_now),
        bool(w_price > w_price_26_ago),
        bool(w_cloud_a_now > w_cloud_b_now),
        bool(d_price > max(d_cloud_a_now, d_cloud_b_now)),
        bool(d_price > d_tenkan_now),
        bool(adx_rising and plus_di_now > minus_di_now and adx_now >= 20),
        bool(d_price > ma200),
    ]
    score = sum(conditions)
    rating = "+++" if score == 8 else "++" if score >= 6 else "+" if score >= 4 else "=" if score >= 2 else "--"
    return {"score": score, "rating": rating, "conditions": conditions}


def score_symbol_native(algorithm: Any, symbol: Any, ind: Any) -> dict[str, Any] | None:
    return score_symbol(algorithm, symbol)


class BCTEngineAlgorithm(QCAlgorithm):
    """
    Engine-integrated BCT algorithm for ARCH-C parity proof.
    Initialize() is byte-identical to oracle. _rebalance() calls StrategyEngine.
    """

    MAX_POSITIONS: int = 9999
    POSITION_PCT: float = 0.10
    MIN_SCORE: int = 7
    ENABLE_CLOUD_BREACH_EXIT: bool = False
    ENABLE_WEEKLY_KIJUN_EXIT: bool = False
    PHASE3_DAYS: int = 56
    PHASE3_PNL: float = 0.15

    @staticmethod
    def _find_local_data_dir() -> Path | None:
        candidates = [
            Path("/Lean/Data/equity/usa/daily"),
            Path("/Data/equity/usa/daily"),
            Path(__file__).parent.parent.parent / "data/equity/usa/daily",
        ]
        return next((d for d in candidates if d.exists()), None)

    def initialize(self) -> None:
        self.log("VERSION_MARKER|engine_champion_asis_v1")
        self.set_time_zone("America/New_York")
        sy = int(self.get_parameter("start_year",  "2025"))
        sm = int(self.get_parameter("start_month", "1"))
        sd = int(self.get_parameter("start_day",   "1"))
        ey = int(self.get_parameter("end_year",    "2025"))
        em = int(self.get_parameter("end_month",   "12"))
        ed = int(self.get_parameter("end_day",     "31"))
        self.set_start_date(sy, sm, sd)
        self.set_end_date(ey, em, ed)
        self.set_cash(100_000)
        self.set_benchmark("SPY")
        warmup_days = int(self.get_parameter("warmup_days", "750"))
        self.set_warmup(timedelta(days=warmup_days))
        self.warmup_days = warmup_days
        self.cloud_exit_enabled = False
        self.weekly_kijun_exit_enabled = False
        self.spy = self.add_equity("SPY", Resolution.DAILY)
        self.spy_sma200 = self.sma("SPY", 200)
        _regime_param = self.get_parameter("regime_gate_enabled", "")
        self.regime_gate_enabled = _regime_param != "false"
        self.parabolic_threshold = float(self.get_parameter("parabolic_threshold", "") or "0.25")
        self.vix_percentile_enabled = False
        self.vix = self.add_index("VIX", Resolution.DAILY).symbol
        self.vix_ichi = self.ichimoku(self.vix, 9, 26, 26, 52, 26, 26)
        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW
        self._active: set = set()
        self._indicators: dict = {}
        self._polygon_universe: dict | None = None
        self._position_meta: dict = {}

        # UNIFIED loader (same as #182 fix)
        obj_key = "polygon_universe_equity200_fy2025.json"
        if not self.object_store.contains_key(obj_key):
            local_candidates = [
                Path(__file__).parent / obj_key,
                Path("/Lean/Data") / obj_key,
            ]
            injected = False
            for local_path in local_candidates:
                if local_path.exists():
                    self.object_store.save(obj_key, local_path.read_text())
                    injected = True
                    break
            if not injected:
                raise Exception(f"UniverseLoadError: ObjectStore key {obj_key!r} not found")
        poly = json.loads(self.object_store.read(obj_key))
        if not poly:
            raise Exception("UniverseLoadError: universe JSON empty")
        self._polygon_universe = poly
        all_tickers = sorted({t for tickers in poly.values() for t in tickers})
        self.log(f"UNIVERSE|polygon_equity|unique_tickers={len(all_tickers)}|path=object_store")
        for ticker in all_tickers:
            try:
                self.add_equity(ticker, Resolution.DAILY)
            except Exception:
                pass

        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.at(16, 5),
            self._rebalance,
        )

        # Build engine after Initialize
        self._engine = build_engine(self)
        self.log("VERSION_MARKER|champion_asis_v1_engine_ready")

    def on_securities_changed(self, changes: SecurityChanges) -> None:
        for s in changes.added_securities:
            sym = s.symbol
            self._active.add(sym)
            if sym not in self._indicators:
                self._register_indicators(sym)
        for s in changes.removed_securities:
            sym = s.symbol
            self._active.discard(sym)
            if sym in self._indicators:
                self.subscription_manager.remove_consolidator(sym, self._indicators[sym]["consolidator"])
                del self._indicators[sym]

    def _register_indicators(self, sym) -> None:
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)
        consolidator = TradeBarConsolidator(Calendar.WEEKLY)
        def _on_weekly(_, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)
        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)
        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)
        self._indicators[sym] = {"d_ichi": d_ichi, "w_ichi": w_ichi, "w_close": w_close, "sma200": sma200, "consolidator": consolidator}

    def _seed_weekly(self, sym, w_ichi, w_close) -> None:
        hist = self.history(sym, 750, Resolution.DAILY)
        if hist is None or hist.empty:
            return
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        if not {"open", "high", "low", "close", "volume"}.issubset(hist.columns):
            return
        weeks: dict = {}
        for time, row in hist.iterrows():
            friday = time + pd.Timedelta(days=(4 - time.weekday()) % 7)
            friday = friday.normalize()
            if friday not in weeks:
                weeks[friday] = {"open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": int(row["volume"])}
            else:
                weeks[friday]["high"] = max(weeks[friday]["high"], float(row["high"]))
                weeks[friday]["low"] = min(weeks[friday]["low"], float(row["low"]))
                weeks[friday]["close"] = float(row["close"])
                weeks[friday]["volume"] += int(row["volume"])
        for time in sorted(weeks):
            row = weeks[time]
            bar = TradeBar(time, sym, row["open"], row["high"], row["low"], row["close"], row["volume"], timedelta(weeks=1))
            w_ichi.update(bar)
            w_close.add(float(row["close"]))

    def _daily_vals(self, symbol) -> tuple[float, float, float, float] | None:
        if symbol not in self._indicators:
            return None
        d_ichi = self._indicators[symbol]["d_ichi"]
        if not d_ichi.is_ready:
            return None
        close = float(self.securities[symbol].close)
        kijun = d_ichi.kijun.current.value
        senkou_a = d_ichi.senkou_a.current.value
        senkou_b = d_ichi.senkou_b.current.value
        return close, kijun, max(senkou_a, senkou_b), min(senkou_a, senkou_b)

    def _has_open_orders(self, symbol) -> bool:
        return bool(self.transactions.get_open_orders(symbol))

    def _rebalance(self) -> None:
        if self.is_warming_up:
            return
        ctx = PhaseContext(qc=self, time=self.time, data=None)
        self._engine.on_data_with_ctx(ctx)
