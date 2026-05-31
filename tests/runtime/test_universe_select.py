"""Tests for runtime.universe_select — the pure floor + rank helpers (#238 / Y).

Two helpers, each GOLDEN-MASTERED against an inline independent reference on identical bars:
  - apply_floors(bar_metrics)            == the canonical floor (close>=p AND dv>=adv), sorted
  - rank_and_cap(eligible, dv_by_ticker) == the canonical rank (DV-desc, ticker-asc tiebreak),
                                            capped to coarse_max
Under Y (Falk) BOTH helpers run, in sequence, inside lean_entry._coarse_selection (the
selection gate) — apply_floors then rank_and_cap → qc._ranked_today. They are PURE (no QC
types); the universe phase only exposes the result. The fused select_live_universe is gone.
"""
from __future__ import annotations

from runtime.universe_select import apply_floors, rank_and_cap


# --------------------------------------------------------------------------------------
# Inline independent reference implementations (the golden master). Deliberately written
# differently from the impl (explicit loops, not comprehensions) so a shared bug can't hide.
# --------------------------------------------------------------------------------------
def _ref_floors(bar_metrics, *, min_price, min_adv):
    out = []
    for ticker, (close, dv) in bar_metrics.items():
        if close >= min_price and dv >= min_adv:
            out.append(ticker)
    out.sort()
    return out


def _ref_rank_and_cap(eligible, dv_by_ticker, *, coarse_max):
    # decorate-sort-undecorate: (-dv, ticker) so DV-desc, ticker-asc tiebreak; case-insens dv.
    decorated = [(-dv_by_ticker.get(t.lower(), 0.0), t) for t in eligible]
    decorated.sort()
    ranked = [t for _negdv, t in decorated]
    return ranked[:coarse_max]


# A deterministic metric set covering every edge:
#   below/above price floor, below/above dv floor, dv ties (tiebreak), cap truncation, empty.
_METRICS = {
    "aaa": (50.0, 2.0e8),   # passes both
    "mmm": (50.0, 5.0e8),   # passes both
    "zzz": (50.0, 1.0e9),   # passes both (highest dv)
    "cheap": (9.99, 9.9e8),  # below price floor -> excluded (even though huge dv)
    "thin": (50.0, 9.99e7),  # below dv floor -> excluded
    "edgep": (10.0, 1.0e8),  # exactly AT both floors -> included (>= is inclusive)
    "tieb": (50.0, 3.0e8),   # ties tiea on dv -> ticker-asc tiebreak
    "tiea": (50.0, 3.0e8),   # ties tieb on dv
}


# ---- apply_floors golden master + edges ----
def test_apply_floors_golden_master_vs_reference():
    got = apply_floors(_METRICS, min_price=10.0, min_avg_dollar_volume=1.0e8)
    ref = _ref_floors(_METRICS, min_price=10.0, min_adv=1.0e8)
    assert got == ref
    # explicit: cheap (price) + thin (dv) dropped; rest kept, SORTED.
    assert got == ["aaa", "edgep", "mmm", "tiea", "tieb", "zzz"]


def test_apply_floors_boundary_inclusive():
    # >= on both floors: exactly-at-floor names pass.
    bm = {"at_p": (10.0, 1.0e8), "below_p": (9.999, 1.0e9), "below_dv": (50.0, 99_999_999.0)}
    assert apply_floors(bm, min_price=10.0, min_avg_dollar_volume=1.0e8) == ["at_p"]


def test_apply_floors_empty():
    assert apply_floors({}, min_price=10.0, min_avg_dollar_volume=1.0e8) == []


def test_apply_floors_defaults_are_the_agreed_values():
    import inspect
    sig = inspect.signature(apply_floors)
    assert sig.parameters["min_price"].default == 10.0
    assert sig.parameters["min_avg_dollar_volume"].default == 100_000_000.0


def test_apply_floors_returns_sorted_deterministic():
    # Insertion order must NOT leak into the output (determinism for local==cloud).
    bm1 = {"zzz": (50.0, 1.0e9), "aaa": (50.0, 2.0e8)}
    bm2 = {"aaa": (50.0, 2.0e8), "zzz": (50.0, 1.0e9)}
    assert apply_floors(bm1, min_price=10.0, min_avg_dollar_volume=1.0e8) == ["aaa", "zzz"]
    assert apply_floors(bm2, min_price=10.0, min_avg_dollar_volume=1.0e8) == ["aaa", "zzz"]


# ---- rank_and_cap golden master + edges ----
def _dv_of(metrics):  # lowercase-keyed dv view, as lean_entry builds qc._trailing_dv
    return {t: dv for t, (_close, dv) in metrics.items()}


def test_rank_and_cap_golden_master_vs_reference():
    eligible = apply_floors(_METRICS, min_price=10.0, min_avg_dollar_volume=1.0e8)
    dv = _dv_of(_METRICS)
    got = rank_and_cap(eligible, dv, coarse_max=9999)
    ref = _ref_rank_and_cap(eligible, dv, coarse_max=9999)
    assert got == ref
    # explicit DV-desc (zzz1e9 > mmm5e8 > {tiea,tieb}3e8 > aaa2e8 > edgep1e8); tiea before
    # tieb (ticker-asc tiebreak at the shared dv=3e8).
    assert got == ["zzz", "mmm", "tiea", "tieb", "aaa", "edgep"]


def test_rank_and_cap_dv_desc_ticker_tiebreak():
    eligible = ["b", "a", "c"]
    dv = {"b": 5.0e8, "a": 5.0e8, "c": 9.0e8}  # a,b tie
    assert rank_and_cap(eligible, dv, coarse_max=9999) == ["c", "a", "b"]


def test_rank_and_cap_truncates_at_coarse_max():
    eligible = ["big", "mid", "small"]
    dv = {"big": 1.0e9, "mid": 5.0e8, "small": 2.0e8}
    assert rank_and_cap(eligible, dv, coarse_max=2) == ["big", "mid"]


def test_rank_and_cap_case_insensitive_dv_lookup():
    # eligible may carry canonical UPPERCASE; dv keys are LOWERCASE (case-insensitive lookup).
    eligible = ["ZZZ", "AAA", "MMM"]
    dv = {"zzz": 1.0e9, "aaa": 2.0e8, "mmm": 5.0e8}
    assert rank_and_cap(eligible, dv, coarse_max=9999) == ["ZZZ", "MMM", "AAA"]


def test_rank_and_cap_missing_dv_defaults_zero_sorts_last():
    eligible = ["known", "unknown"]
    dv = {"known": 1.0e8}  # 'unknown' absent -> 0.0 -> ranks last
    assert rank_and_cap(eligible, dv, coarse_max=9999) == ["known", "unknown"]


def test_rank_and_cap_empty_eligible():
    assert rank_and_cap([], {"a": 1.0}, coarse_max=9999) == []


def test_rank_and_cap_defaults_are_the_agreed_values():
    import inspect
    sig = inspect.signature(rank_and_cap)
    assert sig.parameters["coarse_max"].default == 9999


def test_rank_and_cap_coarse_max_zero_yields_empty():
    # A 0 cap truncates to nothing (boundary; not a champion value, but the helper must be honest).
    assert rank_and_cap(["a", "b"], {"a": 2.0, "b": 1.0}, coarse_max=0) == []
