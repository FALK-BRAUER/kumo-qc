"""#228 METHODOLOGY GOLDEN-MASTER for the SIGNAL/QUALIFY phase.

This is the NEW #228 contribution on top of the existing condition-logic tests
(tests/phases/shared/test_score_symbol_native.py): an EXPLICIT methodology-anchored
golden-master. Each fixture encodes a KNOWN methodology qualify decision (the CLAUDE.md
"BCT Signal Stack" 8-condition Blue Flag checklist + its rating bands) as a hand-specified
indicator state, then asserts score_symbol_native reproduces that decision — score, rating,
AND the exact per-condition boolean vector.

GOLDEN-MASTER DISCIPLINE (charter: RAW-own-merits): these fixtures assert LOGIC CORRECTNESS
on identical hand-computed bars — the scorer's 8 conditions == the methodology's 8 conditions.
They are NOT champion-number matching and carry NO universe/fixed-snapshot assumption. If this
file ever fails, the scorer DIVERGED from the methodology — STOP + FLAG for HQ; do NOT edit the
scorer to make it pass (oracle_helpers is DO-NOT-MODIFY, champion-parity-gated).

The 8 methodology conditions, in scorer order (score_symbol_native L173-182):
  C1 weekly price above cloud        -> d_price  > w_cloud_top   (live price vs completed wkly cloud)
  C2 weekly Tenkan > Kijun           -> w_tenkan > w_kijun
  C3 weekly Chikou > price 26 ago    -> w_close[0] > w_close[26] (completed close-vs-close)
  C4 weekly cloud GREEN              -> w_sa > w_sb
  C5 daily price above cloud         -> d_price  > d_cloud_top
  C6 daily price above Tenkan        -> d_price  > d_tenkan
  C7 ADX(9) rising + +DI>-DI + >=20  -> adx_window[0]>adx_window[3] AND +DI>-DI AND adx>=20
  C8 price above 200-day MA          -> d_price  > ma200
Rating bands: 8 -> "+++"; 6-7 -> "++"; 4-5 -> "+"; 2-3 -> "="; 0-1 -> "--".
"""
from __future__ import annotations

from typing import Any

import pytest

from phases.shared.oracle_helpers import score_symbol_native

# ---------------------------------------------------------------------------------------------
# Minimal QC-shaped fakes (the exact accessors score_symbol_native reads). Kept self-contained
# in this file so the methodology golden-master does not couple to another test module.
# ---------------------------------------------------------------------------------------------


class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    def __init__(self, tenkan: float, kijun: float, sa: float, sb: float) -> None:
        self.tenkan = _Ind(tenkan)
        self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa)
        self.senkou_b = _Ind(sb)
        self.is_ready = True


class _Adx:
    def __init__(self, adx: float, pdi: float, ndi: float) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _Ind(pdi)
        self.negative_directional_index = _Ind(ndi)
        self.is_ready = True


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


# ---------------------------------------------------------------------------------------------
# A methodology-anchored ALL-PASS reference state at LIVE PRICE = 100. Every condition is set
# with a clear margin so that toggling exactly one component flips exactly one condition. This
# is the canonical 8/8 "+++" fixture; the per-condition fixtures below derive from it.
# ---------------------------------------------------------------------------------------------

_PRICE = 100.0


def _all_pass() -> dict[str, Any]:
    return {
        # daily: cloud top 85 < 100 (C5), tenkan 90 < 100 (C6)
        "d_ichi": _Ichi(tenkan=90.0, kijun=88.0, sa=85.0, sb=80.0),
        # weekly: cloud top 75 < 100 (C1), tenkan 70 > kijun 60 (C2), green sa75 > sb65 (C4)
        "w_ichi": _Ichi(tenkan=70.0, kijun=60.0, sa=75.0, sb=65.0),
        # weekly chikou: now 90 > 26-ago 50 (C3); >=27 entries
        "w_close": _Window([90.0] + [50.0] * 26),
        "sma200": _Ind(50.0),  # 100 > 50 (C8)
        "adx": _Adx(adx=25.0, pdi=30.0, ndi=10.0),  # >=20, +DI>-DI (C7)
        "adx_window": _Window([25.0, 24.0, 23.0, 22.0]),  # [0]>[3] -> rising (C7)
        "roc13": _Ind(0.10),  # readiness only; not a scoring condition
    }


def _score(ind: dict[str, Any]) -> dict[str, Any]:
    r = score_symbol_native(_QC(_PRICE), "SYM", ind)
    assert r is not None
    return r


def _rating_for(score: int) -> str:
    if score == 8:
        return "+++"
    if score >= 6:
        return "++"
    if score >= 4:
        return "+"
    if score >= 2:
        return "="
    return "--"


# ---------------------------------------------------------------------------------------------
# GOLD 1 — the 8/8 "+++" reference: every methodology condition true.
# ---------------------------------------------------------------------------------------------


def test_golden_8_of_8_plusplusplus() -> None:
    r = _score(_all_pass())
    assert r["conditions"] == [True] * 8
    assert r["score"] == 8
    assert r["rating"] == "+++"


# ---------------------------------------------------------------------------------------------
# GOLD 2 — EACH-CONDITION-FAILED: a parametrised table. For each of the 8 methodology
# conditions, mutate exactly the indicator that drives it so ONLY that condition flips False;
# assert the conditions vector has exactly that index False and score == 7, rating "++".
# This is the methodology<->code mapping, asserted condition by condition.
# ---------------------------------------------------------------------------------------------

# (index, human label, override that flips ONLY conditions[index] to False)
_FAIL_ONE: list[tuple[int, str, dict[str, Any]]] = [
    (0, "C1 weekly price above cloud", {"w_ichi": _Ichi(70.0, 60.0, 120.0, 110.0)}),  # cloud top 120>100
    (1, "C2 weekly tenkan>kijun", {"w_ichi": _Ichi(55.0, 60.0, 75.0, 65.0)}),  # tenkan<kijun; cloud 75<100 keeps C1
    (2, "C3 weekly chikou", {"w_close": _Window([40.0] + [50.0] * 26)}),  # now 40 < 26ago 50
    (3, "C4 weekly cloud green", {"w_ichi": _Ichi(70.0, 60.0, 65.0, 75.0)}),  # sa<sb; cloud top 75<100 keeps C1
    (4, "C5 daily price above cloud", {"d_ichi": _Ichi(90.0, 88.0, 105.0, 80.0)}),  # cloud top 105>100
    (5, "C6 daily price above tenkan", {"d_ichi": _Ichi(110.0, 88.0, 85.0, 80.0)}),  # tenkan 110>100; cloud 85<100 keeps C5
    (6, "C7 ADX(9) rising+DI+>=20", {"adx": _Adx(19.9, 30.0, 10.0)}),  # adx<20
    (7, "C8 price above 200MA", {"sma200": _Ind(120.0)}),  # ma200 120>100
]


@pytest.mark.parametrize("idx,label,override", _FAIL_ONE, ids=[f[1] for f in _FAIL_ONE])
def test_golden_each_condition_failed_is_7(idx: int, label: str, override: dict[str, Any]) -> None:
    ind = _all_pass()
    ind.update(override)
    r = _score(ind)
    expected = [True] * 8
    expected[idx] = False
    assert r["conditions"] == expected, f"{label}: only conditions[{idx}] should flip False"
    assert r["score"] == 7
    assert r["rating"] == "++"


# ---------------------------------------------------------------------------------------------
# GOLD 3 — the C7 ADX three-part rule, broken out: each of the three sub-clauses
# (rising / +DI>-DI / >=20) must independently drop C7. The methodology states all three.
# ---------------------------------------------------------------------------------------------

_C7_BREAKS: list[tuple[str, dict[str, Any]]] = [
    ("adx below 20", {"adx": _Adx(19.9, 30.0, 10.0)}),
    ("+DI <= -DI", {"adx": _Adx(25.0, 10.0, 30.0)}),
    ("not rising ([0]<=[3])", {"adx_window": _Window([22.0, 23.0, 24.0, 25.0])}),
]


@pytest.mark.parametrize("label,override", _C7_BREAKS, ids=[b[0] for b in _C7_BREAKS])
def test_golden_c7_three_part_rule(label: str, override: dict[str, Any]) -> None:
    ind = _all_pass()
    ind.update(override)
    r = _score(ind)
    assert r["conditions"][6] is False, f"C7 must fail when: {label}"
    assert r["score"] == 7


# ---------------------------------------------------------------------------------------------
# GOLD 4 — the 6/8 "++" band edge: two conditions fail, rating stays "++" (band 6-7).
# ---------------------------------------------------------------------------------------------


def test_golden_6_of_8_is_plusplus() -> None:
    ind = _all_pass()
    ind.update({"w_ichi": _Ichi(70.0, 60.0, 120.0, 110.0), "sma200": _Ind(120.0)})  # C1 + C8 fail
    r = _score(ind)
    assert r["score"] == 6
    assert r["rating"] == "++"


# ---------------------------------------------------------------------------------------------
# GOLD 5 — the rating-band boundaries, as a table over score -> rating. We drive a target score
# by failing a chosen set of conditions and assert the rating band the methodology specifies.
# (5 fails C1,C2,C8 -> 5 "+"; 3 fails C1,C2,C4,C8,C5 -> 3 "="; 1 fails 7 -> 1 "--".)
# ---------------------------------------------------------------------------------------------

# An ordered set of single-condition overrides we can stack to drive the score down precisely.
_DOWN: dict[int, dict[str, Any]] = {
    0: {"w_ichi_c1": True},  # placeholder, replaced below — we compose explicitly per case
}


def _compose(fail_indices: set[int]) -> dict[str, Any]:
    """Build an indicator state that fails exactly `fail_indices` (a subset of 0..7).

    Uses non-overlapping indicators per condition so failures compose cleanly. C1 and C5/C6 both
    key on weekly/daily cloud-vs-price; to fail several at once without cross-talk we drive each
    via its own indicator and keep the others passing.
    """
    ind = _all_pass()
    # Each entry sets ONLY its condition False; indicators are disjoint enough to stack.
    if 7 in fail_indices:
        ind["sma200"] = _Ind(120.0)  # C8
    if 6 in fail_indices:
        ind["adx"] = _Adx(19.9, 30.0, 10.0)  # C7
    if 2 in fail_indices:
        ind["w_close"] = _Window([40.0] + [50.0] * 26)  # C3
    if 5 in fail_indices:
        ind["d_ichi"] = _Ichi(110.0, 88.0, 85.0, 80.0)  # C6 (tenkan>price), cloud 85<100 keeps C5
    if 4 in fail_indices and 5 not in fail_indices:
        ind["d_ichi"] = _Ichi(90.0, 88.0, 105.0, 80.0)  # C5 only
    # weekly C1/C2/C4 via the weekly ichi — choose the variant that fails the requested subset.
    wk = {1, 2, 4} & fail_indices  # note: index 0 is C1, 1 is C2, 3 is C4
    # Re-map to actual indices: C1=0, C2=1, C4=3.
    w_fail = {i for i in (0, 1, 3) if i in fail_indices}
    if w_fail == {0}:
        ind["w_ichi"] = _Ichi(70.0, 60.0, 120.0, 110.0)  # C1 fail
    elif w_fail == {1}:
        ind["w_ichi"] = _Ichi(55.0, 60.0, 75.0, 65.0)  # C2 fail
    elif w_fail == {3}:
        ind["w_ichi"] = _Ichi(70.0, 60.0, 65.0, 75.0)  # C4 fail
    elif w_fail == {0, 1}:
        ind["w_ichi"] = _Ichi(55.0, 60.0, 120.0, 110.0)  # C1+C2: tenkan<kijun AND cloud>price
    elif w_fail == {0, 1, 3}:
        ind["w_ichi"] = _Ichi(55.0, 60.0, 110.0, 120.0)  # C1 (top120>100), C2 (55<60), C4 (110<120)
    _ = wk  # silence unused (kept for readability of intent)
    return ind


_BAND_CASES: list[tuple[set[int], int, str]] = [
    ({0, 1, 7}, 5, "+"),  # 3 fail -> 5/8 -> "+"
    ({0, 1, 3, 7, 2}, 3, "="),  # 5 fail -> 3/8 -> "="
    ({0, 1, 3, 2, 5, 6, 7}, 1, "--"),  # 7 fail -> 1/8 -> "--"
]


@pytest.mark.parametrize(
    "fails,exp_score,exp_rating", _BAND_CASES, ids=[f"{c[1]}->{c[2]}" for c in _BAND_CASES]
)
def test_golden_rating_bands(fails: set[int], exp_score: int, exp_rating: str) -> None:
    r = _score(_compose(fails))
    failed = {i for i, c in enumerate(r["conditions"]) if c is False}
    assert failed == fails, f"composed wrong failure set: got {failed}, want {fails}"
    assert r["score"] == exp_score
    assert r["rating"] == exp_rating
    assert r["rating"] == _rating_for(r["score"])  # cross-check against the band function


# ---------------------------------------------------------------------------------------------
# GOLD 6 — DETERMINISM: the same indicator state scored repeatedly yields byte-identical results
# (no hidden state, no ordering nondeterminism). Required by the #228 DoD.
# ---------------------------------------------------------------------------------------------


def test_golden_determinism() -> None:
    ind = _all_pass()
    first = _score(ind)
    for _ in range(50):
        again = score_symbol_native(_QC(_PRICE), "SYM", ind)
        assert again == first


# ---------------------------------------------------------------------------------------------
# GOLD 7 — rating function consistency over the full 0..8 score range (the band contract).
# ---------------------------------------------------------------------------------------------


def test_rating_band_contract_full_range() -> None:
    assert [_rating_for(s) for s in range(9)] == [
        "--", "--",  # 0,1
        "=", "=",  # 2,3
        "+", "+",  # 4,5
        "++", "++",  # 6,7
        "+++",  # 8
    ]
