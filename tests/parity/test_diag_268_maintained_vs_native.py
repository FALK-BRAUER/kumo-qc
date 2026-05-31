"""#268 — pin the maintained-vs-native diagnostic's load-bearing pure logic.

scripts/diag_268_maintained_vs_native.py replicates LEAN's weekly IchimokuKinkoHyo and the
engine's seed+consolidator warm path in pure Python to localize the #265 signal divergence.
Two things must hold or the finding lies:

  1. ICHIMOKU MATH PARITY — the pure-Python ichimoku_series must agree with the oracle reference
     (oracle_helpers._mid + .shift(26), the DO-NOT-MODIFY parity oracle) on the same weekly bars.
  2. SEED-OVERLAP MODEL — a mid-week forced seed must (a) retain the seed's PARTIAL current week
     (the forward-only re-emit is rejected → the defect), and (b) leave a clean (no-seed / aligned)
     warm bit-identical to native (no spurious diff). Synthetic, deterministic data — no BT needed.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import diag_268_maintained_vs_native as D  # noqa: E402
from phases.shared.oracle_helpers import _mid as oracle_mid  # noqa: E402


def _ramp_daily(n: int) -> pd.DataFrame:
    """A deterministic rising daily OHLCV frame over n business days from 2022-01-03 — enough to
    fill the 78-week Ichimoku pole (n>=560 cal days)."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    base = pd.Series(range(n), dtype=float) + 100.0
    return pd.DataFrame(
        {
            "open": base.values,
            "high": (base + 1.0).values,
            "low": (base - 1.0).values,
            "close": (base + 0.5).values,
            "volume": [1_000_000.0] * n,
        },
        index=idx,
    )


def test_ichimoku_math_matches_oracle_reference() -> None:
    """ichimoku_series tenkan/kijun/senkou_a/senkou_b must equal the oracle _mid(+shift(26)) on
    the SAME weekly bars (oracle_helpers is the DO-NOT-MODIFY parity oracle). Exact float
    agreement at the last fully-ready bar."""
    daily = _ramp_daily(700)
    weekly = D.weekly_aggregate(daily)
    series = D.ichimoku_series(weekly)
    assert len(series) == len(weekly)

    wk = pd.DataFrame(
        {"high": [b["high"] for b in weekly], "low": [b["low"] for b in weekly]}
    )
    o_tenkan = oracle_mid(wk["high"], wk["low"], 9)
    o_kijun = oracle_mid(wk["high"], wk["low"], 26)
    o_sa = ((o_tenkan + o_kijun) / 2).shift(26)
    o_sb = oracle_mid(wk["high"], wk["low"], 52).shift(26)

    last = next(i for i in range(len(series) - 1, -1, -1) if series[i]["ready"])
    assert abs(series[last]["tenkan"] - float(o_tenkan.iloc[last])) < 1e-9
    assert abs(series[last]["kijun"] - float(o_kijun.iloc[last])) < 1e-9
    assert abs(series[last]["senkou_a"] - float(o_sa.iloc[last])) < 1e-9
    assert abs(series[last]["senkou_b"] - float(o_sb.iloc[last])) < 1e-9


def test_seed_overlap_retains_partial_week() -> None:
    """A mid-WEEK seed must keep the seed's PARTIAL current week (the forward-only re-emit of the
    full week on the SAME Monday is rejected) — the seed-overlap defect. Concretely: the
    maintained weekly bar whose Friday == the seed week's Friday must carry the PARTIAL
    (Mon..seed-day) close, NOT the full-week (Mon..Fri) close that native carries."""
    daily = _ramp_daily(700)
    # pick a Wednesday well inside the data.
    wed = date(2023, 6, 14)
    assert pd.Timestamp(wed).weekday() == 2  # Wed
    maint = D.maintained_weekly(daily, wed, date(2024, 1, 1))
    native = D.weekly_aggregate(daily[daily.index < pd.Timestamp("2024-01-01")])

    seed_friday = D.weekly_friday(pd.Timestamp(wed))
    m_bar = next(b for b in maint if b["friday"] == seed_friday)
    n_bar = next(b for b in native if b["friday"] == seed_friday)
    # On a strictly-rising ramp, the partial Mon..Wed close < the full Mon..Fri close.
    assert m_bar["close"] < n_bar["close"], "seed partial week should be < native full week"
    # And the partial week's close equals the seed-day-week's last PRE-seed-day close (Wed).
    wed_close = float(daily.loc[pd.Timestamp(wed) - pd.Timedelta(days=1), "close"])
    assert abs(m_bar["close"] - wed_close) < 1e-9


def test_aligned_seed_no_spurious_diff() -> None:
    """Control: when the maintained path is built identically to native (no partial-week split —
    we feed native to BOTH sides), diff_sequences reports ZERO diff. Guards against the diff
    machinery inventing a divergence."""
    daily = _ramp_daily(700)
    native_weeks = D.weekly_aggregate(daily)
    native_ichi = D.ichimoku_series(native_weeks)
    diff = D.diff_sequences(native_ichi, native_ichi, date(2022, 1, 1))
    assert diff["fy_weeks_with_any_diff"] == 0
    for v in diff["max_abs_diff"].values():
        assert v == 0.0
