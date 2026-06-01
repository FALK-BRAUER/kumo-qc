"""tests/harness/gdata_asserts.py — G-DATA assertion verbs (#260).

The real-data integration invariants as reusable asserts. Each is MUTATION-BITEABLE: it asserts
on a real computed quantity, so breaking the underlying engine code flips the assert (no #263
tautology). The degraded-path asserts are used in HEALTHY/DEGRADED pairs — a degraded assert is
only meaningful next to a healthy control proving the SAME seam can pass.
"""
from __future__ import annotations

from typing import Any, Callable

import pytest

from engine.base import DegradedDataError


def assert_selection_nonempty(ranked: Any, *, names_in: int, day: str) -> None:
    """NON-EMPTY where expected: a populated real session must select a non-empty, floored,
    strict-subset universe. An empty selection on a full feed is the #173 BROKEN-0 mirage."""
    assert names_in > 1000, f"{day}: coarse feed unexpectedly sparse ({names_in} rows) — not a real session"
    assert ranked, (
        f"{day}: BROKEN-0 — a populated feed ({names_in} names) selected an EMPTY universe "
        f"(the #173 empty-warmup mirage)"
    )
    assert len(ranked) < names_in, (
        f"{day}: selection ({len(ranked)}) is not a strict subset of {names_in} — the liquidity "
        f"floors did not bind"
    )


def assert_can_warm(*, weekly_bars: int, daily_bars: int, ticker: str) -> None:
    """WARM where expected: the binding pole is the 78-week weekly Ichimoku; the daily poles
    (200d SMA etc.) are shorter. A selected name that cannot reach these from its seed window
    would be COLD at its first score — the mirage."""
    assert weekly_bars >= 78, (
        f"{ticker}: seed produced only {weekly_bars} weekly bars (< 78 weekly-Ichimoku readiness) "
        f"— a post-warmup entrant would be COLD at first score (the mirage)"
    )
    assert daily_bars >= 200, (
        f"{ticker}: only {daily_bars} daily bars (< 200) — the 200d SMA (longest daily pole) "
        f"cannot warm from the seed"
    )


def assert_warm_scores(score: Any, *, ticker: str) -> None:
    """The chain payoff: a name that selection picked AND that warmed must be scoreable. A
    warm-but-None name is the rung-handoff break #260 exists to catch."""
    assert score is not None, (
        f"{ticker}: a selected, warmed name scored None — 'warm but unscoreable' is the "
        f"selection→warm→score chain break #260 guards"
    )


def assert_cold_cannot_score(score: Any, *, label: str) -> None:
    """The anti-mirage half: a not-ready input must yield None, never a number."""
    assert score is None, (
        f"cold input '{label}' produced a score ({score}) — 'silently scored cold' is the mirage; "
        f"a not-ready input MUST return None"
    )


def assert_crash_not_mirage(fn: Callable[[], Any], *, label: str, exc: type = DegradedDataError) -> None:
    """Degraded/outage data must CRASH LOUD, never silently produce an empty/mirage result.
    Pair every call with a healthy control on the same seam."""
    with pytest.raises(exc):
        fn()


def assert_coverage_not_zero(n_covered: int, *, window_label: str, universe_label: str) -> None:
    """THE #237 trap (the single most important assertion): a short window that covers 0 names
    must FAIL as non-coverage, never pass green. A 0-coverage window reading green is exactly the
    11-day Step-A mask that hid a full-FY sign flip — 0 coverage is RED, not a silent pass."""
    assert n_covered > 0, (
        f"ZERO-COVERAGE TRAP: window '{window_label}' covered 0 {universe_label} — a 0-coverage "
        f"window passing green is the #237 Step-A mask (a short window hiding a full-FY sign "
        f"flip). 0 coverage is RED, not a silent pass."
    )
