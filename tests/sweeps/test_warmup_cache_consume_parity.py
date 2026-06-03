"""#332 warmup-cache CONSUMPTION decision-neutrality gate (stage 3, HQ-mandated comprehensive).

score_symbol_native (live, UNTOUCHED) and score_symbol_cached (flag-ON cache path) are two copies of
the 8-condition logic. This is the ONLY thing keeping them in sync → it must be COMPREHENSIVE:
all 8 conditions toggled on AND off, the score aggregation, threshold boundaries (==), and
property-based randomized tuples fed to BOTH → identical conditions + score. A future native edit that
isn't mirrored in cached fails here (the drift guard). (Queued post-gate: extract a shared
evaluate_conditions both call — single source of truth — guarded by the end-to-end gate.)
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from phases.shared.oracle_helpers import score_symbol_cached, score_symbol_native  # noqa: E402
from sweeps.warmup_cache.table_builder import SCALAR_FIELDS  # noqa: E402


class _Pt:
    def __init__(self, v): self.current = type("C", (), {"value": v})()


class _FakeIchi:
    def __init__(self, tenkan, kijun, sa, sb):
        self.tenkan, self.kijun = _Pt(tenkan), _Pt(kijun)
        self.senkou_a, self.senkou_b = _Pt(sa), _Pt(sb)
        self.is_ready = True


class _FakeAdx:
    def __init__(self, adx, pdi, mdi):
        self.current = type("C", (), {"value": adx})()
        self.positive_directional_index, self.negative_directional_index = _Pt(pdi), _Pt(mdi)
        self.is_ready = True


class _FakeWindow:
    """adx_window / w_close: indexable [i] = i-back; .count for readiness."""
    def __init__(self, mapping: dict[int, float], count: int):
        self._m, self.count = mapping, count

    def __getitem__(self, i): return self._m[i]


class _FakeAlgo:
    def __init__(self, price): self.securities = {"X": type("S", (), {"price": price})()}


def _fake_ind_and_algo(s: dict[str, float]):
    """Build a synthetic (algorithm, ind) that makes score_symbol_native read EXACTLY the scalars in
    s — so its output must equal score_symbol_cached(s) for identical values."""
    d_ichi = _FakeIchi(s["d_tenkan"], 0.0, s["d_cloud_top"], s["d_cloud_top"] - 1.0)  # max=d_cloud_top
    w_ichi = _FakeIchi(s["w_tenkan"], s["w_kijun"], s["w_senkou_a"], s["w_senkou_b"])
    ind = {
        "d_ichi": d_ichi, "w_ichi": w_ichi,
        "w_close": _FakeWindow({0: s["w_close_0"], 26: s["w_close_26"]}, count=27),
        "sma200": _Pt(s["ma200"]), "sma200_": None,
        "adx": _FakeAdx(s["adx_now"], s["plus_di"], s["minus_di"]),
        "adx_window": _FakeWindow({0: s["adx_now"], 3: s["adx_3back"]}, count=4),
        "roc13": type("R", (), {"is_ready": True})(),
    }
    # sma200 needs .is_ready; _Pt has only .current — patch is_ready on the sma200 entry
    ind["sma200"].is_ready = True
    return _FakeAlgo(s["d_price"]), ind


def _both(s: dict[str, float]):
    algo, ind = _fake_ind_and_algo(s)
    native = score_symbol_native(algo, "X", ind)
    cached = score_symbol_cached(s)
    return native, cached


def _all_pass() -> dict[str, float]:
    # every condition TRUE: price above everything, weekly tenkan>kijun, chikou rising, cloud green,
    # adx rising + +DI>-DI + adx>=20.
    return {
        "d_price": 100.0, "d_tenkan": 90.0, "d_cloud_top": 88.0, "ma200": 80.0,
        "w_tenkan": 70.0, "w_kijun": 60.0, "w_senkou_a": 55.0, "w_senkou_b": 50.0,
        "w_close_0": 65.0, "w_close_26": 40.0,
        "adx_now": 30.0, "plus_di": 25.0, "minus_di": 10.0, "adx_3back": 22.0,
    }


def test_all_conditions_pass_score_8() -> None:
    native, cached = _both(_all_pass())
    assert cached["score"] == 8 and native["score"] == 8
    assert cached["conditions"] == native["conditions"] == [True] * 8


def test_each_condition_toggled_off_matches_native() -> None:
    """Flip each of the 8 conditions OFF individually (score→7, exactly one False) — native + cached
    must agree on WHICH condition is False. Catches a flipped/dropped condition in either copy."""
    breakers = {
        0: {"w_senkou_a": 120.0},                      # 1: w_cloud_top=max(120,50)=120 > price(100); cond4 stays True(120>50)
        1: {"w_kijun": 80.0},                          # 2: w_tenkan(70) < w_kijun(80)
        2: {"w_close_26": 70.0},                       # 3: w_close_0(65) < w_close_26(70)
        3: {"w_senkou_a": 40.0},                        # 4: w_sa(40) < w_sb(50) → cloud not green
        4: {"d_cloud_top": 120.0},                     # 5: d_price(100) < d_cloud_top(120)
        5: {"d_tenkan": 120.0},                        # 6: d_price(100) < d_tenkan(120)
        6: {"adx_3back": 35.0},                         # 7: adx_now(30) < adx_3back(35) → not rising
        7: {"ma200": 120.0},                           # 8: d_price(100) < ma200(120)
    }
    for idx, patch in breakers.items():
        s = _all_pass() | patch
        native, cached = _both(s)
        assert cached["conditions"] == native["conditions"], f"cond {idx+1}: {cached} vs {native}"
        assert cached["conditions"][idx] is False
        assert cached["score"] == native["score"] == 7


def test_aggregation_thresholds() -> None:
    """Rating bands + score count match native across the boundary (8/+++, 6-7/++, 4-5/+, 2-3/=)."""
    # break conditions 1..k to land on each score, assert rating agreement
    order = [{"d_price": 50.0}, {"w_kijun": 80.0}, {"w_close_26": 70.0}, {"w_senkou_a": 40.0}]
    s = _all_pass()
    for patch in order:
        s = s | patch
        native, cached = _both(s)
        assert cached["score"] == native["score"]
        assert cached["rating"] == native["rating"]


def test_boundary_equality_is_false_both() -> None:
    """Each condition uses strict > — a value EXACTLY at the threshold → False, identically in both
    (the threshold-function flip risk HQ flagged)."""
    for patch in (
        {"d_tenkan": 100.0},        # d_price == d_tenkan → cond6 False
        {"ma200": 100.0},           # d_price == ma200 → cond8 False
        {"w_kijun": 70.0},          # w_tenkan == w_kijun → cond2 False
        {"adx_3back": 30.0},        # adx_now == adx_3back → not rising → cond7 False
        {"adx_now": 20.0, "adx_3back": 19.0},  # adx_now == 20 exactly → cond7 uses >=20 → TRUE
    ):
        s = _all_pass() | patch
        native, cached = _both(s)
        assert cached["conditions"] == native["conditions"], f"{patch}: {cached} vs {native}"
        assert cached["score"] == native["score"]


def test_property_random_tuples_identical() -> None:
    """1000 randomized scalar tuples → score_symbol_cached(s) conditions+score IDENTICAL to
    score_symbol_native(fake_ind(s)). The strongest drift guard (HQ)."""
    rng = random.Random(20260603)  # fixed seed → deterministic, no Math.random reliance
    for _ in range(1000):
        # positive prices (real data is >0; native guards d_price<=0→None, which the cache never sees
        # since the builder only emits real bars). Tight band so conditions land on BOTH sides often.
        s = {f: rng.uniform(1.0, 150.0) for f in SCALAR_FIELDS}
        native, cached = _both(s)
        assert cached["conditions"] == native["conditions"], f"DRIFT on {s}: {cached} vs {native}"
        assert cached["score"] == native["score"]
        assert cached["rating"] == native["rating"]
