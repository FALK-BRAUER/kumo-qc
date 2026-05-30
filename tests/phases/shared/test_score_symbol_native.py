"""Golden-master + condition-logic tests for score_symbol_native (#213f).

score_symbol_native reads MAINTAINED indicators (zero per-bar history). These tests verify
the 8-condition logic + rating against hand-computed expectations over a broad set of value
combinations, and the readiness guards. Fake indicators expose the exact QC accessors
(.current.value / .is_ready / .positive_directional_index / RollingWindow [i] + .count).

The QC-native-value == pandas-value equivalence (e.g. QC IchimokuKinkoHyo == _mid) is the
INTEGRATION check (longer local run); here we prove the maintained-read condition LOGIC is
correct + matches score_symbol's boolean expressions on equal values, isolating the
intentional weekly asymmetry (conds 1 live-price, 3 completed-close).
"""
from __future__ import annotations

from typing import Any

from phases.shared.oracle_helpers import score_symbol_native


class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, tenkan: float, kijun: float, sa: float, sb: float, ready: bool = True) -> None:
        self.tenkan = _Ind(tenkan); self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa); self.senkou_b = _Ind(sb)
        self.is_ready = ready


class _Adx:
    def __init__(self, adx: float, pdi: float, ndi: float, ready: bool = True) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _Ind(pdi)
        self.negative_directional_index = _Ind(ndi)
        self.is_ready = ready


class _Window:
    def __init__(self, vals: list[float]) -> None:
        self._v = vals  # index 0 = most recent
    def __getitem__(self, i: int) -> float:
        return self._v[i]
    @property
    def count(self) -> int:
        return len(self._v)


class _Sec:
    def __init__(self, price: float) -> None:
        self.price = price


class _QC:
    def __init__(self, price: float) -> None:
        self.securities = {"SYM": _Sec(price)}


def _ind(*, d=( "T","K","SA","SB"), **over: Any) -> dict[str, Any]:
    """All-pass-by-default maintained indicator set; override per test to toggle a condition."""
    base: dict[str, Any] = {
        # daily ichimoku: tenkan below price, cloud below price (conds 5,6 pass at price=100)
        "d_ichi": _Ichi(tenkan=90.0, kijun=88.0, sa=85.0, sb=80.0),
        # weekly ichimoku: tenkan>kijun (2), green sa>sb (4), cloud below price (1)
        "w_ichi": _Ichi(tenkan=70.0, kijun=60.0, sa=75.0, sb=65.0),
        # weekly closes: [0]=now 90 > [26]=50 (cond 3 chikou pass); >=27 entries
        "w_close": _Window([90.0] + [50.0] * 26),
        "sma200": _Ind(50.0),                  # price 100 > 50 (cond 8)
        "adx": _Adx(adx=25.0, pdi=30.0, ndi=10.0),  # >=20, +DI>-DI (cond 7, with rising)
        "adx_window": _Window([25.0, 24.0, 23.0, 22.0]),  # [0]=25 > [3]=22 → rising
        "roc13": _Ind(0.10),                   # not used by score; readiness only
    }
    base.update(over)
    return base


def _score(price: float, ind: dict[str, Any]):
    return score_symbol_native(_QC(price), "SYM", ind)


def test_all_eight_pass_is_score_8_plusplusplus():
    r = _score(100.0, _ind())
    assert r is not None
    assert r["score"] == 8
    assert r["rating"] == "+++"
    assert r["conditions"] == [True] * 8


def test_condition_1_weekly_cloud_live_price():
    # price below weekly cloud top → cond 1 False. (LIVE price vs completed weekly cloud.)
    ind = _ind(w_ichi=_Ichi(tenkan=70, kijun=60, sa=120, sb=110))  # cloud top 120 > price 100
    r = _score(100.0, ind)
    assert r["conditions"][0] is False
    assert r["score"] == 7


def test_condition_2_weekly_tenkan_kijun():
    # w_tenkan <= w_kijun → cond 2 False.
    assert _score(100.0, _ind(w_ichi=_Ichi(tenkan=55, kijun=60, sa=75, sb=65)))["conditions"][1] is False


def test_condition_4_weekly_cloud_green():
    # senkou_a <= senkou_b → cond 4 False (cloud not green); cloud top still below price so cond1 stays True.
    assert _score(100.0, _ind(w_ichi=_Ichi(tenkan=70, kijun=60, sa=65, sb=75)))["conditions"][3] is False


def test_condition_3_chikou_completed_close():
    # w_close[0] (now) <= w_close[26] → cond 3 False. Close-vs-close, completed weeks.
    ind = _ind(w_close=_Window([40.0] + [50.0] * 26))  # now 40 < 26ago 50
    assert _score(100.0, ind)["conditions"][2] is False


def test_condition_7_adx_three_parts():
    # adx<20 fails; +DI<=-DI fails; not rising fails. Each independently.
    assert _score(100.0, _ind(adx=_Adx(19.9, 30, 10)))["conditions"][6] is False   # adx<20
    assert _score(100.0, _ind(adx=_Adx(25, 10, 30)))["conditions"][6] is False     # +DI<-DI
    assert _score(100.0, _ind(adx_window=_Window([22, 23, 24, 25])))["conditions"][6] is False  # not rising ([0]<[3])


def test_conditions_5_6_8_daily_use_live_price():
    # daily-above-cloud(5), daily-above-tenkan(6), above-200MA(8): all keyed on LIVE d_price.
    assert _score(100.0, _ind(d_ichi=_Ichi(90, 88, 105, 80)))["conditions"][4] is False  # cloud top 105>100
    assert _score(100.0, _ind(d_ichi=_Ichi(110, 88, 85, 80)))["conditions"][5] is False  # tenkan 110>100
    assert _score(100.0, _ind(sma200=_Ind(120.0)))["conditions"][7] is False             # ma200 120>100


def test_rating_thresholds():
    # 6 conds → "++"; force 2 to fail (cond1 cloud + cond8 ma200).
    ind = _ind(w_ichi=_Ichi(70, 60, 120, 110), sma200=_Ind(120.0))
    r = _score(100.0, ind)
    assert r["score"] == 6 and r["rating"] == "++"


def test_not_ready_returns_none():
    assert _score(100.0, _ind(d_ichi=_Ichi(90, 88, 85, 80, ready=False))) is None
    assert _score(100.0, _ind(adx=_Adx(25, 30, 10, ready=False))) is None


def test_insufficient_window_returns_none():
    assert _score(100.0, _ind(w_close=_Window([90.0] + [50.0] * 10))) is None   # <27
    assert _score(100.0, _ind(adx_window=_Window([25.0, 24.0]))) is None        # <4


def test_nonpositive_price_returns_none():
    assert _score(0.0, _ind()) is None
