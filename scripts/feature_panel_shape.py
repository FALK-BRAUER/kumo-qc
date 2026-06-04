"""#372 stage-1 — MULTI-TIMEFRAME SHAPE features (as-of entry, NO look-ahead).

#349 graded single daily scalars and found nothing robust. The #372 hypothesis: the discriminator
between a base-breakout winner (CIBR +$121) and a parabolic-spike loser (IGV 94→107 vertical, entry
at the blow-off, −$111) is the SHAPE of the last few weeks plus multi-timeframe agreement — not any
one daily distance scalar (dist_ath can't tell them apart).

This module ADDS shape features on top of scripts/feature_panel.py. Every feature is computed AS-OF
the candidate's entry date: it reads ONLY bars with date <= asof (via fp._asof / the _weekly/_monthly
helpers that key on the LAST daily date in the bucket). A feature that needs a future bar returns None.

HARD CONSTRAINTS (inherited from #349):
- NO LOOK-AHEAD — proven by the as-of unit test (scripts/test_372_shape_asof.py) that appends wild
  future bars and asserts every feature value is unchanged.
- forward-return (the label) is graded-on ONLY, never an input.
- missing/insufficient data → None (fail-loud at the caller; never silent 0).

Bar = feature_panel.Bar (NamedTuple d,o,h,l,c,v), ASC by date.
"""
from __future__ import annotations

import datetime as _dt
from typing import Sequence

import feature_panel as fp
from feature_panel import Bar


# ─────────────────────────── helpers ───────────────────────────

def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _ols_slope(ys: Sequence[float]) -> float | None:
    """Plain OLS slope of ys vs index 0..n-1 (un-normalised). None if < 2 points or degenerate."""
    n = len(ys)
    if n < 2:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


# ─────────────────────── 1. multi-TF trend agreement ───────────────────────

def _tf_signed_slope(bars: list[Bar], asof: _dt.date, agg, n: int) -> float | None:
    """Signed, mean-normalised slope (slope/mean_close) of the last n candles on a timeframe."""
    tf = agg([b for b in bars if b.d <= asof])
    if len(tf) < n:
        return None
    sl = fp.trend_slope_r2(tf, tf[-1].d, n)
    if sl is None:
        return None
    return sl[0]  # already slope/mean_close


def mtf_slope_daily(bars: Sequence[Bar], asof: _dt.date, n: int = 20) -> float | None:
    """Normalised daily-close slope over the last n daily bars (as-of)."""
    return _tf_signed_slope(list(bars), asof, lambda x: x, n)


def mtf_slope_weekly(bars: Sequence[Bar], asof: _dt.date, n: int = 12) -> float | None:
    """Normalised weekly-close slope over the last n weekly candles (as-of)."""
    return _tf_signed_slope(list(bars), asof, fp._weekly, n)


def mtf_slope_monthly(bars: Sequence[Bar], asof: _dt.date, n: int = 6) -> float | None:
    """Normalised monthly-close slope over the last n monthly candles (as-of)."""
    return _tf_signed_slope(list(bars), asof, fp._monthly, n)


def mtf_agreement(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Multi-timeframe trend AGREEMENT score (the IGV-divergence flag). Sum of the SIGNS of the
    daily(20)/weekly(12)/monthly(6) normalised slopes → {-3..+3}. +3 = all three up (aligned uptrend,
    a healthy base-breakout shape); divergence (e.g. monthly up but daily blowing off, or daily up
    monthly down) sits near 0. None if any timeframe lacks enough history."""
    d = mtf_slope_daily(bars, asof, 20)
    w = mtf_slope_weekly(bars, asof, 12)
    m = mtf_slope_monthly(bars, asof, 6)
    if d is None or w is None or m is None:
        return None
    return float(_sign(d) + _sign(w) + _sign(m))


def mtf_slope_dispersion(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Spread between the FAST (daily) and SLOW (monthly) normalised slopes: daily_slope − monthly_slope.
    A parabolic blow-off has daily slope >> monthly slope (recent acceleration far above the base trend);
    a steady base-breakout has them comparable. Large positive = chasing a vertical move. None if short."""
    d = mtf_slope_daily(bars, asof, 20)
    m = mtf_slope_monthly(bars, asof, 6)
    if d is None or m is None:
        return None
    return d - m


# ─────────────────────── 2. base-vs-spike (the novel discriminator) ───────────────────────

def _base_window(w: list[Bar], base_lb: int, excl_recent: int) -> list[Bar] | None:
    """The 'base' = bars [-(base_lb+excl_recent) : -excl_recent] — i.e. the consolidation BEFORE the
    most recent excl_recent bars (which are the breakout/spike leg). None if insufficient."""
    if len(w) < base_lb + excl_recent + 1:
        return None
    base = w[-(base_lb + excl_recent):-excl_recent] if excl_recent > 0 else w[-base_lb:]
    return base or None


def extension_above_base(bars: Sequence[Bar], asof: _dt.date,
                         base_lb: int = 40, excl_recent: int = 5) -> float | None:
    """(entry_close − base_top) / base_height. base_top = max HIGH of the base window; base_height =
    base_top − base_low (the consolidation range). ~0 = breaking out right at the base top (base-buy);
    large = price has run far above the base (chasing an extended move). Negative = still inside/under
    the base. None if insufficient history or a degenerate (zero-height) base."""
    w = fp._asof(bars, asof)
    base = _base_window(w, base_lb, excl_recent)
    if base is None:
        return None
    base_top = max(b.h for b in base)
    base_low = min(b.l for b in base)
    height = base_top - base_low
    if height <= 0:
        return None
    return (w[-1].c - base_top) / height


def parabolic_accel(bars: Sequence[Bar], asof: _dt.date, seg: int = 5) -> float | None:
    """Blow-off detector: slope-of-slope (2nd derivative) of close over the last 3 segments of length
    `seg`, expressed as a fraction of mean close. Computes the mean-close slope of each of the three
    most-recent `seg`-bar segments, then the slope of those three slopes. >0 = accelerating up
    (steepening = parabolic); ~0 = linear; <0 = decelerating. None if < 3*seg bars."""
    w = fp._asof(bars, asof)
    if len(w) < 3 * seg:
        return None
    mc = sum(b.c for b in w[-3 * seg:]) / (3 * seg)
    if mc <= 0:
        return None
    seg_slopes = []
    for k in range(3):
        chunk = w[-(3 - k) * seg: len(w) - (2 - k) * seg] if k < 2 else w[-seg:]
        s = _ols_slope([b.c for b in chunk])
        if s is None:
            return None
        seg_slopes.append(s / mc)
    accel = _ols_slope(seg_slopes)
    return accel


def range_expansion(bars: Sequence[Bar], asof: _dt.date, recent: int = 5, base: int = 20) -> float | None:
    """Mean true-range of the last `recent` bars / mean true-range of the prior `base` bars (both as a
    fraction of close, so it's scale-free). >1 = range expanding into entry (blow-off / climax); ~1 or
    <1 = quiet, controlled (a tight base). None if insufficient history."""
    w = fp._asof(bars, asof)
    if len(w) < recent + base + 1:
        return None
    def _atr_frac(seg: list[Bar]) -> float | None:
        trs = []
        for i in range(1, len(seg)):
            h, l, pc = seg[i].h, seg[i].l, seg[i - 1].c
            tr = max(h - l, abs(h - pc), abs(l - pc))
            if seg[i].c > 0:
                trs.append(tr / seg[i].c)
        return sum(trs) / len(trs) if trs else None
    recent_seg = w[-recent - 1:]            # recent+1 bars → `recent` TRs
    base_seg = w[-(recent + base + 1):-recent]  # base+1 bars → `base` TRs
    r = _atr_frac(recent_seg)
    b = _atr_frac(base_seg)
    if r is None or b is None or b <= 0:
        return None
    return r / b


def consolidation_quality(bars: Sequence[Bar], asof: _dt.date,
                          base_lb: int = 40, excl_recent: int = 5) -> float | None:
    """Tightness of the BASE before the breakout leg: base_height / base_mid (range as a fraction of
    the base's mid-price), SIGN-FLIPPED so HIGHER = TIGHTER = better base. A tight low-vol base scores
    near 0 (returned as a small-magnitude negative); a wide sloppy/vertical base scores very negative.
    None if insufficient or degenerate. (Reads only the base window — excludes the recent breakout leg.)"""
    w = fp._asof(bars, asof)
    base = _base_window(w, base_lb, excl_recent)
    if base is None:
        return None
    base_top = max(b.h for b in base)
    base_low = min(b.l for b in base)
    mid = (base_top + base_low) / 2.0
    if mid <= 0:
        return None
    return -((base_top - base_low) / mid)  # higher (less negative) = tighter base


def days_since_breakout(bars: Sequence[Bar], asof: _dt.date,
                        base_lb: int = 40, excl_recent: int = 20) -> float | None:
    """How many bars ago price first closed above the base top — recency of the breakout. base_top =
    max HIGH over the base window (excluding the last excl_recent bars = the candidate breakout zone).
    Scans the last excl_recent bars for the FIRST close > base_top; returns (bars-ago) of that close.
    Small = fresh breakout (early, room to run); large = broke out long ago (extended/late). Returns
    excl_recent (the cap) if no breakout close is found in the window. None if insufficient history."""
    w = fp._asof(bars, asof)
    if len(w) < base_lb + excl_recent + 1:
        return None
    base = w[-(base_lb + excl_recent):-excl_recent]
    if not base:
        return None
    base_top = max(b.h for b in base)
    recent = w[-excl_recent:]
    for i, b in enumerate(recent):
        if b.c > base_top:
            return float(len(recent) - 1 - i)  # bars-ago of the first breakout close
    return float(excl_recent)  # no breakout in window → treat as maximally stale


# ─────────────────────── 3. stage_room ───────────────────────

def stage_room(bars: Sequence[Bar], asof: _dt.date,
               base_lb: int = 40, excl_recent: int = 5,
               prior_high_months: int = 12, prior_excl: int = 2) -> float | None:
    """Early-with-room vs late-extended: distance-ABOVE-base ÷ distance-TO-prior-high.
      num = (entry_close − base_top) / entry_close      (how far above the base we've already run)
      den = (prior_high − entry_close) / entry_close    (how much headroom remains to the prior high)
    Small ratio (<1) = just left the base with the prior high still overhead (room to run); large /
    negative-den (price already above the prior high) = extended, little/no measured headroom = the
    late-chase shape. Returns the ratio; if headroom <= 0 (already above prior high) returns a large
    sentinel (no room). None if insufficient history."""
    w = fp._asof(bars, asof)
    base = _base_window(w, base_lb, excl_recent)
    if base is None:
        return None
    close = w[-1].c
    if close <= 0:
        return None
    base_top = max(b.h for b in base)
    dist_to_prior = fp.dist_to_prior_high(bars, asof, prior_high_months, prior_excl)
    if dist_to_prior is None:
        return None
    # dist_to_prior = close/prior_high - 1  → headroom fraction = -(dist_to_prior) when below prior high
    headroom = -dist_to_prior  # >0 if below prior high (room), <=0 if at/above it
    above_base = (close - base_top) / close
    if headroom <= 0:
        return 999.0  # already at/above the prior high → no measured room (late-extended sentinel)
    return above_base / headroom
