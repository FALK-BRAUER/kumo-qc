"""Tests for runtime.universe_select — the live filter→rank→cap (#238).

Golden-master: select_live_universe (with an all-pass prefilter) == the canonical INLINE
reference (price≥floor AND trailing-DV≥floor → rank DV-desc, ticker tiebreak → cap) — the
same logic the retired build_filter/build_universe held. Plus prefilter behavior + edges.
"""
from __future__ import annotations

from runtime.universe_select import select_live_universe


def _reference(raw, *, min_price, min_adv, coarse_max):
    """Canonical filter+rank+cap (the build_filter eligibility + build_universe rank), inline
    so there's no dead build_*.py reference to re-tempt file regeneration."""
    elig = {t: tdv for t, (close, tdv) in raw.items() if close >= min_price and tdv >= min_adv}
    ranked = sorted(elig.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:coarse_max]]


def test_golden_master_vs_reference_allpass_prefilter():
    # All names clear the prefilter (single-day DV huge) → select == the canonical reference.
    raw = {
        "aaa": (50.0, 2.0e8), "mmm": (50.0, 5.0e8), "zzz": (50.0, 1.0e9),
        "cheap": (9.0, 9.9e8),        # below price floor → excluded
        "thin": (50.0, 5.0e7),        # below 100M trailing floor → excluded
    }
    coarse = {t: 1.0e12 for t in raw}  # all pass prefilter
    got = select_live_universe(coarse, raw, prefilter_dv=0.0, min_price=10.0,
                               min_avg_dollar_volume=1.0e8, coarse_max=9999)
    assert got == _reference(raw, min_price=10.0, min_adv=1.0e8, coarse_max=9999)
    assert got == ["zzz", "mmm", "aaa"]  # DV-desc; cheap+thin excluded


def test_rank_is_dv_desc_ticker_tiebreak():
    raw = {"b": (50.0, 5.0e8), "a": (50.0, 5.0e8), "c": (50.0, 9.0e8)}  # a,b tie on DV
    coarse = {t: 1.0e12 for t in raw}
    got = select_live_universe(coarse, raw, prefilter_dv=0.0, min_avg_dollar_volume=1.0e8)
    assert got == ["c", "a", "b"]  # c highest; a before b (ticker tiebreak)


def test_coarse_max_caps_in_rank_order():
    raw = {"big": (50.0, 1.0e9), "mid": (50.0, 5.0e8), "small": (50.0, 2.0e8)}
    coarse = {t: 1.0e12 for t in raw}
    got = select_live_universe(coarse, raw, prefilter_dv=0.0, min_avg_dollar_volume=1.0e8, coarse_max=2)
    assert got == ["big", "mid"]


def test_prefilter_drops_low_single_day_dv():
    # A name with single-day DV below the prefilter is dropped BEFORE the precise stage,
    # even if its trailing DV would qualify. (The perf-bound.)
    raw = {"x": (50.0, 2.0e8)}  # trailing 200M qualifies
    assert select_live_universe({"x": 1.0e7}, raw, prefilter_dv=25_000_000.0,
                                min_avg_dollar_volume=1.0e8) == []      # single-day 10M < 25M prefilter
    assert select_live_universe({"x": 3.0e7}, raw, prefilter_dv=25_000_000.0,
                                min_avg_dollar_volume=1.0e8) == ["x"]   # single-day 30M ≥ 25M → kept


def test_prefilter_loose_keeps_qualifying_name_on_quiet_day():
    # The 25M prefilter must NOT drop a 100M-trailing name whose single-day DV dipped to 30M.
    raw = {"quiet": (50.0, 1.0e8)}  # exactly at the 100M floor
    assert select_live_universe({"quiet": 3.0e7}, raw, prefilter_dv=25_000_000.0,
                                min_avg_dollar_volume=1.0e8) == ["quiet"]


def test_price_floor_and_adv_floor_on_raw():
    raw = {"cheap": (9.99, 1.0e9), "thin": (50.0, 9.99e7), "ok": (50.0, 1.0e8)}
    coarse = {t: 1.0e12 for t in raw}
    got = select_live_universe(coarse, raw, prefilter_dv=0.0, min_price=10.0, min_avg_dollar_volume=1.0e8)
    assert got == ["ok"]  # cheap<$10, thin<100M trailing


def test_survivor_without_history_dropped():
    # Prefilter survivor with no RAW history entry → dropped (fail-safe, not assumed).
    assert select_live_universe({"x": 1.0e12}, {}, prefilter_dv=0.0, min_avg_dollar_volume=1.0e8) == []


def test_defaults_are_the_agreed_values():
    # prefilter 25M (perf-bound), min_price 10, min_adv 100M (liquidity floor), coarse_max 9999.
    import inspect
    sig = inspect.signature(select_live_universe)
    assert sig.parameters["prefilter_dv"].default == 25_000_000.0
    assert sig.parameters["min_price"].default == 10.0
    assert sig.parameters["min_avg_dollar_volume"].default == 100_000_000.0
    assert sig.parameters["coarse_max"].default == 9999
