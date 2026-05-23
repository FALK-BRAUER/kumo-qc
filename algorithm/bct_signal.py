"""
BCT (Blue Cloud Trading) signal scorer — 8-condition Ichimoku checklist.
Used by both live_bct.py (QC native) and backtest_bct.py (QC native).
Also runnable standalone with yfinance for parity testing.
"""

import numpy as np
import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────────

def _kijun(close: pd.Series, period: int = 26) -> pd.Series:
    h = close.rolling(period).max()
    l = close.rolling(period).min()
    return (h + l) / 2


def _tenkan(close: pd.Series, period: int = 9) -> pd.Series:
    h = close.rolling(period).max()
    l = close.rolling(period).min()
    return (h + l) / 2


def _span_a(tenkan: pd.Series, kijun: pd.Series) -> pd.Series:
    return ((tenkan + kijun) / 2).shift(26)


def _span_b(close: pd.Series, period: int = 52) -> pd.Series:
    h = close.rolling(period).max()
    l = close.rolling(period).min()
    return ((h + l) / 2).shift(26)


def _chikou(close: pd.Series) -> pd.Series:
    return close.shift(-26)


def _adx_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Wilder's EWM ADX. alpha=1/period, adjust=False — matches TC2000."""
    alpha = 1 / period

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    atr = pd.Series(plus_dm, index=close.index).ewm(alpha=alpha, adjust=False).mean()
    # reuse atr name temporarily — compute actual ATR
    tr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_smooth = pd.Series(plus_dm, index=close.index).ewm(alpha=alpha, adjust=False).mean()
    minus_smooth = pd.Series(minus_dm, index=close.index).ewm(alpha=alpha, adjust=False).mean()

    plus_di = 100 * plus_smooth / tr_smooth
    minus_di = 100 * minus_smooth / tr_smooth

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx, plus_di, minus_di


# ── standalone scorer (yfinance data for parity testing) ─────────────────────

def score_symbol(df_daily: pd.DataFrame, df_weekly: pd.DataFrame) -> tuple[int, str]:
    """
    Score a symbol on BCT 8-condition checklist.
    df_daily / df_weekly must have columns: open, high, low, close, volume.
    Returns (score, rating) where rating is +++/++/+/=/--
    """
    try:
        dc = df_daily["close"]
        dh = df_daily["high"]
        dl = df_daily["low"]
        wc = df_weekly["close"]
        wh = df_weekly["high"]
        wl = df_weekly["low"]

        # Weekly indicators
        w_ten = _tenkan(wc)
        w_kij = _kijun(wc)
        w_spa = _span_a(w_ten, w_kij)
        w_spb = _span_b(wc)
        w_chi = _chikou(wc)

        # Daily indicators
        d_ten = _tenkan(dc)
        d_kij = _kijun(dc)
        d_spa = _span_a(d_ten, d_kij)
        d_adx, d_plus_di, d_minus_di = _adx_wilder(dh, dl, dc)
        d_ma200 = dc.rolling(200).mean()

        # Current values
        cp = dc.iloc[-1]
        w_spa_now = w_spa.iloc[-1]
        w_spb_now = w_spb.iloc[-1]
        w_ten_now = w_ten.iloc[-1]
        w_kij_now = w_kij.iloc[-1]
        w_chi_now = w_chi.iloc[-52] if len(wc) > 52 else float("nan")
        w_price_26ago = wc.iloc[-27] if len(wc) > 27 else float("nan")
        d_spa_now = d_spa.iloc[-1]
        d_ten_now = d_ten.iloc[-1]
        adx_now = d_adx.iloc[-1]
        plus_di_now = d_plus_di.iloc[-1]
        minus_di_now = d_minus_di.iloc[-1]
        ma200_now = d_ma200.iloc[-1]

        conditions = [
            cp > max(w_spa_now, w_spb_now),           # c1: weekly above cloud
            w_ten_now > w_kij_now,                     # c2: weekly tenkan > kijun
            w_chi_now > w_price_26ago,                 # c3: weekly chikou > price 26w ago
            w_spa_now > w_spb_now,                     # c4: weekly cloud green
            cp > max(d_spa_now, d_spa.shift(1).iloc[-1] if not pd.isna(d_spa.shift(1).iloc[-1]) else d_spa_now),  # c5: daily above cloud
            cp > d_ten_now,                            # c6: daily above tenkan
            adx_now >= 20 and plus_di_now > minus_di_now,  # c7: ADX rising + +DI > -DI
            cp > ma200_now,                            # c8: above 200d MA
        ]

        score = sum(1 for c in conditions if c is True or c == True)
        rating = _rating(score)
        return score, rating

    except Exception:
        return 0, "--"


def _rating(score: int) -> str:
    if score == 8:
        return "+++"
    if score >= 6:
        return "++"
    if score >= 4:
        return "+"
    if score >= 2:
        return "="
    return "--"


# ── QC-native scorer (uses self.History) ─────────────────────────────────────

def score_symbol_native(algorithm, symbol: str, period: int = 9) -> tuple[int, str]:
    """
    Score using QC History API. Fetches 80 daily bars per symbol.
    Used inside live_bct.py and backtest_bct.py QCAlgorithm subclasses.
    Returns (score, rating).
    """
    try:
        hist = algorithm.History(symbol, 300, algorithm.Resolution.Daily)
        if hist.empty:
            return 0, "--"

        hist = hist.reset_index()
        close = hist["close"]
        high = hist["high"]
        low = hist["low"]

        # Build daily df
        df_d = pd.DataFrame({"close": close.values, "high": high.values, "low": low.values})

        # Weekly resample from daily (approximate)
        n = len(df_d)
        week_idx = list(range(4, n, 5))
        df_w = df_d.iloc[week_idx].reset_index(drop=True)

        return score_symbol(df_d, df_w)

    except Exception:
        return 0, "--"
