"""Runtime-safe scanner rank-history features.

The LambdaMART scanner is a daily ranked list. This helper turns repeated daily rank evidence into
same-day-safe persistence features without reading George labels, OCR, posts, videos, or future
returns. It stores only ranks/scores that the runtime model produced on or before the current
decision date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from engine.symbol_key import canonical_symbol_key


@dataclass(frozen=True, slots=True)
class RankHistoryInput:
    ticker: str
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class RankHistoryParams:
    short_window: int = 5
    long_window: int = 20
    focus_rank: int = 10
    core_rank: int = 20
    min_seen_short: int = 2
    min_seen_long: int = 3
    min_persistence_score: float = 0.85


def empty_rank_history_state() -> dict[str, Any]:
    return {"dates": [], "symbols": {}}


def date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def update_rank_history(
    state: dict[str, Any] | None,
    rows: list[RankHistoryInput],
    decision_date: Any,
    *,
    params: RankHistoryParams = RankHistoryParams(),
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Update rank history and return same-day-safe per-ticker feature context.

    Windows are observed ranker sessions, not calendar days. This avoids exchange-calendar
    dependencies and matches what the runtime actually saw.
    """
    current = date_key(decision_date)
    working = _coerce_state(state)
    dates = list(working["dates"])
    if current not in dates:
        dates.append(current)
    max_window = max(int(params.short_window), int(params.long_window), 1)
    kept_dates = dates[-max_window:]
    kept_date_set = set(kept_dates)
    working["dates"] = kept_dates

    symbols: dict[str, list[dict[str, Any]]] = working["symbols"]
    for row in rows:
        ticker = canonical_symbol_key(row.ticker)
        history = [item for item in symbols.get(ticker, []) if item.get("date") != current]
        history.append({"date": current, "rank": int(row.rank), "score": float(row.score)})
        symbols[ticker] = [item for item in history if item.get("date") in kept_date_set]

    stale = [ticker for ticker, history in symbols.items() if not history]
    for ticker in stale:
        symbols.pop(ticker, None)

    context: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = canonical_symbol_key(row.ticker)
        features = rank_history_features(symbols.get(ticker, []), kept_dates, params=params)
        context[ticker] = features
    return working, context


def rank_history_features(
    history: list[dict[str, Any]],
    observed_dates: list[str],
    *,
    params: RankHistoryParams = RankHistoryParams(),
) -> dict[str, Any]:
    if not history or not observed_dates:
        return _empty_features(params)

    by_date = {str(item["date"]): item for item in history}
    last_date = observed_dates[-1]
    last = by_date.get(last_date)
    if last is None:
        last = max(history, key=lambda item: observed_dates.index(str(item["date"])))

    short_dates = set(observed_dates[-max(int(params.short_window), 1):])
    long_dates = set(observed_dates[-max(int(params.long_window), 1):])
    short = [item for item in history if str(item["date"]) in short_dates]
    long = [item for item in history if str(item["date"]) in long_dates]

    previous = _previous_observation(history, observed_dates, str(last["date"]))
    last_rank = int(last["rank"])
    last_score = float(last["score"])
    best_short = min((int(item["rank"]) for item in short), default=0)
    best_long = min((int(item["rank"]) for item in long), default=0)
    days_seen_short = len(short)
    days_seen_long = len(long)
    days_since_top_focus = _days_since_rank_at_or_better(history, observed_dates, int(params.focus_rank))
    days_since_top_core = _days_since_rank_at_or_better(history, observed_dates, int(params.core_rank))
    previous_rank = int(previous["rank"]) if previous is not None else 0
    rank_trend = previous_rank - last_rank if previous_rank else 0
    persistence_score = _persistence_score(
        days_seen_short=days_seen_short,
        days_seen_long=days_seen_long,
        best_rank_long=best_long,
        params=params,
    )
    requalified, state = rank_history_requalification_state(
        {
            "last_rank": last_rank,
            "best_rank_last_5": best_short,
            "best_rank_last_20": best_long,
            "days_seen_last_5": days_seen_short,
            "days_seen_last_20": days_seen_long,
            "rank_persistence_score": persistence_score,
        },
        params=params,
    )
    return {
        "last_rank": last_rank,
        "last_score": last_score,
        "best_rank_last_5": best_short,
        "best_rank_last_20": best_long,
        "days_seen_last_5": days_seen_short,
        "days_seen_last_20": days_seen_long,
        "days_since_last_top10": days_since_top_focus,
        "days_since_last_top20": days_since_top_core,
        "rank_trend": rank_trend,
        "rank_persistence_score": persistence_score,
        "rank_requalified": requalified,
        "rank_requalification_state": state,
    }


def rank_history_requalification_state(
    features: dict[str, Any],
    *,
    params: RankHistoryParams = RankHistoryParams(),
) -> tuple[bool, str]:
    last_rank = int(features.get("last_rank") or 0)
    best_short = int(features.get("best_rank_last_5") or 0)
    best_long = int(features.get("best_rank_last_20") or 0)
    days_short = int(features.get("days_seen_last_5") or 0)
    days_long = int(features.get("days_seen_last_20") or 0)
    persistence = float(features.get("rank_persistence_score") or 0.0)

    if last_rank > 0 and last_rank <= int(params.focus_rank):
        return True, "today_focus"
    if best_short > 0 and best_short <= int(params.core_rank) and days_short >= int(params.min_seen_short):
        return True, "short_persistent_core"
    if best_long > 0 and best_long <= int(params.core_rank) and days_long >= int(params.min_seen_long):
        return True, "long_persistent_core"
    if persistence >= float(params.min_persistence_score):
        return True, "persistence_score"
    return False, "not_requalified"


def _coerce_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return empty_rank_history_state()
    dates = [str(item) for item in state.get("dates", [])]
    raw_symbols = state.get("symbols", {})
    symbols: dict[str, list[dict[str, Any]]] = {}
    if isinstance(raw_symbols, dict):
        for ticker, rows in raw_symbols.items():
            if isinstance(rows, list):
                clean: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if "date" not in row or "rank" not in row or "score" not in row:
                        continue
                    clean.append(
                        {
                            "date": str(row["date"]),
                            "rank": int(row["rank"]),
                            "score": float(row["score"]),
                        }
                    )
                symbols[canonical_symbol_key(ticker)] = clean
    return {"dates": dates, "symbols": symbols}


def _empty_features(params: RankHistoryParams) -> dict[str, Any]:
    return {
        "last_rank": 0,
        "last_score": 0.0,
        "best_rank_last_5": 0,
        "best_rank_last_20": 0,
        "days_seen_last_5": 0,
        "days_seen_last_20": 0,
        "days_since_last_top10": -1,
        "days_since_last_top20": -1,
        "rank_trend": 0,
        "rank_persistence_score": 0.0,
        "rank_requalified": False,
        "rank_requalification_state": "not_requalified",
        "_focus_rank": int(params.focus_rank),
        "_core_rank": int(params.core_rank),
    }


def _previous_observation(
    history: list[dict[str, Any]],
    observed_dates: list[str],
    current_date: str,
) -> dict[str, Any] | None:
    date_index = {value: index for index, value in enumerate(observed_dates)}
    current_index = date_index.get(current_date, len(observed_dates))
    prior = [
        item
        for item in history
        if date_index.get(str(item["date"]), -1) < current_index
    ]
    if not prior:
        return None
    return max(prior, key=lambda item: date_index.get(str(item["date"]), -1))


def _days_since_rank_at_or_better(
    history: list[dict[str, Any]],
    observed_dates: list[str],
    rank_threshold: int,
) -> int:
    date_index = {value: index for index, value in enumerate(observed_dates)}
    current_index = len(observed_dates) - 1
    qualifying = [
        date_index[str(item["date"])]
        for item in history
        if str(item["date"]) in date_index and int(item["rank"]) <= rank_threshold
    ]
    if not qualifying:
        return -1
    return current_index - max(qualifying)


def _persistence_score(
    *,
    days_seen_short: int,
    days_seen_long: int,
    best_rank_long: int,
    params: RankHistoryParams,
) -> float:
    short_component = days_seen_short / max(float(params.short_window), 1.0)
    long_component = days_seen_long / max(float(params.long_window), 1.0)
    if best_rank_long <= 0:
        rank_component = 0.0
    else:
        rank_component = max(0.0, (float(params.core_rank) + 1.0 - best_rank_long) / max(float(params.core_rank), 1.0))
    return round(short_component + 0.5 * long_component + rank_component, 6)
