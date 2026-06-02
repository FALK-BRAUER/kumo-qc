"""LEAN-faithful indicator ports (#332 warmup-cache) — Ichimoku / ADX / SMA, ported EXACTLY from the
LEAN source (~/reference/Lean, pinned 24afc50db) so a standalone one-pass over daily bars reproduces
what the strategy's live LEAN indicators compute. GATED by byte-identical parity against LEAN's own
golden test data (Tests/TestData/spy_with_ichimoku.csv) + a reference cell — a port that diverges is
the parity trap (a cache that changes trades is worse than no cache), so it does NOT ship un-gated.

Scope: only the scalars the 8-condition `score_symbol_native` reads (the param-free table):
  daily: tenkan, kijun, senkou_a, senkou_b (cloud_top = max(a,b)), price, sma200
  weekly: tenkan, kijun, senkou_a, senkou_b, completed weekly closes (chikou: w_close[0] vs [26])
  adx: adx, +di, -di, adx 3-back (rising)
This module ports the indicator MATH; the table builder (separate) drives it over the bars.
"""
from __future__ import annotations

from collections import deque


class Maximum:
    """LEAN Maximum(period): max over the last `period` samples; ready at `period` samples."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._w: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> None:
        self._w.append(value)

    @property
    def is_ready(self) -> bool:
        return len(self._w) == self.period

    @property
    def value(self) -> float:
        return max(self._w)


class Minimum:
    """LEAN Minimum(period): min over the last `period` samples; ready at `period` samples."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._w: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> None:
        self._w.append(value)

    @property
    def is_ready(self) -> bool:
        return len(self._w) == self.period

    @property
    def value(self) -> float:
        return min(self._w)


class Delay:
    """LEAN Delay(period): the input's value `period` samples ago. Holds period+1 samples; ready when
    full. `value` = the oldest of the period+1 window == the value `period` updates back."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._w: deque[float] = deque(maxlen=period + 1)

    def update(self, value: float) -> None:
        self._w.append(value)

    @property
    def is_ready(self) -> bool:
        return len(self._w) == self.period + 1

    @property
    def value(self) -> float:
        return self._w[0]


class SMA:
    """LEAN SimpleMovingAverage(period): mean of the last `period` samples; ready at `period`."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._w: deque[float] = deque(maxlen=period)

    def update(self, value: float) -> None:
        self._w.append(value)

    @property
    def is_ready(self) -> bool:
        return len(self._w) == self.period

    @property
    def value(self) -> float:
        return sum(self._w) / len(self._w)


class Ichimoku:
    """LEAN IchimokuKinkoHyo port (default 9/26/26/52/26/26). Feed update(high, low, close) per bar.
    Tenkan = (max(H,9)+min(L,9))/2; Kijun = (max(H,26)+min(L,26))/2; SenkouA = ((Tenkan+Kijun)/2)
    delayed 26; SenkouB = ((max(H,52)+min(L,52))/2) delayed 26. `.current.value` of SenkouA/B is the
    DELAYED value (matches LEAN's senkou_a.current.value the strategy reads)."""

    def __init__(self, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52,
                 senkou_a_delay: int = 26, senkou_b_delay: int = 26) -> None:
        self._tmax = Maximum(tenkan_period)
        self._tmin = Minimum(tenkan_period)
        self._kmax = Maximum(kijun_period)
        self._kmin = Minimum(kijun_period)
        self._sbmax = Maximum(senkou_b_period)
        self._sbmin = Minimum(senkou_b_period)
        self._delay_tenkan = Delay(senkou_a_delay)   # Of(Tenkan)
        self._delay_kijun = Delay(senkou_a_delay)     # Of(Kijun)
        self._delay_sbmax = Delay(senkou_b_delay)     # Of(SenkouBMaximum)
        self._delay_sbmin = Delay(senkou_b_delay)     # Of(SenkouBMinimum)
        self.tenkan = float("nan")
        self.kijun = float("nan")
        self.senkou_a = float("nan")
        self.senkou_b = float("nan")
        self.chikou = float("nan")  # = the current close (LEAN Chikou.Update(close))

    def update(self, high: float, low: float, close: float) -> None:
        self._tmax.update(high); self._tmin.update(low)
        self._kmax.update(high); self._kmin.update(low)
        self._sbmax.update(high); self._sbmin.update(low)
        self.chikou = close
        if self._tmax.is_ready and self._tmin.is_ready:
            self.tenkan = (self._tmax.value + self._tmin.value) / 2.0
            self._delay_tenkan.update(self.tenkan)
        if self._kmax.is_ready and self._kmin.is_ready:
            self.kijun = (self._kmax.value + self._kmin.value) / 2.0
            self._delay_kijun.update(self.kijun)
        if self._sbmax.is_ready and self._sbmin.is_ready:
            self._delay_sbmax.update(self._sbmax.value)
            self._delay_sbmin.update(self._sbmin.value)
        if self._delay_tenkan.is_ready and self._delay_kijun.is_ready:
            self.senkou_a = (self._delay_tenkan.value + self._delay_kijun.value) / 2.0
        if self._delay_sbmax.is_ready and self._delay_sbmin.is_ready:
            self.senkou_b = (self._delay_sbmax.value + self._delay_sbmin.value) / 2.0

    @property
    def is_ready(self) -> bool:
        import math
        return not any(math.isnan(v) for v in (self.tenkan, self.kijun, self.senkou_a, self.senkou_b))


class _WilderSmoothed:
    """LEAN's smoothed-TR/DM accumulator: on update i (1-based, Samples=i), value = (i>period+1) ?
    prev/period : 0; current = prev + raw - value. Ready when Samples > period. Seeds as a cumulative
    sum for the first period+1 updates, then Wilder-smooths."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._cur = 0.0
        self._n = 0

    def update(self, raw: float) -> None:
        self._n += 1
        value = (self._cur / self.period) if self._n > self.period + 1 else 0.0
        self._cur = self._cur + raw - value

    @property
    def is_ready(self) -> bool:
        return self._n > self.period

    @property
    def value(self) -> float:
        return self._cur


class _WilderMA:
    """LEAN WilderMovingAverage(period): SMA(period) until ready (Samples>=period), then EWM
    value*k + prev*(1-k), k=1/period. Samples incremented before compute (LEAN ordering)."""
    def __init__(self, period: int) -> None:
        self.period = period
        self._k = 1.0 / period
        self._sma_win: deque[float] = deque(maxlen=period)
        self._cur = float("nan")
        self._n = 0

    def update(self, value: float) -> None:
        self._n += 1
        if self._n < self.period:           # not ready yet → SMA accumulation
            self._sma_win.append(value)
            self._cur = sum(self._sma_win) / len(self._sma_win)
        elif self._n == self.period:        # becomes ready this sample → the seed SMA
            self._sma_win.append(value)
            self._cur = sum(self._sma_win) / self.period
        else:                                # ready → EWM off the prior value
            self._cur = value * self._k + self._cur * (1.0 - self._k)

    @property
    def is_ready(self) -> bool:
        return self._n >= self.period

    @property
    def value(self) -> float:
        return self._cur


class ADX:
    """LEAN AverageDirectionalIndex(period) port. Feed update(high, low, close) per bar. Exposes
    .adx, .plus_di, .minus_di (matches adx.current.value / .positive_directional_index.current.value /
    .negative_directional_index.current.value the strategy reads). Wilder TR/DM smoothing + DX +
    WilderMA-of-DX, ported exactly from AverageDirectionalIndex.cs + WilderMovingAverage.cs."""

    def __init__(self, period: int = 9) -> None:
        self.period = period
        self._prev: tuple[float, float, float] | None = None  # (high, low, close)
        self._str = _WilderSmoothed(period)   # smoothed TrueRange
        self._sdmp = _WilderSmoothed(period)  # smoothed +DM
        self._sdmn = _WilderSmoothed(period)  # smoothed -DM
        self._adx_wma = _WilderMA(period)
        self.plus_di = float("nan")
        self.minus_di = float("nan")
        self.adx = float("nan")

    def update(self, high: float, low: float, close: float) -> None:
        if self._prev is None:
            tr = dmp = dmn = 0.0
        else:
            ph, pl, pc = self._prev
            tr = max(high - low, abs(high - pc), abs(low - pc))
            up_move = high - ph
            down_move = pl - low
            dmp = up_move if (high > ph and up_move >= down_move) else 0.0
            dmn = down_move if (pl > low and down_move > up_move) else 0.0
        self._str.update(tr); self._sdmp.update(dmp); self._sdmn.update(dmn)
        self._prev = (high, low, close)
        if self._str.is_ready and self._str.value != 0:
            if self._sdmp.is_ready:
                self.plus_di = 100.0 * self._sdmp.value / self._str.value
            if self._sdmn.is_ready:
                self.minus_di = 100.0 * self._sdmn.value / self._str.value
        import math
        if not (math.isnan(self.plus_di) or math.isnan(self.minus_di)):
            diff = abs(self.plus_di - self.minus_di)
            s = self.plus_di + self.minus_di
            dx = 50.0 if s == 0 else 100.0 * diff / s
            self._adx_wma.update(dx)
            self.adx = self._adx_wma.value

    @property
    def is_ready(self) -> bool:
        import math
        return not math.isnan(self.adx) and self._adx_wma.is_ready
