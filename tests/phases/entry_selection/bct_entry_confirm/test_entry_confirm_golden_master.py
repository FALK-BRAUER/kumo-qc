"""#253 METHODOLOGY GOLDEN-MASTER for the ENTRY-CONFIRMATION phase (§4 Gate 2 + §2 C1-C4).

The methodology anchor for `BctEntryConfirm` after the HQ #253-P1 rulings. Each fixture encodes a
KNOWN §4 Gate-2 decision (the GH#253 authoritative comment + the 5 ruled flags) as a hand-spec
float state — INCLUDING the daily OHLC bar C2 now reads — and asserts the PURE scorer
`evaluate_gate2` reproduces it (exact per-component pass/fail AND the X/4 count).

GOLDEN-MASTER DISCIPLINE (charter: RAW-own-merits): assert LOGIC CORRECTNESS on identical
hand-computed inputs — the coded components == the methodology's §2 components. NOT champion-number
matching. If this file fails, the gate DIVERGED from the methodology — STOP + FLAG for HQ.

The 4 components (HQ-ruled, C2 reads the DAILY OHLC bar):
  C1 Regime    live price > daily cloud top AND Tenkan > Kijun
  C2 T-Bounce  was-above(sessions<=3) AND pullback(daily_low<=Tenkan OR within tol ABOVE) AND
               bounce(close>open OR lower_wick>=0.5*range) AND T>K AND not-in-cloud AND
               not-degraded(Tenkan-flat |T/K-1|<=flat_eps OR T<K / gap-up>thr)
  C3 MACD      hist>=0 (positive OR FLAT) OR (hist<0 AND turning-up) -> confirm; else NO
  C4 Volume    volume >= volume_gate_mult x vol_avg20  (gate = 1.0x)
Qualify rule: score >= min_confirm AND C1 AND C4 (regime + volume mandatory).
"""
from __future__ import annotations

from typing import Any

import pytest

from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import (
    ComponentScore,
    evaluate_gate2,
)

# ---------------------------------------------------------------------------------------------
# A methodology-anchored ALL-CONFIRM reference (4/4). Live price=100; the DAILY bar pulls back to
# the Tenkan and closes back up. Margins set so toggling one input flips one component.
#   C1: cloud top 90 < 100, tenkan 99.7 > kijun 95  -> regime BULL
#   C2: daily LOW 99.5 <= tenkan 99.7 (pullback touch); bullish close (close 100>open 99.6 -> bounce);
#       T 99.7 > K 95; live price 100 not in cloud (80..90); sessions_below 0; gap 0;
#       tenkan-flat? |99.7/95-1|=4.9% > flat_eps 0.2% -> not flat.
#   C3: hist now 0.5 >= 0 (positive) -> confirm
#   C4: volume 200k >= 1.0 x avg 100k
# ---------------------------------------------------------------------------------------------

_BASE: dict[str, Any] = dict(
    price=100.0,
    daily_open=99.6,
    daily_high=100.2,
    daily_low=99.5,
    daily_close=100.0,
    d_tenkan=99.7,
    d_kijun=95.0,
    d_cloud_top=90.0,
    d_cloud_bottom=80.0,
    macd_hist_now=0.5,
    macd_hist_prev=0.2,
    volume=200_000.0,
    vol_avg20=100_000.0,
    sessions_below_tenkan=0,
    gap_up_frac=0.0,
    tenkan_pullback_tol=0.005,
    flat_eps=0.002,
    volume_gate_mult=1.0,
    gap_up_threshold=0.01,
)


def _score(**overrides: Any) -> ComponentScore:
    kw = dict(_BASE)
    kw.update(overrides)
    return evaluate_gate2(**kw)


# ---------------------------------------------------------------------------------------------
# GOLD 1 — the 4/4 ALL-CONFIRM reference: every §4 component true.
# ---------------------------------------------------------------------------------------------


def test_golden_4_of_4_all_confirm() -> None:
    cs = _score()
    assert (cs.c1_regime, cs.c2_tbounce, cs.c3_macd, cs.c4_volume) == (True, True, True, True)
    assert cs.score == 4
    assert cs.qualifies(min_confirm=2)
    assert cs.qualifies(min_confirm=4)


# ---------------------------------------------------------------------------------------------
# GOLD 2 — EACH-COMPONENT-FAILED (the independently-isolable ones): C2 / C3 / C4 single-flip.
# C1's T>K leg is SHARED with C2 (see the coupling test below), so C1 is covered there.
# ---------------------------------------------------------------------------------------------

_FAIL_ONE: list[tuple[str, str, dict[str, Any], int]] = [
    # C2: daily low far ABOVE Tenkan (no pullback touch) but T>K kept (so C1 still passes).
    #     low 102 vs tenkan 99.7 -> (102-99.7)/99.7 = 2.3% > 0.5% tol -> no pullback -> C2 fails.
    ("c2_tbounce", "C2 no pullback (low above tol)", {"daily_low": 102.0, "daily_open": 102.1, "daily_close": 102.5, "daily_high": 102.6}, 3),
    # C3: negative AND turning down -> the only failing MACD state.
    ("c3_macd", "C3 neg+turning-down", {"macd_hist_now": -0.5, "macd_hist_prev": -0.2}, 3),
    # C4: below the 1.0x gate.
    ("c4_volume", "C4 below gate", {"volume": 90_000.0}, 3),
]


@pytest.mark.parametrize("attr,label,override,exp_score", _FAIL_ONE, ids=[f[1] for f in _FAIL_ONE])
def test_golden_each_component_failed_is_3(
    attr: str, label: str, override: dict[str, Any], exp_score: int
) -> None:
    cs = _score(**override)
    flags = {
        "c1_regime": cs.c1_regime,
        "c2_tbounce": cs.c2_tbounce,
        "c3_macd": cs.c3_macd,
        "c4_volume": cs.c4_volume,
    }
    assert flags[attr] is False, f"{label}: {attr} should be False"
    assert cs.score == exp_score, f"{label}: expected score {exp_score}, got {cs.score}"
    others = {k: v for k, v in flags.items() if k != attr}
    assert all(others.values()), f"{label}: only {attr} should flip, got {flags}"


def test_golden_c1_regime_fail_couples_c2() -> None:
    # C1's T>K leg is SHARED with C2 (the regime IS C2's precondition). Failing C1 via T<=K ALSO
    # fails C2 (the T>K sub-clause + the Tenkan-flat T<K degrade). Documented coupling.
    cs = _score(d_tenkan=94.0, d_kijun=95.0)
    assert cs.c1_regime is False  # T<K
    assert cs.c2_tbounce is False  # coupled
    assert (cs.c3_macd, cs.c4_volume) == (True, True)
    assert cs.score == 2


# ---------------------------------------------------------------------------------------------
# GOLD 3 — C2 sub-conditions (HQ-ruled, daily-OHLC). Each ANDed clause + each degrade drops C2.
# ---------------------------------------------------------------------------------------------

_C2_BREAKS: list[tuple[str, dict[str, Any]]] = [
    # (a) downtrend: below Tenkan >3 sessions.
    ("(a) below tenkan >3 sessions", {"sessions_below_tenkan": 4}),
    # (b) FLAG 1: daily low too far ABOVE Tenkan (> tol) -> no pullback touch.
    ("(b) no pullback (low > tol above)", {"daily_low": 102.0, "daily_open": 102.1, "daily_close": 102.5, "daily_high": 102.6}),
    # (c) FLAG 5: bearish close AND no lower-wick rejection -> no bounce.
    #     open 100, close 99.5 (bearish); low 99.4 -> lower_wick = min(100,99.5)-99.4 = 0.1;
    #     range = high 100.1 - low 99.4 = 0.7; 0.1 < 0.5*0.7=0.35 -> no wick rejection -> C2 fails.
    ("(c) bearish close, no wick", {"daily_open": 100.0, "daily_close": 99.5, "daily_low": 99.4, "daily_high": 100.1}),
    # (d) T<=K (also a flat degrade, but the T>K clause alone fails C2).
    ("(d) tenkan<=kijun", {"d_kijun": 100.0}),
    # (e) live price inside the cloud.
    ("(e) inside the cloud", {"d_cloud_top": 101.0, "d_cloud_bottom": 99.0}),
    # FLAG 2 degrade: Tenkan flat (within flat_eps of Kijun). kijun 99.6 -> |99.7/99.6-1|=0.1% <= 0.2%.
    ("degrade: tenkan flat (~kijun)", {"d_kijun": 99.6}),
    # FLAG 4 degrade: gap-up over threshold (1%).
    ("degrade: gap-up > threshold", {"gap_up_frac": 0.02}),
]


@pytest.mark.parametrize("label,override", _C2_BREAKS, ids=[b[0] for b in _C2_BREAKS])
def test_golden_c2_subconditions(label: str, override: dict[str, Any]) -> None:
    cs = _score(**override)
    assert cs.c2_tbounce is False, f"C2 must fail when: {label}"


def test_golden_c2_pullback_ceiling_inclusive_and_deeper_better() -> None:
    # FLAG 1: pullback is a CEILING. Daily low exactly tenkan_pullback_tol ABOVE Tenkan -> counts
    # (inclusive). A DEEPER touch (low at/below Tenkan) also counts (never rejected for being closer).
    tenkan = 99.7
    edge_low = tenkan * (1.0 + 0.005)  # exactly 0.5% above
    assert _score(daily_low=edge_low, daily_open=edge_low, daily_close=edge_low + 0.3,
                  daily_high=edge_low + 0.4).c2_tbounce is True  # at the ceiling -> counts
    assert _score(daily_low=98.0).c2_tbounce is True             # deeper touch (low<tenkan) -> counts
    just_over = tenkan * (1.0 + 0.0051)  # just past the ceiling
    assert _score(daily_low=just_over, daily_open=just_over, daily_close=just_over + 0.3,
                  daily_high=just_over + 0.4).c2_tbounce is False


def test_golden_c2_bounce_lower_wick_rejection() -> None:
    # FLAG 5: a bearish close still BOUNCES if the lower wick rejection is >= 0.5*range.
    # open 100, close 99.8 (bearish), low 99.0, high 100.1: lower_wick = min(100,99.8)-99.0 = 0.8;
    # range = 100.1-99.0 = 1.1; 0.8 >= 0.5*1.1=0.55 -> wick rejection -> bounce True.
    # pullback: low 99.0 <= tenkan 99.7 -> touch. So C2 confirms on the wick alone.
    cs = _score(daily_open=100.0, daily_close=99.8, daily_low=99.0, daily_high=100.1)
    assert cs.c2_tbounce is True


# ---------------------------------------------------------------------------------------------
# GOLD 4 — C3 MACD the four states (HQ FLAG 3): positive (up OR flat) and negative-turning-up
# CONFIRM; only negative-turning-down/flat FAILS. (positive-flat + zero-flat now CONFIRM.)
# ---------------------------------------------------------------------------------------------

_C3_STATES: list[tuple[str, float, float, bool]] = [
    ("positive turning up", 0.5, 0.2, True),
    ("positive flat", 0.5, 0.5, True),        # FLAG 3: positive-flat CONFIRMS (was failing)
    ("zero flat", 0.0, 0.0, True),            # FLAG 3: hist==0 CONFIRMS (>= 0)
    ("positive turning down (still >0)", 0.5, 0.8, True),  # still positive -> confirm
    ("negative turning up (divergence)", -0.2, -0.5, True),
    ("negative turning down", -0.5, -0.2, False),
    ("negative flat", -0.5, -0.5, False),     # negative AND not turning up -> fail
]


@pytest.mark.parametrize(
    "label,now,prev,expect", _C3_STATES, ids=[s[0] for s in _C3_STATES]
)
def test_golden_c3_macd_states(label: str, now: float, prev: float, expect: bool) -> None:
    cs = _score(macd_hist_now=now, macd_hist_prev=prev)
    assert cs.c3_macd is expect, f"C3 {label}: expected {expect}"


# ---------------------------------------------------------------------------------------------
# GOLD 5 — C4 volume gate boundary (inclusive at 1.0x) + custom multiple.
# ---------------------------------------------------------------------------------------------


def test_golden_c4_volume_gate_boundary_inclusive() -> None:
    assert _score(volume=100_000.0, vol_avg20=100_000.0).c4_volume is True   # exactly 1.0x
    assert _score(volume=99_999.0, vol_avg20=100_000.0).c4_volume is False   # just under
    assert _score(volume=150_000.0, vol_avg20=100_000.0).c4_volume is True   # 1.5x (strong)


def test_golden_c4_custom_gate_multiple() -> None:
    assert _score(volume=100_000.0, vol_avg20=100_000.0, volume_gate_mult=1.5).c4_volume is False
    assert _score(volume=150_000.0, vol_avg20=100_000.0, volume_gate_mult=1.5).c4_volume is True


# ---------------------------------------------------------------------------------------------
# GOLD 6 — the QUALIFY rule: score >= min_confirm AND regime(C1) AND volume(C4) mandatory.
# ---------------------------------------------------------------------------------------------


def test_golden_qualify_2of4_with_mandatory_passes() -> None:
    # C1 + C4 pass, C2 + C3 fail -> 2/4 with both mandatory -> qualifies at min=2.
    # Daily low far above Tenkan fails C2 (no pullback) while T>K keeps C1; MACD neg-down fails C3.
    cs = _score(
        daily_low=102.0, daily_open=102.1, daily_close=102.5, daily_high=102.6,
        macd_hist_now=-0.5, macd_hist_prev=-0.2,
    )
    assert (cs.c1_regime, cs.c4_volume) == (True, True)
    assert (cs.c2_tbounce, cs.c3_macd) == (False, False)
    assert cs.score == 2
    assert cs.qualifies(min_confirm=2) is True
    assert cs.qualifies(min_confirm=3) is False


def test_golden_qualify_2of4_missing_regime_is_do_not_enter() -> None:
    # live price inside the cloud -> C1 fails (price not > cloud top) AND C2 (in cloud) fails;
    # volume below gate fails C4. Missing both mandatory -> DO NOT ENTER even at min=2.
    cs = _score(d_cloud_top=101.0, d_cloud_bottom=99.5, volume=90_000.0)
    assert cs.c1_regime is False
    assert cs.c4_volume is False
    assert cs.qualifies(min_confirm=2) is False


def test_golden_qualify_missing_volume_is_do_not_enter() -> None:
    # C1 + C2 + C3 pass (3/4) but C4 volume fails -> volume mandatory -> DO NOT ENTER.
    cs = _score(volume=90_000.0)
    assert cs.score == 3
    assert cs.c4_volume is False
    assert cs.qualifies(min_confirm=2) is False
    assert cs.qualifies(min_confirm=3) is False


# ---------------------------------------------------------------------------------------------
# GOLD 7 — DETERMINISM.
# ---------------------------------------------------------------------------------------------


def test_golden_determinism() -> None:
    first = _score()
    for _ in range(50):
        again = _score()
        assert (again.c1_regime, again.c2_tbounce, again.c3_macd, again.c4_volume, again.score) == (
            first.c1_regime, first.c2_tbounce, first.c3_macd, first.c4_volume, first.score,
        )
