"""#264 — the REAL-DATA anti-mirage integration guard (the #259 "wakes up in October" fingerprint
must be IMPOSSIBLE).

THE MIRAGE (research/parity/first-divergence-diff-2025.md, #173): indicators that warmed LATE
"woke up in October" — a name was effectively scored off partial/cold state, producing the fake
−0.616 baseline. The anti-mirage invariant has TWO halves, both asserted here over REAL on-disk
data (the data symlink), distinguishing 'correctly not-yet-ready -> excluded' from 'silently
scored cold -> mirage' (the latter must be UNREACHABLE):

  HALF 1 (SEED CAN reach readiness): over a real liquid name's daily history, WARMUP_DAYS of bars
    replayed through the REAL seed path (runtime.indicators.weekly_aggregate, the manual weekly
    aggregation _seed_weekly uses) yields >= 78 weekly bars — i.e. the WEEKLY IchimokuKinkoHyo
    (the BINDING 78-week readiness, the longest pole) CAN warm from the seed alone. If it could
    not, a post-warmup entrant would be cold at its first score -> the mirage. The daily-suite
    poles (200d SMA, 78d daily-Ichimoku, ADX, ROC, the 27-deep weekly-close window) are all
    SHORTER than 78 weeks, so the weekly bar count is the load-bearing sufficiency check.

  HALF 2 (COLD CANNOT score): the maintained scorer is STRUCTURALLY incapable of emitting a score
    while any input is not-ready — a property fuzz over the readiness flags on REAL-derived value
    layouts confirms score_symbol_native returns None whenever ANY gate is not-ready, and a number
    ONLY when ALL are ready. This is the invariant that makes "scored cold" unreachable: there is
    no value combination of not-ready inputs that yields a score.

If the local data tree is absent (CI without the gitignored data/), HALF 1 SKIPS with a reason
(data-presence guard, not a silent pass) — matching tests/data/test_warmup_coarse.py. HALF 2 is
pure logic and always runs.

#260 REFACTOR: the daily-zip loader, the data-presence guard, the liquid probe set, and the
QC-native value-shapes are now the shared tests/harness/realdata.py primitives (they were
triplicated across the real-data tests). The ASSERTIONS below are unchanged.
"""
from __future__ import annotations

import itertools

import pytest

from phases.shared.oracle_helpers import score_symbol_native
from runtime.indicators import weekly_aggregate
from runtime.lean_entry import BctEngineAlgorithm
from tests.harness import realdata as rd


@pytest.mark.skipif(not rd.have_daily_tree(), reason="local LEAN daily tree absent (gitignored data/)")
def test_data_tree_not_fully_pruned() -> None:
    # FAIL-LOUD on a coverage mirage: if the daily dir EXISTS but every liquid zip is pruned, the
    # parametrized HALF-1 tests below all per-ticker-skip and the file passes as a silent no-op.
    # This guard makes that state RAISE instead of green — at least one liquid name must be present
    # when the tree is present, so HALF 1 genuinely exercises the seed path.
    assert any(rd.daily_available(t) for t in rd.LIQUID), (
        f"daily tree present at {rd.DAILY_DIR} but none of {rd.LIQUID} on disk — HALF-1 seed "
        f"coverage would silently no-op (a coverage mirage). Restore the data symlink / liquid zips."
    )


# ======================================================================================
# HALF 1 — the SEED can reach the binding weekly-Ichimoku readiness from real history.
# ======================================================================================
@pytest.mark.skipif(not rd.have_daily_tree(), reason="local LEAN daily tree absent (gitignored data/)")
@pytest.mark.parametrize("ticker", rd.LIQUID)
def test_seed_reaches_weekly_ichimoku_readiness_real_data(ticker: str) -> None:
    if not rd.daily_available(ticker):
        pytest.skip(f"{ticker}.zip absent on disk")
    df = rd.read_daily_zip(ticker)
    # _seed_weekly pulls `self.history(sym, WARMUP_DAYS, Resolution.DAILY)` — the INT form of QC
    # History returns that many BARS (trading days), not calendar days. So the seed window is the
    # LAST WARMUP_DAYS (560) trading bars ~ 112 weeks, comfortably above the 78-week pole.
    window = df.iloc[-BctEngineAlgorithm.WARMUP_DAYS:]
    weekly = weekly_aggregate(window)
    # BINDING constraint: the weekly IchimokuKinkoHyo needs 78 completed weekly bars to be ready.
    # The seed must deliver >= 78 from the WARMUP_DAYS window — else a post-warmup entrant is
    # cold at its first score (the mirage). >= 78 proves the seed CAN warm the longest pole.
    assert len(weekly) >= 78, (
        f"{ticker}: WARMUP_DAYS seed produced only {len(weekly)} weekly bars "
        f"(< 78 weekly-Ichimoku readiness) — a post-warmup entrant would be COLD at first score"
    )
    # And the 27-deep weekly-close window (chikou cond 3, score_symbol_native needs w_close[26])
    # is trivially satisfied by >= 78 weekly closes.
    assert len(weekly) >= 27


@pytest.mark.skipif(not rd.have_daily_tree(), reason="local LEAN daily tree absent (gitignored data/)")
@pytest.mark.parametrize("ticker", rd.LIQUID)
def test_seed_reaches_daily_suite_readiness_real_data(ticker: str) -> None:
    if not rd.daily_available(ticker):
        pytest.skip(f"{ticker}.zip absent on disk")
    df = rd.read_daily_zip(ticker)
    # Same INT-form history semantics: last WARMUP_DAYS (560) trading bars.
    window = df.iloc[-BctEngineAlgorithm.WARMUP_DAYS:]
    # The daily-suite poles (all SHORTER than the 78-week weekly pole): 200d SMA, 78d daily
    # Ichimoku, ADX(9), ROC(13). The seed feeds one bar per trading day -> need >= 200 trading
    # days for the longest daily pole (sma200) to warm. WARMUP_DAYS=560 bars >> 200.
    assert len(window) >= 200, (
        f"{ticker}: only {len(window)} trading days in the WARMUP_DAYS window — the 200d SMA "
        f"(longest daily pole) cannot warm from the seed"
    )


# ======================================================================================
# HALF 2 — COLD CANNOT score: the maintained scorer never emits a number off a not-ready input.
# Property fuzz over the readiness flags (the anti-mirage structural invariant). The value-shapes
# are the shared realdata.build_native_suite primitive (#260 dedup); the fuzz is unchanged.
# ======================================================================================
def test_cold_cannot_score_property_fuzz() -> None:
    # Exhaustive small fuzz: across all combinations of the 5 readiness flags + the two window
    # counts at their boundaries, a score is emitted IFF every gate is ready. No not-ready combo
    # ever yields a number -> "silently scored cold" is structurally UNREACHABLE.
    scored_when_not_all_ready = []
    for d_r, w_r, sma_r, adx_r, roc_r in itertools.product([True, False], repeat=5):
        for wclose_n in (26, 27):       # 26 = too short, 27 = exactly ready
            for adxwin_n in (3, 4):     # 3 = too short, 4 = exactly ready
                ind, qc = rd.build_native_suite(
                    d_ready=d_r, w_ready=w_r, sma_ready=sma_r, adx_ready=adx_r, roc_ready=roc_r,
                    wclose_n=wclose_n, adxwin_n=adxwin_n, price=100.0,
                )
                r = score_symbol_native(qc, "SYM", ind)
                all_ready = (d_r and w_r and sma_r and adx_r and roc_r
                             and wclose_n >= 27 and adxwin_n >= 4)
                if r is not None and not all_ready:
                    scored_when_not_all_ready.append(
                        (d_r, w_r, sma_r, adx_r, roc_r, wclose_n, adxwin_n)
                    )
                if all_ready:
                    assert r is not None, "fully-ready set must score (sanity)"
    assert scored_when_not_all_ready == [], (
        f"MIRAGE: scorer emitted a score on a NOT-fully-ready input: {scored_when_not_all_ready}"
    )
