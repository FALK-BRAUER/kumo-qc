"""#349 feature-panel — feature units (known→expected), the NO-LOOK-AHEAD invariant, grading metrics."""
import datetime as dt

import pytest

import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "scripts")]

import feature_panel as fp
from feature_panel import Bar


def _bars(closes, opens=None, highs=None, lows=None, vols=None, start=dt.date(2025, 1, 1)):
    n = len(closes)
    opens = opens or closes
    highs = highs or [max(o, c) for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) for o, c in zip(opens, closes)]
    vols = vols or [100.0] * n
    return [Bar(start + dt.timedelta(days=i), opens[i], highs[i], lows[i], closes[i], vols[i]) for i in range(n)]


# ── feature units ──

def test_roc_known():
    b = _bars([100, 101, 110])
    assert fp.roc(b, b[-1].d, 2) == pytest.approx(0.10)  # 110/100 - 1
    assert fp.roc(b, b[-1].d, 5) is None                 # insufficient


def test_dist_to_high_known():
    b = _bars([100, 120, 108], highs=[100, 120, 110])
    assert fp.dist_to_high(b, b[-1].d, None) == pytest.approx(108 / 120 - 1)  # ATH=120


def test_daily_open_close_known():
    b = _bars([102], opens=[100])
    assert fp.daily_open_close(b, b[-1].d) == pytest.approx(0.02)


def test_gap_known():
    b = _bars([100, 105], opens=[100, 103])
    assert fp.gap(b, b[-1].d) == pytest.approx(103 / 100 - 1)


def test_volume_surge_known():
    b = _bars([1] * 21, vols=[100.0] * 20 + [300.0])
    assert fp.volume_surge(b, b[-1].d, n=20) == pytest.approx(3.0)


def test_trend_persistence_known():
    closes = [1, 2, 3, 2, 4]  # last 4 vs prior: up,up,down,up = 3/4
    b = _bars(closes)
    assert fp.trend_persistence(b, b[-1].d, n=4) == pytest.approx(0.75)


def test_trend_slope_r2_clean_vs_choppy():
    clean = fp.trend_slope_r2(_bars([100 + i for i in range(63)]), dt.date(2025, 1, 1) + dt.timedelta(days=62), 63)
    assert clean is not None and clean[1] > 0.99 and clean[0] > 0      # perfect line → R²≈1, slope>0
    choppy = fp.trend_slope_r2(_bars([100 + (5 if i % 2 else 0) for i in range(63)]),
                               dt.date(2025, 1, 1) + dt.timedelta(days=62), 63)
    assert choppy is not None and choppy[1] < 0.1                       # zigzag → low R²


def test_rs_vs_benchmark():
    name = _bars([100, 110])   # +10%
    bench = _bars([100, 104])  # +4%
    assert fp.rs_vs_benchmark(name, bench, name[-1].d, 1) == pytest.approx(0.06)


# ── NO-LOOK-AHEAD invariant ──

def test_no_look_ahead_future_bars_ignored():
    # asof at index 2; a HUGE spike on FUTURE bars must NOT change the as-of feature value.
    closes = [100, 101, 110, 999, 1]  # future bars 999, 1
    b = _bars(closes)
    asof = b[2].d
    assert fp.roc(b, asof, 2) == pytest.approx(0.10)              # uses only <=asof (110/100-1)
    assert fp.dist_to_high(b, asof, None) == pytest.approx(110 / 110 - 1)  # ATH so far = 110, not 999
    # same as computing on the truncated series:
    trunc = b[:3]
    assert fp.roc(b, asof, 2) == fp.roc(trunc, asof, 2)
    assert fp.dist_to_high(b, asof, None) == fp.dist_to_high(trunc, asof, None)


def test_asof_excludes_exact_future():
    b = _bars([100, 200])
    assert fp.dist_to_high(b, b[0].d, None) == pytest.approx(0.0)  # only bar 0 (100); bar 1 (200) is future


# ── grading metrics ──

def test_spearman_separable_vs_not():
    label = [float(i) for i in range(10)]
    perfect = [float(i) for i in range(10)]            # feature == label → +1
    inverse = [float(-i) for i in range(10)]           # → -1
    flat = [5.0] * 10                                  # constant → None (no discrimination)
    assert fp.spearman(perfect, label) == pytest.approx(1.0)
    assert fp.spearman(inverse, label) == pytest.approx(-1.0)
    assert fp.spearman(flat, label) is None


def test_quartile_auc_separable_vs_not():
    label = [float(i) for i in range(12)]
    perfect = [float(i) for i in range(12)]            # top-quartile feature > bottom → AUC 1.0
    inverse = [float(-i) for i in range(12)]           # AUC 0.0
    assert fp.quartile_auc(perfect, label) == pytest.approx(1.0)
    assert fp.quartile_auc(inverse, label) == pytest.approx(0.0)
    # non-separable: feature constant → 0.5 (all ties)
    assert fp.quartile_auc([7.0] * 12, label) == pytest.approx(0.5)


def test_grading_length_mismatch_fails_loud():
    with pytest.raises(ValueError):
        fp.spearman([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        fp.quartile_auc([1.0, 2.0], [1.0])


# ── extended features ──

def test_liquidity_and_price_level():
    b = _bars([10.0] * 20, vols=[100.0] * 20)
    assert fp.liquidity_dollar_vol(b, b[-1].d, n=20) == pytest.approx(1000.0)  # 10*100
    assert fp.price_level(b, b[-1].d) == pytest.approx(10.0)


def test_weekly_aggregation():
    # 10 consecutive days → 2-3 ISO weeks; weekly close = last daily close of each week.
    b = _bars([100 + i for i in range(10)])
    wk = fp._weekly(b)
    assert len(wk) >= 2
    assert wk[-1].c == b[-1].c                      # last weekly close = last daily close
    assert wk[0].o == b[0].o                         # first weekly open = first daily open


def test_ichimoku_cloud_pos_above_below():
    rising = _bars([100 + i for i in range(90)])     # strong uptrend → price ABOVE cloud → pos > 0
    asof = rising[-1].d
    pos = fp.ichimoku_cloud_pos(rising, asof)
    assert pos is not None and pos > 0
    falling = _bars([200 - i for i in range(90)])     # downtrend → price BELOW cloud → pos < 0
    posf = fp.ichimoku_cloud_pos(falling, falling[-1].d)
    assert posf is not None and posf < 0


def test_ichimoku_not_ready_returns_none():
    b = _bars([100 + i for i in range(20)])           # < ~78 bars → Ichimoku never ready
    assert fp.ichimoku_cloud_pos(b, b[-1].d) is None


def test_ichimoku_no_look_ahead():
    # a giant future spike must not change the as-of cloud position.
    closes = [100 + i for i in range(90)] + [9999, 1]
    b = _bars(closes)
    asof = b[89].d
    full = fp.ichimoku_cloud_pos(b, asof)
    trunc = fp.ichimoku_cloud_pos(b[:90], asof)
    assert full == trunc                              # future bars (9999,1) ignored


def test_weekly_ichimoku_pos_runs():
    b = _bars([100 + i * 0.5 for i in range(750)])    # ~750 daily → ~107 weekly → Ichimoku ready
    pos = fp.weekly_ichimoku_pos(b, b[-1].d)
    assert pos is not None and pos > 0                # rising → above weekly cloud


# ── #353 manual features (panel-missed: continuous-growth, prior-high/clearance) ──

def test_monthly_aggregation():
    # ~90 calendar days → ~3-4 months; monthly close = last daily close of each month.
    b = _bars([100 + i for i in range(90)])
    m = fp._monthly(b)
    assert len(m) >= 3
    assert m[-1].c == b[-1].c and m[0].o == b[0].o


def test_continuous_growth_clean_up_vs_choppy():
    # clean monthly uptrend (≈400 daily rising → ~13 months) → high +signed-R².
    up = fp.continuous_growth(_bars([100 + i for i in range(400)]), dt.date(2025, 1, 1) + dt.timedelta(days=399), 12)
    assert up is not None and up > 0.9
    # choppy → near 0.
    chop = fp.continuous_growth(_bars([100 + (8 if i % 40 < 20 else 0) for i in range(400)]),
                                dt.date(2025, 1, 1) + dt.timedelta(days=399), 12)
    assert chop is not None and abs(chop) < 0.6


def test_dist_to_prior_high_signed():
    # build ~5 months: a prior high of 150 (months 1-3), then pull back to 140 (recent) → below prior.
    closes = [150] * 60 + [140] * 60   # ~4 months; prior-high (excl last 2 mo) = 150, current = 140
    highs = [150] * 60 + [142] * 60
    b = _bars(closes, highs=highs)
    d = fp.dist_to_prior_high(b, b[-1].d, lookback_months=12, excl_recent=2)
    assert d is not None and d < 0          # 140 below the prior 150 → negative
    # a name that CLEARED its prior high → positive
    closes2 = [100] * 60 + [130] * 60
    highs2 = [100] * 60 + [131] * 60
    b2 = _bars(closes2, highs=highs2)
    d2 = fp.dist_to_prior_high(b2, b2[-1].d, lookback_months=12, excl_recent=2)
    assert d2 is not None and d2 > 0          # 130 above the prior 100 → cleared


def test_continuous_growth_no_look_ahead():
    closes = [100 + i for i in range(400)] + [99999, 1]
    b = _bars(closes)
    asof = b[399].d
    assert fp.continuous_growth(b, asof, 12) == fp.continuous_growth(b[:400], asof, 12)


def test_monthly_momentum_roc_reuse():
    # monthly momentum = roc over a multi-month horizon (reuses roc, in days).
    b = _bars([100 * (1.01 ** i) for i in range(300)])
    assert fp.roc(b, b[-1].d, 126) is not None and fp.roc(b, b[-1].d, 126) > 0
