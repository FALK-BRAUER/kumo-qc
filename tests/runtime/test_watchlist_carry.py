from __future__ import annotations

from runtime.watchlist_carry import select_watchlist_carry


def test_watchlist_carry_selects_deterministically_and_bounds() -> None:
    watchlist = {
        "ATI": {"score": 2.0, "age_days": 3, "reason": "metals"},
        "CRS": {"score": 2.0, "age_days": 1, "reason": "metals"},
        "CRM": {"score": 3.0, "age_days": 8, "reason": "software"},
    }
    bar_metrics = {
        "ati": (40.0, 80_000_000.0),
        "crs": (42.0, 90_000_000.0),
        "crm": (260.0, 75_000_000.0),
    }

    carry, rejected = select_watchlist_carry(
        watchlist,
        bar_metrics,
        ranked=[],
        max_names=2,
        min_price=10.0,
        min_avg_dollar_volume=50_000_000.0,
    )

    assert [c.ticker for c in carry] == ["crm", "crs"]
    assert carry[0].score == 3.0
    assert carry[1].age_days == 1
    assert rejected == {}


def test_watchlist_carry_rejects_ineligible_names() -> None:
    watchlist = {
        "AAPL": {"score": 9.0},
        "MISSING": {"score": 8.0},
        "CHEAP": {"score": 7.0},
        "THIN": {"score": 6.0},
        "PASS": {"score": 5.0},
    }
    bar_metrics = {
        "aapl": (200.0, 5_000_000_000.0),
        "cheap": (8.0, 100_000_000.0),
        "thin": (50.0, 10_000_000.0),
        "pass": (50.0, 75_000_000.0),
    }

    carry, rejected = select_watchlist_carry(
        watchlist,
        bar_metrics,
        ranked=["aapl"],
        max_names=10,
        min_price=10.0,
        min_avg_dollar_volume=50_000_000.0,
    )

    assert [c.ticker for c in carry] == ["pass"]
    assert rejected == {
        "aapl": "already_ranked",
        "missing": "missing_bar_metrics",
        "cheap": "below_price_floor",
        "thin": "below_dv_floor",
    }


def test_watchlist_carry_disabled_is_noop() -> None:
    carry, rejected = select_watchlist_carry(
        {"ATI": {"score": 2.0}},
        {"ati": (40.0, 80_000_000.0)},
        ranked=[],
        max_names=0,
        min_price=10.0,
        min_avg_dollar_volume=50_000_000.0,
    )

    assert carry == []
    assert rejected == {}
