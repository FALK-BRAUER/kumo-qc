"""#253 METHODOLOGY GOLDEN-MASTER for the ENTRY-CONFIRMATION phase (§4 Gate 2 + §2 C1-C4).

The methodology anchor for `BctEntryConfirm`: each fixture encodes a KNOWN §4 Gate-2 decision
(the GH#253 authoritative comment: SCORED X/4, C1 regime + C4 volume MANDATORY, the four
component definitions) as a hand-specified float state, then asserts the PURE scorer
`evaluate_gate2` reproduces that decision — the exact per-component pass/fail AND the X/4 count.

GOLDEN-MASTER DISCIPLINE (charter: RAW-own-merits): these assert LOGIC CORRECTNESS on identical
hand-computed inputs — the coded components == the methodology's §2 components. They are NOT
champion-number matching and carry NO universe/snapshot assumption. If this file fails, the gate
DIVERGED from the methodology — STOP + FLAG for HQ; do NOT edit the scorer to make it pass.

The 4 components, in scorer order (bct_entry_confirm.evaluate_gate2):
  C1 Regime    price > daily cloud top AND Tenkan > Kijun
  C2 T-Bounce  was-above(<=3 sessions below) AND near-Tenkan(<=tol) AND bounced(price>=Tenkan)
               AND T>K AND not-in-cloud AND not-degraded(tenkan-flat / large-gap-up)
  C3 MACD      hist>0  OR (hist<=0 AND turning-up)  -> confirm; else (neg & turning-down/flat) NO
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
# A methodology-anchored ALL-CONFIRM reference (4/4). Price=100. Every component passes with a
# clear margin so toggling exactly one input flips exactly one component.
#   C1: cloud top 90 < 100, tenkan 99.7 > kijun 95  -> regime BULL
#   C2: price 100 within 0.5% of tenkan 99.7 (0.30%), price>=tenkan (bounced), T>K, not in cloud
#       (cloud 80..90 < 100), sessions_below=0 (was above), gap_up 0 (no gap)
#   C3: hist now 0.5 > prev 0.2 -> positive & turning up
#   C4: volume 200k >= 1.0 x avg 100k
# ---------------------------------------------------------------------------------------------

_BASE: dict[str, Any] = dict(
    price=100.0,
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
    volume_gate_mult=1.0,
    gap_up_threshold=0.05,
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
# GOLD 2 — EACH-COMPONENT-FAILED: mutate the input(s) that drive one component so it flips False
# and assert the right flag is False at score 3. NOTE the GENUINE coupling (asserted, not fought):
#   - C1's "T>K" leg is SHARED with C2's "T>K" sub-condition; C1's price-vs-cloud is SHARED with
#     C2's "not in cloud". So C1 cannot be failed in TRUE isolation from C2 — see GOLD 6
#     (qualify rule) for the coupled C1-fail behavior. Here C3/C4 are independently isolable, and
#     C2 is isolated via a far-from-Tenkan-but-T>K-intact state.
# ---------------------------------------------------------------------------------------------

_FAIL_ONE: list[tuple[str, str, dict[str, Any], int]] = [
    # C2 t-bounce: Tenkan far ABOVE price (4.8% > tol) so price is not near + did not reclaim,
    # but T>K stays intact (105>95) and price>cloud stays (100>90) so C1 still PASSES -> only C2.
    ("c2_tbounce", "C2 not near tenkan (T>K kept)", {"d_tenkan": 105.0}, 3),
    # C3 macd: negative AND turning down — the one MACD state that fails (fully independent).
    ("c3_macd", "C3 neg+turning-down", {"macd_hist_now": -0.5, "macd_hist_prev": -0.2}, 3),
    # C4 volume: below the 1.0x gate (fully independent).
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
    # the OTHER three should be True (the isolated single-flip).
    others = {k: v for k, v in flags.items() if k != attr}
    assert all(others.values()), f"{label}: only {attr} should flip, got {flags}"


def test_golden_c1_regime_fail_couples_c2() -> None:
    # C1's T>K and price-vs-cloud legs are SHARED with C2. Failing C1 via T<=K ALSO fails C2's
    # T>K sub-condition (documented coupling — the methodology's regime IS C2's precondition).
    cs = _score(d_tenkan=94.0, d_kijun=95.0)
    assert cs.c1_regime is False  # T<K
    assert cs.c2_tbounce is False  # coupled (C2 requires T>K)
    assert (cs.c3_macd, cs.c4_volume) == (True, True)
    assert cs.score == 2


# ---------------------------------------------------------------------------------------------
# GOLD 3 — C2 T-Bounce sub-conditions broken out: each of the 5 ANDed sub-clauses + the 2
# degrade guards must independently drop C2 (the methodology states ALL of them).
# ---------------------------------------------------------------------------------------------

_C2_BREAKS: list[tuple[str, dict[str, Any]]] = [
    ("(a) was below tenkan >3 sessions", {"sessions_below_tenkan": 4}),
    ("(b) not near tenkan (>tol)", {"d_tenkan": 90.5}),
    ("(c) did not bounce (price<tenkan)", {"price": 99.0, "d_tenkan": 99.4}),  # near but below
    ("(d) tenkan<=kijun", {"d_kijun": 100.0}),
    ("(e) inside the cloud", {"d_cloud_top": 101.0, "d_cloud_bottom": 99.0}),
    ("degrade: tenkan flat (~kijun)", {"d_kijun": 99.4}),  # tenkan 99.7 within 0.5% of kijun
    ("degrade: large gap-up (>=thresh)", {"gap_up_frac": 0.06}),
]


@pytest.mark.parametrize("label,override", _C2_BREAKS, ids=[b[0] for b in _C2_BREAKS])
def test_golden_c2_subconditions(label: str, override: dict[str, Any]) -> None:
    cs = _score(**override)
    assert cs.c2_tbounce is False, f"C2 must fail when: {label}"


def test_golden_c2_boundary_near_tenkan_exact_tol() -> None:
    # Pullback exactly at the tolerance edge (0.5%) still counts (<=, inclusive). price 100,
    # tenkan such that |100/tenkan - 1| == 0.005 -> tenkan = 100/1.005.
    cs = _score(d_tenkan=100.0 / 1.005)
    assert cs.c2_tbounce is True  # price 100 >= tenkan (~99.5), within tol, not degraded


# ---------------------------------------------------------------------------------------------
# GOLD 4 — C3 MACD the four states (the §2 Component-3 table): positive+up / positive+flat /
# negative+up / negative+down. Only negative+down (and negative-flat) FAIL.
# ---------------------------------------------------------------------------------------------

_C3_STATES: list[tuple[str, float, float, bool]] = [
    ("positive turning up", 0.5, 0.2, True),
    ("positive flat", 0.5, 0.5, True),
    ("negative turning up (divergence)", -0.2, -0.5, True),
    ("negative turning down", -0.5, -0.2, False),
    ("negative flat", -0.5, -0.5, False),
    ("zero flat", 0.0, 0.0, False),
]


@pytest.mark.parametrize(
    "label,now,prev,expect", _C3_STATES, ids=[s[0] for s in _C3_STATES]
)
def test_golden_c3_macd_states(label: str, now: float, prev: float, expect: bool) -> None:
    cs = _score(macd_hist_now=now, macd_hist_prev=prev)
    assert cs.c3_macd is expect, f"C3 {label}: expected {expect}"


# ---------------------------------------------------------------------------------------------
# GOLD 5 — C4 volume gate boundary + tier independence. Gate is >= 1.0x (inclusive). The 1.5x
# is the full-SIZE tier, NOT the gate (GH#253 correction) — so 1.0x exactly PASSES the gate.
# ---------------------------------------------------------------------------------------------


def test_golden_c4_volume_gate_boundary_inclusive() -> None:
    assert _score(volume=100_000.0, vol_avg20=100_000.0).c4_volume is True   # exactly 1.0x
    assert _score(volume=99_999.0, vol_avg20=100_000.0).c4_volume is False   # just under
    assert _score(volume=150_000.0, vol_avg20=100_000.0).c4_volume is True   # 1.5x (strong)


def test_golden_c4_custom_gate_multiple() -> None:
    # With a 1.5x gate, 1.0x volume no longer passes.
    assert _score(volume=100_000.0, vol_avg20=100_000.0, volume_gate_mult=1.5).c4_volume is False
    assert _score(volume=150_000.0, vol_avg20=100_000.0, volume_gate_mult=1.5).c4_volume is True


# ---------------------------------------------------------------------------------------------
# GOLD 6 — the QUALIFY rule: score >= min_confirm AND regime(C1) AND volume(C4) mandatory.
# A 2/4 that misses regime or volume is DO-NOT-ENTER (GH#253 "only if regime + volume both pass").
# ---------------------------------------------------------------------------------------------


def test_golden_qualify_2of4_with_mandatory_passes() -> None:
    # C1 + C4 pass, C2 + C3 fail -> 2/4 with both mandatory -> qualifies at min_confirm=2.
    # Tenkan 105 above price keeps T>K (C1 ok) but fails C2 (not near / no reclaim); MACD
    # negative-turning-down fails C3; volume (base) keeps C4.
    cs = _score(d_tenkan=105.0, macd_hist_now=-0.5, macd_hist_prev=-0.2)
    assert (cs.c1_regime, cs.c4_volume) == (True, True)
    assert (cs.c2_tbounce, cs.c3_macd) == (False, False)
    assert cs.score == 2
    assert cs.qualifies(min_confirm=2) is True
    assert cs.qualifies(min_confirm=3) is False  # 2 < 3


def test_golden_qualify_2of4_missing_regime_is_do_not_enter() -> None:
    # 2/4 where the two passing are C2 + C3 but C1 regime FAILS -> DO NOT ENTER even at min=2.
    # tenkan<=kijun fails C1; volume below gate fails C4; keep C2 & C3 passing.
    # (C2 needs price near tenkan + price>=tenkan + T>K + not-in-cloud; we fail C1 only via cloud.)
    cs = _score(d_cloud_top=101.0, d_cloud_bottom=99.5, volume=90_000.0)
    # price 100 inside cloud -> C1 fails (price not > cloud top) AND C2 (in cloud) fails too.
    assert cs.c1_regime is False
    assert cs.c4_volume is False
    assert cs.qualifies(min_confirm=2) is False  # missing both mandatory


def test_golden_qualify_missing_volume_is_do_not_enter() -> None:
    # C1 + C2 + C3 pass (3/4) but C4 volume fails -> volume mandatory -> DO NOT ENTER.
    cs = _score(volume=90_000.0)
    assert cs.score == 3
    assert cs.c4_volume is False
    assert cs.qualifies(min_confirm=2) is False
    assert cs.qualifies(min_confirm=3) is False


# ---------------------------------------------------------------------------------------------
# GOLD 7 — DETERMINISM: same inputs scored repeatedly yield identical results.
# ---------------------------------------------------------------------------------------------


def test_golden_determinism() -> None:
    first = _score()
    for _ in range(50):
        again = _score()
        assert (again.c1_regime, again.c2_tbounce, again.c3_macd, again.c4_volume, again.score) == (
            first.c1_regime, first.c2_tbounce, first.c3_macd, first.c4_volume, first.score,
        )
