"""#358b warmup-skip — table_builder d_cloud_bottom field: the daily cloud-BOTTOM = MIN(senkou_a,b),
the value the EXIT (CloudAdherenceTrail) reads. Proves it's the MIN (distinct from d_cloud_top=MAX),
so the exit consumer can be cache-fed for the full set_warmup skip. CI-safe (synthetic series)."""
from __future__ import annotations

import datetime as _dt
import math

from sweeps.warmup_cache.table_builder import SCALAR_FIELDS, build_ticker_scalars


def _series(n: int = 700) -> list[tuple]:
    """Deterministic trend+oscillation daily series (weekdays) → senkou_a != senkou_b on many rows
    (so cloud-bottom < cloud-top is exercised, distinguishing MIN from a MAX dup)."""
    d = _dt.date(2020, 1, 1)
    out: list[tuple] = []
    for i in range(n):
        while d.weekday() >= 5:
            d += _dt.timedelta(days=1)
        base = 100.0 + i * 0.1 + 8.0 * math.sin(i / 15.0)
        out.append((d, base, base + 1.5, base - 1.5, base + 0.3, 1_000_000))
        d += _dt.timedelta(days=1)
    return out


def test_cloud_bottom_field_present():
    assert "d_cloud_bottom" in SCALAR_FIELDS


def test_cloud_bottom_is_min_not_max():
    rows = list(build_ticker_scalars(_series()))
    assert rows, "no ready rows emitted"
    strict = 0
    for _d, sc in rows:
        assert "d_cloud_bottom" in sc
        assert sc["d_cloud_bottom"] <= sc["d_cloud_top"]          # MIN <= MAX, always
        if sc["d_cloud_bottom"] < sc["d_cloud_top"]:
            strict += 1
    # if d_cloud_bottom were a dup of MAX, bottom == top on every row → strict == 0
    assert strict > 0, "cloud_bottom never < cloud_top — not the MIN(senkou_a,b)"
