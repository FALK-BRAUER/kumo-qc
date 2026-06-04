"""#372 — as-of (NO look-ahead) unit test for the SHAPE feature panel.

For every shape feature: compute it on a real-ish daily series as-of a fixed date, then APPEND a pile
of wild future bars (huge spikes, far past asof) and recompute as-of the SAME date. The value MUST be
byte-identical — proving the feature reads only bars with date <= asof and a future bar can never leak.

Run: cd /Users/falk/projects/kumo-qc-362 && python3 scripts/test_372_shape_asof.py
"""
from __future__ import annotations

import datetime as _dt
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

import feature_panel_shape as shp
from feature_panel import Bar

_FEATURES = {
    "mtf_slope_daily": lambda b, a: shp.mtf_slope_daily(b, a, 20),
    "mtf_slope_weekly": lambda b, a: shp.mtf_slope_weekly(b, a, 12),
    "mtf_slope_monthly": lambda b, a: shp.mtf_slope_monthly(b, a, 6),
    "mtf_agreement": shp.mtf_agreement,
    "mtf_slope_dispersion": shp.mtf_slope_dispersion,
    "extension_above_base": lambda b, a: shp.extension_above_base(b, a, 40, 5),
    "parabolic_accel": lambda b, a: shp.parabolic_accel(b, a, 5),
    "range_expansion": lambda b, a: shp.range_expansion(b, a, 5, 20),
    "consolidation_quality": lambda b, a: shp.consolidation_quality(b, a, 40, 5),
    "days_since_breakout": lambda b, a: shp.days_since_breakout(b, a, 40, 20),
    "stage_room": lambda b, a: shp.stage_room(b, a),
}


def _series(n: int, start: _dt.date) -> list[Bar]:
    """A deterministic non-trivial daily series: rising base + a recent steepening leg + noise."""
    bars = []
    d = start
    price = 50.0
    for i in range(n):
        # base drift + a parabolic kick in the last ~10 bars
        drift = 0.002 if i < n - 10 else 0.02 + 0.004 * (i - (n - 10))
        wobble = math.sin(i * 0.7) * 0.6
        o = price
        price = price * (1 + drift) + wobble
        c = price
        h = max(o, c) + 0.5 + abs(wobble)
        l = min(o, c) - 0.5 - abs(wobble) * 0.5
        v = 1_000_000 + (i % 7) * 50_000 + (300_000 if i >= n - 10 else 0)
        bars.append(Bar(d, o, h, l, c, max(v, 1.0)))
        d += _dt.timedelta(days=1)
        while d.weekday() >= 5:  # skip weekends so weekly/monthly aggregation is realistic
            d += _dt.timedelta(days=1)
    return bars


def _wild_future(asof: _dt.date) -> list[Bar]:
    """Bars strictly AFTER asof, with absurd values — must never affect an as-of computation."""
    out = []
    d = asof + _dt.timedelta(days=1)
    for i in range(60):
        spike = 1e6 if i % 2 == 0 else -1e3
        out.append(Bar(d, spike, spike + 5e5, spike - 5e5, spike, 9e9))
        d += _dt.timedelta(days=1)
    return out


def main() -> int:
    bars = _series(400, _dt.date(2023, 1, 2))
    asof = bars[300].d  # a date well inside the series so all features have history
    future = _wild_future(asof)
    polluted = bars + future

    fails = []
    for name, fn in _FEATURES.items():
        v_clean = fn(bars, asof)
        v_poll = fn(polluted, asof)
        ok = (v_clean is None and v_poll is None) or (
            v_clean is not None and v_poll is not None and abs(v_clean - v_poll) < 1e-12
        )
        status = "OK " if ok else "LEAK"
        print(f"  [{status}] {name:24} clean={v_clean!r:>22}  +future={v_poll!r:>22}")
        if not ok:
            fails.append(name)
        if v_clean is None:
            fails.append(f"{name} (None on a series that should have history)")

    if fails:
        print(f"\nFAILED: {fails}")
        return 1
    print("\nALL SHAPE FEATURES as-of-safe (future bars do not change any value) and non-None.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
