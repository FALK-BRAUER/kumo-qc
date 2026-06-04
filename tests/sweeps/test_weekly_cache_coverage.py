"""#370 — the weekly-cache COVERAGE invariant (the regression test that would have caught NVD@02-18).

The bug: build_ticker_scalars gates row emission on the full 15-scalar readiness (incl len(adx_hist)==4,
which fills 3 days AFTER weekly.is_ready) → it DROPS the first weekly-ready days. The runtime's weekly
lookup (_weekly_scalars_for) needs ONLY weekly.is_ready → it requests those dropped days → cache miss →
WeeklyCacheGapError. build_weekly_scalars emits on weekly.is_ready ALONE → coverage == the runtime's
lookup set, by construction.

These tests assert (HQ re-review focuses): coverage EXACTLY == {weekly.is_ready} (no over/under-emit),
VALUES identical to the port (the early days carry correct weekly scalars), and build_weekly ⊋ build_ticker
on the first-post-weekly-ready days (the gap the fix closes). A normal week wouldn't catch it — the NVD
Presidents-Day-shortened week (02-18) is the canonical case (gdata, real data)."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from sweeps.warmup_cache.lean_indicators import WeeklyIchimokuAsOf
from sweeps.warmup_cache.table_builder import (
    WEEKLY_CACHE_FIELDS,
    build_ticker_scalars,
    build_weekly_scalars,
    read_daily_zip,
)

_NVD = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily/nvd.zip")


def _weekday_series(n: int, start: _dt.date = _dt.date(2022, 1, 3)) -> list[tuple]:
    """n weekday OHLCV bars (gently trending so the weekly Ichimoku becomes ready)."""
    out: list[tuple] = []
    d, i = start, 0
    while len(out) < n:
        if d.weekday() < 5:
            c = 100.0 + i * 0.13
            out.append((d, c, c + 1.0, c - 1.0, c, 1_000_000))
            i += 1
        d += _dt.timedelta(days=1)
    return out


def _weekly_ready_dates(bars: list[tuple]) -> set[_dt.date]:
    """The dates where the runtime's WeeklyIchimokuAsOf (same port) is_ready as-of that bar."""
    w = WeeklyIchimokuAsOf()
    ready = set()
    for d, o, h, l, c, _v in bars:
        w.update(d, o, h, l, c)
        if w.is_ready:
            ready.add(d)
    return ready


def test_coverage_equals_weekly_ready_set_exactly() -> None:
    """build_weekly_scalars emits EXACTLY the dates the runtime deems weekly-computable — no over-emit
    (dates the runtime never queries), no under-emit (the bug)."""
    bars = _weekday_series(650)  # ~130 weeks > 78 → weekly becomes ready partway
    emitted = {d for d, _sc in build_weekly_scalars(iter(bars))}
    expected = _weekly_ready_dates(bars)
    assert emitted == expected
    assert emitted, "fixture too short — weekly never became ready"


def test_values_match_the_port() -> None:
    """The weekly scalar VALUES build_weekly_scalars emits == the port's (they depend only on the weekly
    bars, NOT on adx_hist) → the early-emitted days carry correct values, not placeholders."""
    bars = _weekday_series(650)
    w = WeeklyIchimokuAsOf()
    ref: dict[_dt.date, dict] = {}
    for d, o, h, l, c, _v in bars:
        w.update(d, o, h, l, c)
        if w.is_ready:
            ref[d] = {"w_tenkan": w.tenkan, "w_kijun": w.kijun, "w_senkou_a": w.senkou_a,
                      "w_senkou_b": w.senkou_b, "w_close_0": w.w_close(0), "w_close_26": w.w_close(26)}
    for d, sc in build_weekly_scalars(iter(bars)):
        assert set(sc) == set(WEEKLY_CACHE_FIELDS)
        assert sc == ref[d]


def test_weekly_superset_of_full_row_on_early_days() -> None:
    """build_weekly_scalars ⊇ build_ticker_scalars dates, and STRICTLY so on the first weekly-ready days
    (the full-row adx_hist==4 gate drops them) — the exact gap the fix closes."""
    bars = _weekday_series(650)
    wk = {d for d, _ in build_weekly_scalars(iter(bars))}
    full = {d for d, _ in build_ticker_scalars(iter(bars))}
    assert full <= wk                       # weekly cache covers everything the full row does
    assert (wk - full)                      # ...and strictly more (the dropped first-weekly-ready days)
    assert min(wk) < min(full)              # weekly emits BEFORE the full row (the 3-day adx_hist lag)


@pytest.mark.gdata
def test_nvd_presidents_day_week_covered() -> None:
    """THE canonical regression (NVD@2025-02-18, Presidents-Day-shortened week): build_weekly_scalars
    MUST cover it; build_ticker_scalars (the old cache path) does NOT (proving the bug was real + the
    fix necessary). Skips when the gitignored daily data is absent."""
    if not _NVD.exists():
        pytest.skip("NVD daily zip absent (gitignored data tree)")
    target = _dt.date(2025, 2, 18)
    wk = {d for d, _ in build_weekly_scalars(read_daily_zip(_NVD))}
    full = {d for d, _ in build_ticker_scalars(read_daily_zip(_NVD))}
    assert target in wk, "build_weekly_scalars must cover NVD@2025-02-18 (the runtime queries it)"
    assert target not in full, "build_ticker_scalars drops it (the full-row gate) — the bug being fixed"
