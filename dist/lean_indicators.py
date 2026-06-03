from __future__ import annotations

import datetime as _dt
from collections import deque


class Maximum:
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

    def __init__(self, tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52,
                 senkou_a_delay: int = 26, senkou_b_delay: int = 26) -> None:
        self._tmax = Maximum(tenkan_period)
        self._tmin = Minimum(tenkan_period)
        self._kmax = Maximum(kijun_period)
        self._kmin = Minimum(kijun_period)
        self._sbmax = Maximum(senkou_b_period)
        self._sbmin = Minimum(senkou_b_period)
        self._delay_tenkan = Delay(senkou_a_delay)
        self._delay_kijun = Delay(senkou_a_delay)
        self._delay_sbmax = Delay(senkou_b_delay)
        self._delay_sbmin = Delay(senkou_b_delay)
        self.tenkan = float("nan")
        self.kijun = float("nan")
        self.senkou_a = float("nan")
        self.senkou_b = float("nan")
        self.chikou = float("nan")

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
    def __init__(self, period: int) -> None:
        self.period = period
        self._k = 1.0 / period
        self._sma_win: deque[float] = deque(maxlen=period)
        self._cur = float("nan")
        self._n = 0

    def update(self, value: float) -> None:
        self._n += 1
        if self._n < self.period:
            self._sma_win.append(value)
            self._cur = sum(self._sma_win) / len(self._sma_win)
        elif self._n == self.period:
            self._sma_win.append(value)
            self._cur = sum(self._sma_win) / self.period
        else:
            self._cur = value * self._k + self._cur * (1.0 - self._k)

    @property
    def is_ready(self) -> bool:
        return self._n >= self.period

    @property
    def value(self) -> float:
        return self._cur


class ADX:

    def __init__(self, period: int = 9) -> None:
        self.period = period
        self._prev: tuple[float, float, float] | None = None
        self._str = _WilderSmoothed(period)
        self._sdmp = _WilderSmoothed(period)
        self._sdmn = _WilderSmoothed(period)
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


def monday_of_week(d: _dt.date) -> _dt.date:
    return d - _dt.timedelta(days=d.weekday())


class WeeklyIchimokuAsOf:

    def __init__(self) -> None:
        self._w_ichi = Ichimoku()
        self._w_close: deque[float] = deque(maxlen=64)
        self._cur_monday: _dt.date | None = None
        self._cur: dict[str, float] | None = None

    def _finalize_current_week(self) -> None:
        if self._cur is not None:
            self._w_ichi.update(self._cur["high"], self._cur["low"], self._cur["close"])
            self._w_close.append(self._cur["close"])
            self._cur = None

    def update(self, d: _dt.date, open_: float, high: float, low: float, close: float) -> None:
        mt = monday_of_week(d)
        if self._cur_monday is None:
            self._cur_monday = mt
        elif mt > self._cur_monday:
            self._finalize_current_week()
            self._cur_monday = mt
        if self._cur is None:
            self._cur = {"open": open_, "high": high, "low": low, "close": close}
        else:
            self._cur["high"] = max(self._cur["high"], high)
            self._cur["low"] = min(self._cur["low"], low)
            self._cur["close"] = close

    @property
    def is_ready(self) -> bool:
        return self._w_ichi.is_ready and len(self._w_close) >= 27

    @property
    def tenkan(self) -> float:
        return self._w_ichi.tenkan

    @property
    def kijun(self) -> float:
        return self._w_ichi.kijun

    @property
    def senkou_a(self) -> float:
        return self._w_ichi.senkou_a

    @property
    def senkou_b(self) -> float:
        return self._w_ichi.senkou_b

    @property
    def cloud_top(self) -> float:
        return max(self._w_ichi.senkou_a, self._w_ichi.senkou_b)

    def w_close(self, back: int) -> float:
        return self._w_close[-1 - back]

    @property
    def completed_weeks(self) -> int:
        return len(self._w_close)


class RateOfChange:
    def __init__(self, period: int) -> None:
        self.period = period
        self._w: deque[float] = deque(maxlen=period + 1)
        self.value = float("nan")

    def update(self, close: float) -> None:
        self._w.append(close)
        if len(self._w) == self.period + 1:
            denom = self._w[0]
            self.value = 0.0 if denom == 0 else (self._w[-1] - denom) / denom

    @property
    def is_ready(self) -> bool:
        return len(self._w) == self.period + 1
