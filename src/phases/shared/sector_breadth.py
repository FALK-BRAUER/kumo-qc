"""Pure sector/industry breadth features for live scanner candidate panels.

These helpers consume only same-day candidate rows and optional runtime taxonomy maps. They do
not read files, George/BCT evidence, OCR labels, transcripts, or learned model scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, nan
from statistics import median
from typing import Any

from engine.symbol_key import canonical_symbol_key

UNKNOWN_GROUP = "unknown"


@dataclass(frozen=True, slots=True)
class BreadthCandidate:
    ticker: str
    bct_score: float | None = None
    day_return_pct: float | None = None
    rel_volume20: float | None = None
    sector: str | None = None
    industry: str | None = None


@dataclass(frozen=True, slots=True)
class _GroupMetrics:
    denominator_count: int
    bct6_count: int
    bct7_count: int
    positive_return_count: int
    median_day_return_pct: float
    median_rel_volume20: float

    @property
    def bct6_pct(self) -> float:
        return _pct(self.bct6_count, self.denominator_count)

    @property
    def bct7_pct(self) -> float:
        return _pct(self.bct7_count, self.denominator_count)

    @property
    def positive_return_pct(self) -> float:
        return _pct(self.positive_return_count, self.denominator_count)


ZERO_METRICS = _GroupMetrics(
    denominator_count=0,
    bct6_count=0,
    bct7_count=0,
    positive_return_count=0,
    median_day_return_pct=0.0,
    median_rel_volume20=nan,
)


def _clean_group(value: Any) -> str:
    if value is None:
        return UNKNOWN_GROUP
    text = str(value).strip().lower()
    return text or UNKNOWN_GROUP


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _pct(part: int, total: int) -> float:
    return 100.0 * float(part) / float(total) if total else 0.0


def _median_or_zero(values: list[float]) -> float:
    return float(median(values)) if values else 0.0


def _industry_key(sector_key: str, industry: str | None) -> str:
    return f"{sector_key}|{_clean_group(industry)}"


def _candidate_with_maps(
    candidate: BreadthCandidate,
    *,
    sector_by_ticker: dict[Any, Any] | None,
    industry_by_ticker: dict[Any, Any] | None,
) -> BreadthCandidate:
    ticker_key = canonical_symbol_key(candidate.ticker)
    sector = candidate.sector
    industry = candidate.industry
    if sector is None and sector_by_ticker:
        sector = sector_by_ticker.get(ticker_key, sector_by_ticker.get(candidate.ticker))
    if industry is None and industry_by_ticker:
        industry = industry_by_ticker.get(ticker_key, industry_by_ticker.get(candidate.ticker))
    return BreadthCandidate(
        ticker=ticker_key,
        bct_score=candidate.bct_score,
        day_return_pct=candidate.day_return_pct,
        rel_volume20=candidate.rel_volume20,
        sector=sector,
        industry=industry,
    )


def _build_group_metrics(candidates: list[BreadthCandidate]) -> _GroupMetrics:
    scores = [_finite_float(candidate.bct_score) or 0.0 for candidate in candidates]
    returns = [_finite_float(candidate.day_return_pct) for candidate in candidates]
    rel_volumes = [_finite_float(candidate.rel_volume20) for candidate in candidates]
    finite_returns = [value for value in returns if value is not None]
    finite_rel_volumes = [value for value in rel_volumes if value is not None]
    return _GroupMetrics(
        denominator_count=len(candidates),
        bct6_count=sum(1 for score in scores if score >= 6.0),
        bct7_count=sum(1 for score in scores if score >= 7.0),
        positive_return_count=sum(1 for value in finite_returns if value > 0.0),
        median_day_return_pct=_median_or_zero(finite_returns),
        median_rel_volume20=_median_or_zero(finite_rel_volumes),
    )


def _metrics_features(prefix: str, metrics: _GroupMetrics) -> dict[str, float | int]:
    return {
        f"{prefix}_denominator_count": metrics.denominator_count,
        f"{prefix}_bct6_count": metrics.bct6_count,
        f"{prefix}_bct7_count": metrics.bct7_count,
        f"{prefix}_positive_return_count": metrics.positive_return_count,
        f"{prefix}_median_day_return_pct": metrics.median_day_return_pct,
        f"{prefix}_median_rel_volume20": metrics.median_rel_volume20,
        f"{prefix}_bct6_pct": metrics.bct6_pct,
        f"{prefix}_bct7_pct": metrics.bct7_pct,
        f"{prefix}_positive_return_pct": metrics.positive_return_pct,
    }


def sector_industry_breadth_rows(
    candidates: list[BreadthCandidate],
    *,
    sector_by_ticker: dict[Any, Any] | None = None,
    industry_by_ticker: dict[Any, Any] | None = None,
) -> list[dict[str, str | float | int]]:
    """Return sector/industry breadth features in the same order as `candidates`.

    The input is expected to be one date's live scanner candidate panel. Callers that hold
    multi-date research frames should call this once per date so each date has its own denominator.
    """
    resolved = [
        _candidate_with_maps(
            candidate,
            sector_by_ticker=sector_by_ticker,
            industry_by_ticker=industry_by_ticker,
        )
        for candidate in candidates
    ]
    sector_groups: dict[str, list[BreadthCandidate]] = {}
    industry_groups: dict[str, list[BreadthCandidate]] = {}
    candidate_keys: list[tuple[str, str]] = []
    for candidate in resolved:
        sector_key = _clean_group(candidate.sector)
        industry_key = _industry_key(sector_key, candidate.industry)
        if sector_key != UNKNOWN_GROUP:
            sector_groups.setdefault(sector_key, []).append(candidate)
        if sector_key != UNKNOWN_GROUP and _clean_group(candidate.industry) != UNKNOWN_GROUP:
            industry_groups.setdefault(industry_key, []).append(candidate)
        candidate_keys.append((sector_key, industry_key))

    sector_metrics = {key: _build_group_metrics(rows) for key, rows in sector_groups.items()}
    industry_metrics = {key: _build_group_metrics(rows) for key, rows in industry_groups.items()}
    features: list[dict[str, str | float | int]] = []
    for sector_key, industry_key in candidate_keys:
        row: dict[str, str | float | int] = {
            "sector_key": sector_key,
            "industry_key": industry_key,
        }
        row.update(_metrics_features("sector", sector_metrics.get(sector_key, ZERO_METRICS)))
        row.update(_metrics_features("industry", industry_metrics.get(industry_key, ZERO_METRICS)))
        features.append(row)
    return features
