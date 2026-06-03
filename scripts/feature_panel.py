"""#349 feature-discovery panel — pure as-of-date entry features + discrimination grading.

For every candidate (entered + non-entered) compute a panel of entry features AS-OF the candidate's
decision date (NO look-ahead — only bars with date <= asof), then grade each feature by how well it
separates forward-winners from forward-losers, in Q1 AND Q3 (robustness gate).

HARD CONSTRAINTS (#349):
- NO LOOK-AHEAD: `_asof(bars, asof)` slices to date <= asof; features touch ONLY that slice. A feature
  that would need a future bar returns None (insufficient) — never reaches forward.
- forward-return (the label) is graded-on ONLY, never an input to a feature.
- missing/insufficient data → fail-loud (None → the caller drops the row + counts it; never silent 0).

Each feature: bars (list[Bar] ASC, Bar=(date,o,h,l,c,v)) + asof → float | None. SPY/score/conditions
that aren't bar-derived are passed by the caller. Grading: Spearman rank-corr + top/bottom-quartile AUC.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import NamedTuple, Sequence


class Bar(NamedTuple):
    d: _dt.date
    o: float
    h: float
    l: float
    c: float
    v: float


def _asof(bars: Sequence[Bar], asof: _dt.date) -> list[Bar]:
    """Bars with date <= asof (NO look-ahead). Empty if none."""
    return [b for b in bars if b.d <= asof]


# ─────────────────────────── pure features (as-of) ───────────────────────────

def roc(bars: Sequence[Bar], asof: _dt.date, n: int) -> float | None:
    """n-bar rate-of-change of close, as-of. None if < n+1 bars."""
    w = _asof(bars, asof)
    if len(w) < n + 1:
        return None
    past = w[-1 - n].c
    if past <= 0:
        return None
    return w[-1].c / past - 1.0


def dist_to_high(bars: Sequence[Bar], asof: _dt.date, lookback: int | None) -> float | None:
    """(close / max-high-over-lookback) - 1 (<=0; 0 = at the high). lookback None = all history (ATH)."""
    w = _asof(bars, asof)
    if not w:
        return None
    window = w if lookback is None else w[-lookback:]
    hi = max(b.h for b in window)
    if hi <= 0:
        return None
    return w[-1].c / hi - 1.0


def daily_open_close(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Entry-day continuation proxy: (close - open)/open on the as-of bar. None if no bar/zero open."""
    w = _asof(bars, asof)
    if not w or w[-1].o <= 0:
        return None
    return (w[-1].c - w[-1].o) / w[-1].o


def gap(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Entry-day gap: (open / prev-close) - 1. None if < 2 bars / zero prev-close."""
    w = _asof(bars, asof)
    if len(w) < 2 or w[-2].c <= 0:
        return None
    return w[-1].o / w[-2].c - 1.0


def volume_surge(bars: Sequence[Bar], asof: _dt.date, n: int = 20) -> float | None:
    """Entry-day volume / trailing n-bar mean volume (excluding the entry bar). None if < n+1 bars."""
    w = _asof(bars, asof)
    if len(w) < n + 1:
        return None
    base = sum(b.v for b in w[-1 - n:-1]) / n
    if base <= 0:
        return None
    return w[-1].v / base


def trend_persistence(bars: Sequence[Bar], asof: _dt.date, n: int = 20) -> float | None:
    """Fraction of the last n bars that closed UP vs the prior close (0..1). None if < n+1 bars."""
    w = _asof(bars, asof)
    if len(w) < n + 1:
        return None
    ups = sum(1 for i in range(len(w) - n, len(w)) if w[i].c > w[i - 1].c)
    return ups / n


def trend_slope_r2(bars: Sequence[Bar], asof: _dt.date, n: int = 63) -> tuple[float, float] | None:
    """OLS of the last n closes vs index → (normalised slope = slope/mean_close, R²). The R² is the
    'continuous-growth vs choppy' detector (high R² = clean trend). None if < n bars or degenerate."""
    w = _asof(bars, asof)
    if len(w) < n:
        return None
    ys = [b.c for b in w[-n:]]
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0 or my <= 0:
        return None
    slope = sxy / sxx
    r2 = (sxy * sxy) / (sxx * syy)
    return slope / my, r2


def rs_vs_benchmark(bars: Sequence[Bar], bench: Sequence[Bar], asof: _dt.date, n: int) -> float | None:
    """Relative strength: name n-bar RoC minus benchmark (SPY) n-bar RoC, both as-of. None if either short."""
    a = roc(bars, asof, n)
    b = roc(bench, asof, n)
    if a is None or b is None:
        return None
    return a - b


def liquidity_dollar_vol(bars: Sequence[Bar], asof: _dt.date, n: int = 20) -> float | None:
    """Trailing n-bar mean dollar-volume (close × volume) as-of. The size proxy (mcap unavailable)."""
    w = _asof(bars, asof)
    if len(w) < n:
        return None
    return sum(b.c * b.v for b in w[-n:]) / n


def price_level(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """As-of close (raw price level — a weak size/penny proxy)."""
    w = _asof(bars, asof)
    return w[-1].c if w else None


def _weekly(bars: Sequence[Bar]) -> list[Bar]:
    """Aggregate daily bars → weekly (ISO year-week): open=first, high=max, low=min, close=last, vol=sum.
    Bar.d of each weekly = the LAST daily date in that week (so as-of slicing stays correct)."""
    buckets: dict[tuple[int, int], list[Bar]] = {}
    order: list[tuple[int, int]] = []
    for b in bars:
        key = b.d.isocalendar()[:2]
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(b)
    out = []
    for key in order:
        wk = buckets[key]
        out.append(Bar(wk[-1].d, wk[0].o, max(x.h for x in wk), min(x.l for x in wk),
                       wk[-1].c, sum(x.v for x in wk)))
    return out


def _monthly(bars: Sequence[Bar]) -> list[Bar]:
    """Aggregate daily → monthly (year-month): open=first, high=max, low=min, close=last, vol=sum.
    Each monthly Bar.d = the LAST daily date in that month (as-of slicing stays correct)."""
    buckets: dict[tuple[int, int], list[Bar]] = {}
    order: list[tuple[int, int]] = []
    for b in bars:
        key = (b.d.year, b.d.month)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(b)
    out = []
    for key in order:
        mb = buckets[key]
        out.append(Bar(mb[-1].d, mb[0].o, max(x.h for x in mb), min(x.l for x in mb),
                       mb[-1].c, sum(x.v for x in mb)))
    return out


def continuous_growth(bars: Sequence[Bar], asof: _dt.date, n_months: int = 12) -> float | None:
    """Falk 1a — CONTINUOUS-GROWTH setup: clean-ness of the MONTHLY uptrend over the last n_months.
    Signed R² of the monthly-close trend: +R² for a clean UPtrend, −R² for a clean downtrend, ~0 for
    choppy. (A clean monthly uptrend = high +value.) None if < n_months monthly candles."""
    m = _monthly([b for b in bars if b.d <= asof])
    if len(m) < n_months:
        return None
    sl = trend_slope_r2(m, m[-1].d, n_months)
    if sl is None:
        return None
    slope, r2 = sl
    return r2 if slope > 0 else -r2


def dist_to_prior_high(bars: Sequence[Bar], asof: _dt.date,
                       lookback_months: int = 12, excl_recent: int = 2) -> float | None:
    """Falk 1b+2 — PREVIOUS-HIGH-TO-RETURN-TO / RESISTANCE-CLEARANCE: close vs the prior monthly swing
    high (max monthly HIGH over the lookback EXCLUDING the last `excl_recent` months, so it's a PRIOR
    high, not the current run's). close/prior_high − 1: ~0 = testing the prior high as support (return-
    to); >0 = broke above it (cleared, open sky); <<0 = far below. (Generic dist_to_52wk_high can't —
    it's always <=0; excluding-recent makes this SIGNED.) None if insufficient monthly history."""
    m = _monthly([b for b in bars if b.d <= asof])
    if len(m) < excl_recent + 1:
        return None
    prior = m[-(lookback_months + excl_recent):-excl_recent] if excl_recent > 0 else m[-lookback_months:]
    if not prior:
        return None
    prior_high = max(b.h for b in prior)
    if prior_high <= 0:
        return None
    return m[-1].c / prior_high - 1.0


def ichimoku_cloud_pos(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Continuous Ichimoku regime: (close − cloud_bottom)/close as-of (>0 above the Kumo floor, <0
    below). The cloud_bottom = min(Senkou A, B) PLOTTED UNDER today (displaced 26 back) — same geometry
    as floor_proxy. None until the Ichimoku is ready. Reusable for daily (SPY) or weekly bars."""
    from sweeps.warmup_cache.lean_indicators import Ichimoku  # noqa: PLC0415
    w = _asof(bars, asof)
    ich = Ichimoku()
    last = None
    for b in w:
        ich.update(b.h, b.l, b.c)
        if ich.is_ready:
            last = (b.c, min(ich.senkou_a, ich.senkou_b))
    if last is None or last[0] <= 0:
        return None
    return (last[0] - last[1]) / last[0]


def weekly_ichimoku_pos(bars: Sequence[Bar], asof: _dt.date) -> float | None:
    """Ichimoku cloud position on WEEKLY-aggregated bars, as-of (the weekly regime feature)."""
    return ichimoku_cloud_pos(_weekly([b for b in bars if b.d <= asof]), asof)


# ─────────────────────────── grading metrics ───────────────────────────

def _rank(xs: list[float]) -> list[float]:
    """Average ranks (ties → mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(feature: list[float], label: list[float]) -> float | None:
    """Spearman rank-correlation between a feature and the forward-return label. None if < 3 pairs or
    a constant input (no discrimination possible)."""
    if len(feature) != len(label):
        raise ValueError("feature/label length mismatch")
    if len(feature) < 3:
        return None
    rf, rl = _rank(feature), _rank(label)
    n = len(rf)
    mf = sum(rf) / n
    ml = sum(rl) / n
    cov = sum((a - mf) * (b - ml) for a, b in zip(rf, rl))
    vf = sum((a - mf) ** 2 for a in rf)
    vl = sum((b - ml) ** 2 for b in rl)
    if vf <= 0 or vl <= 0:
        return None
    return cov / math.sqrt(vf * vl)


def quartile_auc(feature: list[float], label: list[float]) -> float | None:
    """AUC-style separation: P(feature higher for a top-quartile-label item than a bottom-quartile one).
    0.5 = no separation, 1.0 = feature perfectly ranks top above bottom. None if quartiles too small."""
    if len(feature) != len(label):
        raise ValueError("feature/label length mismatch")
    n = len(label)
    if n < 8:
        return None
    order = sorted(range(n), key=lambda i: label[i])
    q = max(1, n // 4)
    bottom = [feature[i] for i in order[:q]]
    top = [feature[i] for i in order[-q:]]
    wins = ties = 0
    for t in top:
        for b in bottom:
            if t > b:
                wins += 1
            elif t == b:
                ties += 1
    denom = len(top) * len(bottom)
    return (wins + 0.5 * ties) / denom if denom else None
