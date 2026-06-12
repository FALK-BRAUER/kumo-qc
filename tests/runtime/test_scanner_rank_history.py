from __future__ import annotations

from runtime.scanner_rank_history import (
    RankHistoryInput,
    RankHistoryParams,
    rank_history_requalification_state,
    update_rank_history,
)


def _row(ticker: str, rank: int, score: float = 1.0) -> RankHistoryInput:
    return RankHistoryInput(ticker=ticker, rank=rank, score=score)


def test_rank_history_uses_observed_sessions_and_prunes_old_rows() -> None:
    params = RankHistoryParams(short_window=2, long_window=3, focus_rank=1, core_rank=3)
    state: dict[str, object] | None = None

    state, ctx1 = update_rank_history(state, [_row("AAA", 1), _row("BBB", 3)], "2025-01-02", params=params)
    state, ctx2 = update_rank_history(state, [_row("AAA", 2), _row("BBB", 4)], "2025-01-06", params=params)
    state, ctx3 = update_rank_history(state, [_row("AAA", 5), _row("BBB", 2)], "2025-01-07", params=params)
    state, ctx4 = update_rank_history(state, [_row("AAA", 6), _row("BBB", 2)], "2025-01-08", params=params)

    assert ctx1["aaa"]["rank_requalification_state"] == "today_focus"
    assert ctx2["bbb"]["days_seen_last_5"] == 2
    assert ctx3["aaa"]["best_rank_last_20"] == 1
    assert ctx4["aaa"]["best_rank_last_20"] == 2
    assert ctx4["aaa"]["days_seen_last_20"] == 3
    assert state["dates"] == ["2025-01-06", "2025-01-07", "2025-01-08"]
    assert [row["date"] for row in state["symbols"]["aaa"]] == [
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
    ]


def test_rank_history_trend_and_top_rank_age_are_same_day_safe() -> None:
    params = RankHistoryParams(short_window=5, long_window=20, focus_rank=2, core_rank=5)
    state: dict[str, object] | None = None

    state, _ = update_rank_history(state, [_row("AAA", 8)], "2025-01-02", params=params)
    state, _ = update_rank_history(state, [_row("AAA", 4)], "2025-01-03", params=params)
    state, ctx = update_rank_history(state, [_row("AAA", 3)], "2025-01-06", params=params)

    features = ctx["aaa"]
    assert features["last_rank"] == 3
    assert features["rank_trend"] == 1
    assert features["days_since_last_top10"] == -1
    assert features["days_since_last_top20"] == 0
    assert features["rank_requalification_state"] == "short_persistent_core"


def test_rank_history_requalification_state_prefers_current_focus_then_persistence() -> None:
    params = RankHistoryParams(focus_rank=2, core_rank=5, min_seen_short=2, min_seen_long=4)

    assert rank_history_requalification_state(
        {"last_rank": 1, "best_rank_last_5": 1, "best_rank_last_20": 1},
        params=params,
    ) == (True, "today_focus")
    assert rank_history_requalification_state(
        {
            "last_rank": 9,
            "best_rank_last_5": 5,
            "best_rank_last_20": 5,
            "days_seen_last_5": 2,
            "days_seen_last_20": 2,
        },
        params=params,
    ) == (True, "short_persistent_core")
    assert rank_history_requalification_state(
        {
            "last_rank": 9,
            "best_rank_last_5": 9,
            "best_rank_last_20": 9,
            "days_seen_last_5": 1,
            "days_seen_last_20": 1,
            "rank_persistence_score": 0.1,
        },
        params=params,
    ) == (False, "not_requalified")
