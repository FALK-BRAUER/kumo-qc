"""Stage-by-stage George-label coverage audit for the local QC scanner substrate.

This is an offline research/audit helper. Runtime strategy code must not import it. The audit takes
George labels from an explicit external CSV and explains where each label drops out of the QC local
pipeline: coarse feed, DV/price floors, daily data, BCT prefilter, BCT score, parabolic block, or
the final QC-safe George-style rerank.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import math
import pandas as pd

from phases.shared.oracle_helpers import score_from_daily_frame
from scripts.funnel_signal_count import _DAILY_DIR, load_daily_frame, slice_as_of
from sweeps.archive import candidates as C
from sweeps.archive.candidates import _features_from_daily


STAGE_QC_CANDIDATE = "qc_candidate"
STAGE_DATE_NOT_COVERED = "date_not_covered"
STAGE_NOT_IN_COARSE_FEED = "not_in_coarse_feed"
STAGE_FAILS_PREFILTER_DV = "fails_prefilter_dv"
STAGE_FAILS_PRICE_FLOOR = "fails_price_floor"
STAGE_FAILS_TRAILING_DV_FLOOR = "fails_trailing_dv_floor"
STAGE_NOT_RANKED_AFTER_FLOORS = "not_ranked_after_floors"
STAGE_MISSING_DAILY_FRAME = "missing_daily_frame"
STAGE_NO_DAILY_BARS_ASOF = "no_daily_bars_asof"
STAGE_FEATURE_NOT_READY = "feature_not_ready"
STAGE_FAILS_BCT_PREFILTER = "fails_bct_prefilter"
STAGE_SCORE_NOT_READY = "score_not_ready"
STAGE_BCT_SCORE_BELOW_MIN = "bct_score_below_min"
STAGE_PARABOLIC_BLOCK = "parabolic_block"


@dataclass(slots=True)
class GeorgeCoverageAuditRow:
    date: str
    symbol: str
    stage: str
    in_coarse_feed: bool = False
    passed_prefilter_dv: bool = False
    passed_price_floor: bool = False
    passed_trailing_dv_floor: bool = False
    in_ranked_universe: bool = False
    has_daily_frame: bool = False
    has_daily_bars_asof: bool = False
    passed_bct_prefilter: bool = False
    score_ready: bool = False
    score: int | None = None
    rating: str | None = None
    passed_score: bool = False
    passed_parabolic: bool = False
    single_day_dv: float | None = None
    trailing_dv: float | None = None
    close_for_floor: float | None = None
    daily_close: float | None = None
    sma200: float | None = None
    daily_cloud_top: float | None = None
    roc13: float | None = None
    bct_signal_rank: int | None = None
    george_style_rank: int | None = None
    george_style_score: float | None = None
    george_constructive_resistance: bool | None = None
    george_bad_resistance: bool | None = None
    george_no_chase_risk: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "stage": self.stage,
            "in_coarse_feed": self.in_coarse_feed,
            "passed_prefilter_dv": self.passed_prefilter_dv,
            "passed_price_floor": self.passed_price_floor,
            "passed_trailing_dv_floor": self.passed_trailing_dv_floor,
            "in_ranked_universe": self.in_ranked_universe,
            "has_daily_frame": self.has_daily_frame,
            "has_daily_bars_asof": self.has_daily_bars_asof,
            "passed_bct_prefilter": self.passed_bct_prefilter,
            "score_ready": self.score_ready,
            "score": self.score,
            "rating": self.rating,
            "passed_score": self.passed_score,
            "passed_parabolic": self.passed_parabolic,
            "single_day_dv": self.single_day_dv,
            "trailing_dv": self.trailing_dv,
            "close_for_floor": self.close_for_floor,
            "daily_close": self.daily_close,
            "sma200": self.sma200,
            "daily_cloud_top": self.daily_cloud_top,
            "roc13": self.roc13,
            "bct_signal_rank": self.bct_signal_rank,
            "george_style_rank": self.george_style_rank,
            "george_style_score": self.george_style_score,
            "george_constructive_resistance": self.george_constructive_resistance,
            "george_bad_resistance": self.george_bad_resistance,
            "george_no_chase_risk": self.george_no_chase_risk,
        }


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def load_george_labels(
    labels_path: Path,
    *,
    date_col: str = "date",
    symbol_col: str = "symbol",
    included_col: str = "george_included",
) -> list[tuple[str, str]]:
    """Load unique George positive labels from a CSV such as `george_oof_stage1_scores.csv`."""
    usecols = [date_col, symbol_col]
    if included_col:
        usecols.append(included_col)
    df = pd.read_csv(labels_path, usecols=usecols)
    if included_col in df.columns:
        df = df[df[included_col].astype(bool)]
    out = (
        df[[date_col, symbol_col]]
        .dropna()
        .drop_duplicates()
        .sort_values([date_col, symbol_col])
    )
    return [(str(r[date_col]), str(r[symbol_col]).upper()) for _, r in out.iterrows()]


def audit_label(
    date: str,
    symbol: str,
    *,
    universe: dict[str, list[str]],
    coarse_metrics: dict[str, dict[str, tuple[float, float, float]]],
    daily_dir: Path = _DAILY_DIR,
    frame_cache: dict[str, pd.DataFrame | None] | None = None,
    min_score: int = C.DEFAULT_MIN_SCORE,
    parabolic_threshold: float = C.DEFAULT_PARABOLIC_THRESHOLD,
    candidate_row_by_key: dict[tuple[str, str], C.CandidateRow] | None = None,
) -> GeorgeCoverageAuditRow:
    """Classify one George label against the local QC scanner pipeline."""
    sym = symbol.upper()
    key = sym.lower()
    row = GeorgeCoverageAuditRow(date=date, symbol=sym, stage=STAGE_QC_CANDIDATE)

    if date not in coarse_metrics:
        row.stage = STAGE_DATE_NOT_COVERED
        return row

    metrics = coarse_metrics[date].get(key)
    if metrics is None:
        row.stage = STAGE_NOT_IN_COARSE_FEED
        return row

    row.in_coarse_feed = True
    close_for_floor, single_day_dv, trailing_dv = metrics
    row.close_for_floor = close_for_floor
    row.single_day_dv = single_day_dv
    row.trailing_dv = trailing_dv
    row.passed_prefilter_dv = single_day_dv >= C.PREFILTER_DV
    if not row.passed_prefilter_dv:
        row.stage = STAGE_FAILS_PREFILTER_DV
        return row

    row.passed_price_floor = close_for_floor >= C.MIN_PRICE
    if not row.passed_price_floor:
        row.stage = STAGE_FAILS_PRICE_FLOOR
        return row

    row.passed_trailing_dv_floor = trailing_dv >= C.MIN_AVG_DOLLAR_VOLUME
    if not row.passed_trailing_dv_floor:
        row.stage = STAGE_FAILS_TRAILING_DV_FLOOR
        return row

    ranked = {t.lower() for t in universe.get(date, [])}
    row.in_ranked_universe = key in ranked
    if not row.in_ranked_universe:
        row.stage = STAGE_NOT_RANKED_AFTER_FLOORS
        return row

    if frame_cache is None:
        frame = load_daily_frame(sym, daily_dir)
    else:
        if sym not in frame_cache:
            frame_cache[sym] = load_daily_frame(sym, daily_dir)
        frame = frame_cache[sym]
    if frame is None:
        row.stage = STAGE_MISSING_DAILY_FRAME
        return row
    row.has_daily_frame = True

    as_of = pd.Timestamp(date)
    daily = slice_as_of(frame, as_of)
    if daily.empty:
        row.stage = STAGE_NO_DAILY_BARS_ASOF
        return row
    row.has_daily_bars_asof = True

    feats = _features_from_daily(daily)
    if feats is None:
        row.stage = STAGE_FEATURE_NOT_READY
        return row
    row.daily_close = feats["close"]
    row.sma200 = feats["sma200"]
    row.daily_cloud_top = feats["daily_cloud_top"]
    row.roc13 = feats["roc13"]
    row.passed_bct_prefilter = (
        feats["close"] >= feats["sma200"] and feats["close"] >= feats["daily_cloud_top"]
    )
    if not row.passed_bct_prefilter:
        row.stage = STAGE_FAILS_BCT_PREFILTER
        return row

    result = score_from_daily_frame(daily)
    if result is None:
        row.stage = STAGE_SCORE_NOT_READY
        return row
    row.score_ready = True
    row.score = int(result["score"])
    row.rating = str(result["rating"])
    row.passed_score = row.score >= min_score
    if not row.passed_score:
        row.stage = STAGE_BCT_SCORE_BELOW_MIN
        return row

    row.passed_parabolic = not (_finite(row.roc13) and row.roc13 is not None and row.roc13 > parabolic_threshold)
    if not row.passed_parabolic:
        row.stage = STAGE_PARABOLIC_BLOCK
        return row

    if candidate_row_by_key is not None:
        candidate = candidate_row_by_key.get((date, sym))
        if candidate is not None:
            row.bct_signal_rank = candidate.bct_signal_rank
            row.george_style_rank = candidate.george_style_rank
            row.george_style_score = candidate.george_style_score
            row.george_constructive_resistance = candidate.george_constructive_resistance
            row.george_bad_resistance = candidate.george_bad_resistance
            row.george_no_chase_risk = candidate.george_no_chase_risk
    row.stage = STAGE_QC_CANDIDATE
    return row


def audit_labels(
    labels: Iterable[tuple[str, str]],
    *,
    universe: dict[str, list[str]],
    coarse_metrics: dict[str, dict[str, tuple[float, float, float]]],
    daily_dir: Path = _DAILY_DIR,
    min_score: int = C.DEFAULT_MIN_SCORE,
    parabolic_threshold: float = C.DEFAULT_PARABOLIC_THRESHOLD,
    include_candidate_ranks: bool = True,
) -> list[GeorgeCoverageAuditRow]:
    """Audit labels against a prebuilt universe/metrics map."""
    label_list = list(labels)
    frame_cache: dict[str, pd.DataFrame | None] = {}
    candidate_row_by_key: dict[tuple[str, str], C.CandidateRow] = {}
    if include_candidate_ranks:
        dates = sorted({date for date, _symbol in label_list if date in universe})
        header, candidates = C.generate_window(
            dates,
            universe,
            daily_dir=daily_dir,
            universe_source="coverage-audit",
            coarse_metrics=coarse_metrics,
        )
        _ = header
        candidate_row_by_key = {(r.date, r.symbol): r for r in candidates}

    return [
        audit_label(
            date,
            symbol,
            universe=universe,
            coarse_metrics=coarse_metrics,
            daily_dir=daily_dir,
            frame_cache=frame_cache,
            min_score=min_score,
            parabolic_threshold=parabolic_threshold,
            candidate_row_by_key=candidate_row_by_key,
        )
        for date, symbol in label_list
    ]


def summarize_audit(rows: list[GeorgeCoverageAuditRow]) -> pd.DataFrame:
    """Return a compact stage count/percent table in audit order."""
    order = [
        STAGE_QC_CANDIDATE,
        STAGE_DATE_NOT_COVERED,
        STAGE_NOT_IN_COARSE_FEED,
        STAGE_FAILS_PREFILTER_DV,
        STAGE_FAILS_PRICE_FLOOR,
        STAGE_FAILS_TRAILING_DV_FLOOR,
        STAGE_NOT_RANKED_AFTER_FLOORS,
        STAGE_MISSING_DAILY_FRAME,
        STAGE_NO_DAILY_BARS_ASOF,
        STAGE_FEATURE_NOT_READY,
        STAGE_FAILS_BCT_PREFILTER,
        STAGE_SCORE_NOT_READY,
        STAGE_BCT_SCORE_BELOW_MIN,
        STAGE_PARABOLIC_BLOCK,
    ]
    total = len(rows)
    counts = {stage: 0 for stage in order}
    for row in rows:
        counts[row.stage] = counts.get(row.stage, 0) + 1
    return pd.DataFrame(
        [
            {
                "stage": stage,
                "rows": counts.get(stage, 0),
                "pct": round(100.0 * counts.get(stage, 0) / total, 2) if total else 0.0,
            }
            for stage in order
            if counts.get(stage, 0) > 0
        ]
    )
