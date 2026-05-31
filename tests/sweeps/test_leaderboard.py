"""Leaderboard tests (#214 component 6) — ranking order + CSV/MD rendering."""
from __future__ import annotations

from sweeps.aggregate import aggregate
from sweeps.leaderboard import (
    LEADERBOARD_COLUMNS,
    build_leaderboard,
    to_csv,
    to_markdown,
)
from sweeps.score import score
from sweeps.types import ConfigRun, PhaseChoice, ResultMetrics, SweepConfig, Window, WindowResult


def _scored(sharpes: list[float], *, free_params: int = 1, salt: str = "a"):  # type: ignore[no-untyped-def]
    cfg = SweepConfig(choices=(PhaseChoice("signal", "Mock", ((salt, 1),), free_params),))
    wrs = tuple(
        WindowResult(
            window=Window(name=f"w{i}", start="", end=""),
            metrics=ResultMetrics(sharpe=s, ret_pct=s * 5, dd_pct=10.0, orders=10),
        )
        for i, s in enumerate(sharpes)
    )
    return score(aggregate(ConfigRun(config=cfg, window_results=wrs)))


def test_leaderboard_ranks_by_composite_desc() -> None:
    steady = _scored([3, 3, 3, 3, 3, 3], salt="steady")
    peaky = _scored([0, 0, 0, 0, 0, 12], salt="peaky")
    mid = _scored([2, 2, 2, 2, 2, 4], salt="mid")
    rows = build_leaderboard([peaky, steady, mid])
    # Ranked DESC by composite; ranks are 1-based contiguous.
    assert [r.rank for r in rows] == [1, 2, 3]
    composites = [r.scored.composite for r in rows]
    assert composites == sorted(composites, reverse=True)
    # Steady (high stability, ~0 variance) tops the board over the high-peak config.
    assert rows[0].scored.config_hash == steady.config_hash


def test_leaderboard_tie_breaks_on_simplicity_then_hash() -> None:
    # Identical distributions, different DoF -> simpler ranks first (lower complexity penalty
    # actually gives a higher composite, but assert the Occam ordering holds).
    simple = _scored([4, 4, 4, 4, 4, 4], free_params=1, salt="x")
    complex_ = _scored([4, 4, 4, 4, 4, 4], free_params=5, salt="y")
    rows = build_leaderboard([complex_, simple])
    assert rows[0].scored.config_hash == simple.config_hash


def test_leaderboard_deterministic_on_repeat() -> None:
    items = [_scored([1, 2, 3, 4, 5, 6], salt=s) for s in ("a", "b", "c")]
    r1 = [r.config_hash for r in build_leaderboard(items)]
    r2 = [r.config_hash for r in build_leaderboard(list(reversed(items)))]
    # Same set of scored configs -> same ranking regardless of input order.
    assert r1 == r2


def test_csv_has_metrics_trio_columns() -> None:
    assert "sharpe_mean" in LEADERBOARD_COLUMNS
    assert "ret_pct_mean" in LEADERBOARD_COLUMNS
    assert "dd_pct_mean" in LEADERBOARD_COLUMNS
    rows = build_leaderboard([_scored([1, 2, 3, 4, 5, 6])])
    csv_text = to_csv(rows)
    header = csv_text.splitlines()[0]
    assert header == ",".join(LEADERBOARD_COLUMNS)
    assert len(csv_text.splitlines()) == 2  # header + 1 row


def test_markdown_renders_table() -> None:
    rows = build_leaderboard([_scored([1, 2, 3, 4, 5, 6])])
    md = to_markdown(rows)
    assert md.startswith("| rank |")
    assert "config_hash" in md
    assert md.count("\n") >= 3  # header + sep + >=1 row
