"""
Resistance / Support level computation — R/S #146 foundational data layer.

Pure, strategy-agnostic functions. Given a daily OHLCV DataFrame for ONE symbol
(columns: open/high/low/close/volume, ascending DatetimeIndex), compute the
structural R/S levels around the latest bar. Consumed by experiments #147-151;
no QuantConnect or strategy coupling so it stays unit-testable in isolation.

Levels produced (per symbol/date):
- 52-week high / low                 (static horizon anchors)
- 60-day swing highs/lows, >=3 touch (confirmed pivot clusters)
- round-number magnets               ($50 / $100 / $200 grid near price)
- Senkou A / B                       (passed in from caller's Ichimoku, not recomputed)
- volume-profile HVN                 (price bin holding peak traded volume)

Design note (why in-algorithm, not a parquet precompute): R/S levels MUST be
derived from the same daily bars the strategy trades on. A separately-sourced
artifact reintroduces the parquet-vs-LEAN-zip divergence that produced the
phantom P1 0.392. Single source of truth = the algorithm's own history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# --- tunables (experiments may override) ------------------------------------

WINDOW_52W: int = 252        # trading days ≈ 52 weeks
SWING_WINDOW: int = 60       # lookback for pivot swings
PIVOT_SPAN: int = 3          # bars each side that a pivot must dominate
MIN_TOUCHES: int = 3         # touches to confirm a swing level
TOUCH_TOL: float = 0.015     # ±1.5% band = "same level"
ROUND_STEPS: tuple = (50.0, 100.0, 200.0)
ROUND_BAND: float = 0.25     # round numbers within ±25% of price
HVN_BINS: int = 50           # price bins for volume profile


@dataclass
class Levels:
    """R/S levels for one symbol at one reference bar. Lists are price floats."""
    resistance: list = field(default_factory=list)      # all levels >= ref, ascending
    support: list = field(default_factory=list)         # all levels <= ref, descending
    nearest_resistance: Optional[float] = None
    nearest_support: Optional[float] = None
    by_source: dict = field(default_factory=dict)       # source -> list[float], for diagnostics

    def as_dict(self) -> dict:
        return {
            "resistance": self.resistance,
            "support": self.support,
            "nearest_resistance": self.nearest_resistance,
            "nearest_support": self.nearest_support,
            "by_source": self.by_source,
        }


# --- pivot detection --------------------------------------------------------

def _pivot_high_prices(high: pd.Series, span: int) -> list:
    """Prices of local maxima: bar strictly >= all bars within ±span (excluding edges)."""
    h = high.to_numpy()
    n = len(h)
    out = []
    for i in range(span, n - span):
        window = h[i - span: i + span + 1]
        if h[i] == window.max() and (window.argmax() == span):
            out.append(float(h[i]))
    return out


def _pivot_low_prices(low: pd.Series, span: int) -> list:
    """Prices of local minima: bar <= all bars within ±span."""
    l = low.to_numpy()
    n = len(l)
    out = []
    for i in range(span, n - span):
        window = l[i - span: i + span + 1]
        if l[i] == window.min() and (window.argmin() == span):
            out.append(float(l[i]))
    return out


def _cluster_levels(prices: list, tol: float, min_touches: int) -> list:
    """
    Greedy-cluster nearby pivot prices into confirmed levels. A cluster is a run of
    prices within `tol` (fractional) of the running cluster anchor; clusters with
    >= min_touches members are confirmed and returned as the cluster mean.
    """
    if not prices:
        return []
    ordered = sorted(prices)
    clusters: list[list[float]] = [[ordered[0]]]
    for p in ordered[1:]:
        anchor = clusters[-1][0]
        if abs(p - anchor) <= tol * anchor:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [round(sum(c) / len(c), 4) for c in clusters if len(c) >= min_touches]


# --- individual level sources -----------------------------------------------

def _round_numbers(ref: float, steps: tuple, band: float) -> list:
    """Round-number magnets within ±band of ref, across the given $ grid steps."""
    lo, hi = ref * (1 - band), ref * (1 + band)
    levels = set()
    for step in steps:
        k = int(lo // step)
        while k * step <= hi:
            v = round(k * step, 4)
            if lo <= v <= hi and v > 0:
                levels.add(v)
            k += 1
    return sorted(levels)


def _volume_hvn(df: pd.DataFrame, bins: int) -> Optional[float]:
    """High-volume node: center price of the close-price bin with peak summed volume."""
    if df.empty or df["volume"].sum() <= 0:
        return None
    close = df["close"]
    lo, hi = float(close.min()), float(close.max())
    if hi <= lo:
        return float(lo)
    cut = pd.cut(close, bins=bins)
    vol_by_bin = df["volume"].groupby(cut, observed=False).sum()
    if vol_by_bin.empty or vol_by_bin.max() <= 0:
        return None
    top = vol_by_bin.idxmax()
    return round(float(top.mid), 4)


# --- public API -------------------------------------------------------------

def compute_levels(
    df: pd.DataFrame,
    ref_price: Optional[float] = None,
    senkou_a: Optional[float] = None,
    senkou_b: Optional[float] = None,
    window_52w: int = WINDOW_52W,
    swing_window: int = SWING_WINDOW,
    pivot_span: int = PIVOT_SPAN,
    min_touches: int = MIN_TOUCHES,
    touch_tol: float = TOUCH_TOL,
    round_steps: tuple = ROUND_STEPS,
    round_band: float = ROUND_BAND,
    hvn_bins: int = HVN_BINS,
) -> Levels:
    """
    Compute R/S levels around the latest bar of `df`.

    df: daily OHLCV, ascending DatetimeIndex, columns open/high/low/close/volume.
    ref_price: reference for above/below split; defaults to last close.
    senkou_a/b: optional Ichimoku cloud edges from the caller (classified as R or S).

    Returns a Levels object. Resistance = levels >= ref (ascending);
    support = levels <= ref (descending). Levels within touch_tol of each other
    are de-duplicated. Returns empty lists when no clean level is identifiable.
    """
    if df is None or df.empty:
        return Levels()

    ref = float(ref_price) if ref_price is not None else float(df["close"].iloc[-1])

    by_source: dict[str, list] = {}

    # 52-week horizon
    horizon = df.tail(window_52w)
    by_source["high_52w"] = [round(float(horizon["high"].max()), 4)]
    by_source["low_52w"] = [round(float(horizon["low"].min()), 4)]

    # 60-day confirmed swing pivots
    swing = df.tail(swing_window)
    by_source["swing_high"] = _cluster_levels(
        _pivot_high_prices(swing["high"], pivot_span), touch_tol, min_touches
    )
    by_source["swing_low"] = _cluster_levels(
        _pivot_low_prices(swing["low"], pivot_span), touch_tol, min_touches
    )

    # round numbers
    by_source["round"] = _round_numbers(ref, round_steps, round_band)

    # Ichimoku cloud (passthrough)
    cloud = [v for v in (senkou_a, senkou_b) if v is not None]
    by_source["cloud"] = [round(float(v), 4) for v in cloud]

    # volume profile
    hvn = _volume_hvn(swing, hvn_bins)
    by_source["hvn"] = [hvn] if hvn is not None else []

    # merge → split above/below ref → de-dup within tol
    all_levels = [v for lst in by_source.values() for v in lst if v is not None]
    resistance = _dedup(sorted({v for v in all_levels if v >= ref}), touch_tol)
    support = _dedup(sorted({v for v in all_levels if v <= ref}, reverse=True), touch_tol)

    return Levels(
        resistance=resistance,
        support=support,
        nearest_resistance=resistance[0] if resistance else None,
        nearest_support=support[0] if support else None,
        by_source=by_source,
    )


def _dedup(levels: list, tol: float) -> list:
    """Collapse levels within `tol` (fractional) of the previous kept level."""
    out: list = []
    for v in levels:
        if not out or abs(v - out[-1]) > tol * max(abs(out[-1]), 1e-9):
            out.append(v)
    return out
