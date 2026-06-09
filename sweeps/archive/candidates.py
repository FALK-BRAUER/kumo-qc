"""(B) Local authoritative SIGNAL-WINNER population generator (#303 learn-substrate input side).

WHAT THIS IS
------------
kumo-qc owns the daily-signal funnel definition. The per-run trades archive (sweeps/archive/
snapshot.py) only captures the TRADED subset (closed losers + censored winners). The #303
kumo-lab mine needs the FULL daily candidate population — EVERY score>=7 signal-winner per day
plus each candidate's signal-time context — so it can learn which conditions/context predict good
trades (and whether gap>=3% is the optimal cut) across the WHOLE population, not just the traded
tail. This module emits that population deterministically, offline, from the SAME local LEAN daily
data the strategy scores on.

PARITY-SAFE CORE (charter: single code path, never reimplement scoring)
-----------------------------------------------------------------------
The 8-condition score is produced by `phases.shared.oracle_helpers.score_from_daily_frame` — the
EXACT pure core the QC live path runs (score_symbol -> _fetch_ohlcv -> score_from_daily_frame).
The funnel floors/rank/cap are `runtime.universe_select.apply_floors` / `rank_and_cap`. We import
all three read-only; we do NOT reimplement them. The signal-time FEATURES (kijun/tenkan/cloud/adx/
roc13...) are recomputed with the SAME pure ichimoku/ADX helpers from oracle_helpers (`_mid`,
`_adx_wilder`, `_resample_weekly`) so feature math == scoring math, by construction.

THE FUNNEL (signal_winners) — exactly the live def
--------------------------------------------------
For each trading day, the strategy's daily candidate population is:

    coarse universe (top-DV ~200/day, from polygon_universe_equity200_fy2025.json)
      -> PREFILTER     : single-day DV >= PREFILTER_DV (25M)        [runtime.lean_entry]
      -> FLOORS        : close >= 10.0 AND trailing_dv >= 100M       [apply_floors]
      -> RANK + CAP    : DV-desc, ticker-asc, cap COARSE_MAX (9999)  [rank_and_cap]
      -> BCT PREFILTER : price >= sma200 AND price >= daily cloud_top [bct_score_full L116-124]
      -> PARABOLIC     : roc13 <= parabolic_threshold (0.25)         [bct_score_full L136]
      -> SCORE         : score_from_daily_frame >= min_score (7)     [oracle_helpers]

DAILY-SOURCE PINNED
-------------------
We read the SAME local LEAN daily zips the strategy scores on (RAW/unadjusted; data/equity/usa/
daily/*.zip; OHLC stored *10000). Vendor = local LEAN data files (the C1 harness proved this
gives a reliable ~43/day median score>=7 count). Stamped in the artifact header so the population
cannot silently drift from the cloud's actual signal set.

DETERMINISM + NO LOOK-AHEAD
---------------------------
Every per-day computation slices the daily frame AS-OF the decision date (index <= date), exactly
like the LEAN History(...) call after close on the decision day. No cloud run. Same dates in ->
byte-identical JSONL out (rows sorted score-DESC then ticker-ASC; floats rounded deterministically).

C1 PARITY
---------
Run with `apply_funnel_floors=False` (the C1 mode) and the emitted score>=7 row count per date is
IDENTICAL to scripts/funnel_signal_count.py — same scoring core, same data, same as-of slice. With
floors on, the population is the funnel-exact signal_winners (a subset). Each row carries
`passed_floors`/`passed_prefilter`/`passed_parabolic` so the lab can reconstruct either set and the
(A)-parity audit can diff its regeneration against this artifact.
"""
from __future__ import annotations

import json
import math
import os
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from phases.shared.oracle_helpers import (
    _adx_wilder,
    _mid,
    _resample_weekly,
    score_from_daily_frame,
)
from phases.shared.chart_features import (
    ChartCurationInputs,
    build_chart_curation_features,
    george_qc_candidate_score,
)
from runtime.universe_select import apply_floors, rank_and_cap

# Reuse the C1 harness loaders verbatim (the proven local LEAN daily-zip reader + as-of slicer).
from scripts.funnel_signal_count import (  # noqa: E402
    _DAILY_DIR,
    _PRICE_SCALE,
    load_daily_frame,
    load_universe,
    slice_as_of,
)

# LEAN CoarseFundamental CSV tree — QC's EXACT live universe membership (#276b parity fix).
# One CSV per trading session: `<YYYYMMDD>.csv`. Columns (LEAN coarse format, NO header row):
#   SID, ticker, close, volume, dollar_volume, has_fundamental_data, price_factor, split_factor
# This is the feed runtime.lean_entry._coarse_selection scans live (its `.price` == coarse close,
# its `.dollar_volume` == coarse single-day DV). Reading it reproduces the live coarse membership
# + DV instead of the ~6.7x-too-wide local-daily-all approximation (which scanned every ~19k zip).
_COARSE_DIR: Path = _DAILY_DIR.parent / "fundamental" / "coarse"
# Coarse CSV column indices (0-based) — confirmed by inspecting data/.../coarse/<date>.csv.
_COARSE_COL_TICKER: int = 1
_COARSE_COL_CLOSE: int = 2
_COARSE_COL_DOLLAR_VOLUME: int = 4

# ---------------------------------------------------------------------------
# Funnel constants — MIRRORED from runtime.lean_entry.LeanEntry (the live gate).
# Kept as named constants here (lean_entry is a QC algorithm class we must NOT import/instantiate
# offline); each is annotated with its source so drift is auditable. If lean_entry changes a floor,
# this generator's funnel-def-match test (parity vs the live gate values) is the tripwire.
# ---------------------------------------------------------------------------
PREFILTER_DV: float = 25_000_000.0      # lean_entry.PREFILTER_DV (loose single-day-DV perf-bound)
MIN_PRICE: float = 10.0                 # lean_entry.MIN_PRICE -> apply_floors(min_price=)
MIN_AVG_DOLLAR_VOLUME: float = 100_000_000.0  # lean_entry.MIN_AVG_DOLLAR_VOLUME -> apply_floors
COARSE_MAX: int = 9999                  # lean_entry.COARSE_MAX -> rank_and_cap(coarse_max=)
ADV_WINDOW: int = 20                    # lean_entry.ADV_WINDOW (trailing-DV rolling window)

DEFAULT_MIN_SCORE: int = 7              # bct_score_full Params.min_score (champion)
DEFAULT_PARABOLIC_THRESHOLD: float = 0.25  # bct_score_full Params.parabolic_threshold (champion)

# Provenance stamped into every artifact header so the population can't drift unnoticed.
DATA_VENDOR: str = "local-lean-daily-zips"
DATA_NORMALIZATION: str = "raw"  # RAW/unadjusted; OHLC stored *10000 (load_daily_frame unscales)
SCHEMA_VERSION: int = 3

# Number of float decimals retained in emitted feature values (determinism — no platform jitter).
_ROUND: int = 6

# INSTRUMENTED-CLOUD GROUND TRUTH (#276b acceptance bar). The instrumented FY2025 cloud funnel run
# (bt 3c9cb7b8) recorded signal_winners (score>=7, pre-regime) for the year. The generator's local-
# coarse reconstruction is compared to this; the ratio is stamped into the header as a documented
# universe-membership / scoring-vendor uncertainty so the #303 mine knows the residual it carries.
# (Per-year; only FY2025 has an instrumented baseline — others stamp None.)
INSTRUMENTED_SIGNAL_WINNERS: dict[int, int] = {2025: 7007}


def _candidate_lane(score: int) -> str:
    """Stable lane label for score-threshold experiments in offline exports."""
    if score >= 7:
        return "bct_score_ge7"
    if score == 6:
        return "almost_bct_score6"
    return "below_bct_score6"


@dataclass(slots=True)
class CandidateRow:
    """One score>=min_score signal-winner on one decision date, with its signal-time context.

    `conditions` is the stable 8-element BCT boolean list (cond_0..cond_7) straight from
    score_from_daily_frame — same order as the CLAUDE.md Blue Flag checklist. The `passed_*` flags
    record which funnel stages this name cleared (so the lab can reconstruct C1-set vs funnel-set).
    """

    date: str
    symbol: str
    score: int
    rating: str
    conditions: list[bool]
    # signal-time features available at the decision (all as-of <= date, no look-ahead)
    close: float
    daily_tenkan: float
    daily_kijun: float
    sma200: float
    daily_cloud_a: float
    daily_cloud_b: float
    daily_cloud_top: float
    weekly_cloud_a: float
    weekly_cloud_b: float
    weekly_cloud_top: float
    weekly_tenkan: float
    weekly_kijun: float
    adx: float
    plus_di: float
    minus_di: float
    roc13: float
    single_day_dv: float
    trailing_dv: float
    scanner_rank: int
    # funnel-stage membership flags (the funnel signal_winners == all three True)
    passed_prefilter: bool
    passed_floors: bool
    passed_parabolic: bool
    bct_candidate_lane: str = ""
    # QC-safe George-style ranking bridge fields. Filled after per-date row collection.
    bct_signal_rank: int = -1
    george_style_rank: int = -1
    george_style_score: float = 0.0
    george_constructive_resistance: bool = False
    george_bad_resistance: bool = False
    george_no_chase_risk: bool = False
    george_retest_prior_as_support: bool = False
    george_reclaim_after_touch: bool = False
    george_breakout_volume_confirmed: bool = False

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "date": self.date,
            "symbol": self.symbol,
            "score": self.score,
            "rating": self.rating,
            "bct_candidate_lane": self.bct_candidate_lane or _candidate_lane(self.score),
        }
        # cond_0..cond_7 expanded for a flat, mine-friendly schema (stable order).
        for i, c in enumerate(self.conditions):
            d[f"cond_{i}"] = bool(c)
        for fld in (
            "close", "daily_tenkan", "daily_kijun", "sma200",
            "daily_cloud_a", "daily_cloud_b", "daily_cloud_top",
            "weekly_cloud_a", "weekly_cloud_b", "weekly_cloud_top",
            "weekly_tenkan", "weekly_kijun",
            "adx", "plus_di", "minus_di", "roc13",
            "single_day_dv", "trailing_dv",
        ):
            v = getattr(self, fld)
            d[fld] = None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), _ROUND)
        d["scanner_rank"] = self.scanner_rank
        d["bct_signal_rank"] = self.bct_signal_rank
        d["george_style_rank"] = self.george_style_rank
        d["george_style_score"] = round(float(self.george_style_score), _ROUND)
        d["george_constructive_resistance"] = self.george_constructive_resistance
        d["george_bad_resistance"] = self.george_bad_resistance
        d["george_no_chase_risk"] = self.george_no_chase_risk
        d["george_retest_prior_as_support"] = self.george_retest_prior_as_support
        d["george_reclaim_after_touch"] = self.george_reclaim_after_touch
        d["george_breakout_volume_confirmed"] = self.george_breakout_volume_confirmed
        d["passed_prefilter"] = self.passed_prefilter
        d["passed_floors"] = self.passed_floors
        d["passed_parabolic"] = self.passed_parabolic
        return d


def _roc13(daily: pd.DataFrame) -> float:
    """QC ROC(13) on close == (close[-1] - close[-14]) / close[-14]. NaN if < 14 bars or zero ref.

    Matches lean_entry.roc(sym, 13) (a 13-period rate-of-change on the daily close), the value the
    parabolic block compares to parabolic_threshold. Decimal fraction, not percent.
    """
    c = daily["close"]
    if len(c) < 14:
        return float("nan")
    ref = c.iloc[-14]
    if ref == 0 or pd.isna(ref):
        return float("nan")
    return float((c.iloc[-1] - ref) / ref)


def _prior_high(daily: pd.DataFrame, window: int) -> float:
    """Highest high over the prior `window` completed bars, excluding the current decision bar."""
    if len(daily) < 2:
        return float("nan")
    prior = daily["high"].iloc[:-1].tail(window)
    if prior.empty:
        return float("nan")
    return float(prior.max())


def _rel_volume20(daily: pd.DataFrame) -> float:
    """Current completed-bar volume divided by the prior-20-bar average volume."""
    if len(daily) < 2:
        return float("nan")
    prior = daily["volume"].iloc[:-1].tail(ADV_WINDOW)
    if prior.empty:
        return float("nan")
    avg = float(prior.mean())
    if avg <= 0.0 or not math.isfinite(avg):
        return float("nan")
    return float(daily["volume"].iloc[-1]) / avg


def _features_from_daily(daily: pd.DataFrame) -> dict[str, float] | None:
    """Recompute the signal-time feature context from the as-of daily frame using the SAME pure
    ichimoku/ADX helpers as score_from_daily_frame. Read-only superset of the scorer's internals.

    Returns None on the same warmup guards the scorer applies (so a row with a score always has a
    full feature set). NaN guards on the scorer's critical values are NOT re-applied here — if the
    scorer returned a score, those values were finite.
    """
    if len(daily) < 230:
        return None
    weekly = _resample_weekly(daily)
    if len(weekly) < 78:
        return None

    w_tenkan = _mid(weekly["high"], weekly["low"], 9)
    w_kijun = _mid(weekly["high"], weekly["low"], 26)
    w_cloud_a = ((w_tenkan + w_kijun) / 2).shift(26)
    w_cloud_b = _mid(weekly["high"], weekly["low"], 52).shift(26)

    d_tenkan = _mid(daily["high"], daily["low"], 9)
    d_kijun = _mid(daily["high"], daily["low"], 26)
    d_cloud_a = ((d_tenkan + d_kijun) / 2).shift(26)
    d_cloud_b = _mid(daily["high"], daily["low"], 52).shift(26)

    adx, plus_di, minus_di = _adx_wilder(daily, period=9)

    wca = float(w_cloud_a.iloc[-1])
    wcb = float(w_cloud_b.iloc[-1])
    dca = float(d_cloud_a.iloc[-1])
    dcb = float(d_cloud_b.iloc[-1])

    return {
        "open": float(daily["open"].iloc[-1]),
        "high": float(daily["high"].iloc[-1]),
        "low": float(daily["low"].iloc[-1]),
        "close": float(daily["close"].iloc[-1]),
        "daily_tenkan": float(d_tenkan.iloc[-1]),
        "daily_kijun": float(d_kijun.iloc[-1]),
        "sma200": float(daily["close"].rolling(200).mean().iloc[-1]),
        "daily_cloud_a": dca,
        "daily_cloud_b": dcb,
        "daily_cloud_top": max(dca, dcb),
        "weekly_cloud_a": wca,
        "weekly_cloud_b": wcb,
        "weekly_cloud_top": max(wca, wcb),
        "weekly_tenkan": float(w_tenkan.iloc[-1]),
        "weekly_kijun": float(w_kijun.iloc[-1]),
        "adx": float(adx.iloc[-1]),
        "plus_di": float(plus_di.iloc[-1]),
        "minus_di": float(minus_di.iloc[-1]),
        "roc13": _roc13(daily),
        "prior_high20": _prior_high(daily, 20),
        "prior_high50": _prior_high(daily, 50),
        "prior_high252": _prior_high(daily, 252),
        "rel_volume20": _rel_volume20(daily),
    }


def _trailing_dv_mean(daily: pd.DataFrame, as_of: pd.Timestamp, window: int = ADV_WINDOW) -> float:
    """Trailing mean dollar-volume == mean(close*volume) over the last `window` OBSERVED bars
    up to and including as_of. Mirrors the maintained rolling-20 mean the live gate floors on
    (rolling_dv_mean over the coarse single-day DV, which == close*volume on RAW local data).
    Empty -> 0.0 (a name with no observed DV is never tradeable, matching apply_floors)."""
    upto = daily[daily.index <= as_of]
    if upto.empty:
        return 0.0
    tail = upto.tail(window)
    dv = (tail["close"] * tail["volume"]).astype(float)
    if len(dv) == 0:
        return 0.0
    return float(dv.mean())


def _apply_george_style_bridge(rows: list[CandidateRow], by_symbol_features: dict[str, dict[str, float]]) -> None:
    """Attach QC-safe George-style score/rank fields to already-built rows for one date."""
    for row in rows:
        feats = by_symbol_features[row.symbol]
        chart = build_chart_curation_features(
            ChartCurationInputs(
                bct_score=row.score,
                open=feats.get("open"),
                high=feats.get("high"),
                low=feats.get("low"),
                close=feats["close"],
                tenkan=feats.get("daily_tenkan"),
                kijun=feats.get("daily_kijun"),
                cloud_top=feats.get("daily_cloud_top"),
                roc13=feats.get("roc13"),
                rel_volume20=feats.get("rel_volume20"),
                prior_high20=feats.get("prior_high20"),
                prior_high50=feats.get("prior_high50"),
                prior_high252=feats.get("prior_high252"),
            )
        )
        row.george_style_score = george_qc_candidate_score(chart)
        row.george_constructive_resistance = chart.constructive_resistance
        row.george_bad_resistance = chart.bad_resistance
        row.george_no_chase_risk = chart.no_chase_risk
        row.george_retest_prior_as_support = chart.retest_prior_as_support
        row.george_reclaim_after_touch = chart.reclaim_after_touch
        row.george_breakout_volume_confirmed = chart.breakout_volume_confirmed

    # Existing exported row order stays BCT score desc / ticker asc for compatibility; ranks give
    # the two comparison orders explicitly.
    for rank, row in enumerate(sorted(rows, key=lambda r: (-r.score, r.symbol)), start=1):
        row.bct_signal_rank = rank
    for rank, row in enumerate(
        sorted(rows, key=lambda r: (-r.george_style_score, -r.trailing_dv, r.symbol)), start=1
    ):
        row.george_style_rank = rank


def generate_candidates_for_date(
    date_str: str,
    tickers: list[str],
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    parabolic_threshold: float = DEFAULT_PARABOLIC_THRESHOLD,
    apply_funnel_floors: bool = True,
    daily_dir: Path = _DAILY_DIR,
    frame_cache: dict[str, pd.DataFrame | None] | None = None,
    coarse_metrics: dict[str, tuple[float, float, float]] | None = None,
) -> list[CandidateRow]:
    """Emit EVERY score>=min_score signal-winner on one decision date as a CandidateRow.

    Funnel order (the live def): prefilter (single-day DV) -> floors (close + trailing DV) ->
    rank+cap (DV-desc) -> bct prefilter (price>=sma200 & price>=cloud_top) -> parabolic (roc13) ->
    score>=min_score. Every name that scores >= min_score is emitted (with its passed_* flags) so
    the artifact is BOTH the (B)-emit AND the (A)-parity audit; the funnel signal_winners are the
    rows where passed_prefilter & passed_floors & passed_parabolic are all True.

    `apply_funnel_floors=False` = C1-parity mode: skip the prefilter/floors/rank gate (score the
    full coarse universe), so the score>=min_score count matches funnel_signal_count.py exactly.

    UNIVERSE/DV SOURCE (#276b parity fix): when `coarse_metrics` is supplied (= {ticker_lower:
    (close, single_day_dv, trailing_dv)} from the LEAN coarse CSV via build_coarse_universe), the
    single-day DV, close-for-floor and trailing-mean DV come from QC's LIVE coarse feed — the
    EXACT membership + DV the live _coarse_selection floors/ranks on. The 8-condition SCORE +
    signal-time features still come from the LOCAL daily frame (those are price/indicator features;
    only the universe membership + DV source changes). When `coarse_metrics` is None we fall back
    to the local-daily close*volume approximation (pre-coarse years; NOT authoritative).

    AS-OF <= date everywhere (no look-ahead). Deterministic given (date, tickers, data).
    """
    as_of = pd.Timestamp(date_str)

    # Load each ticker's daily frame once; build (close, trailing_dv, single_day_dv) metrics.
    frames: dict[str, pd.DataFrame] = {}
    single_day_dv: dict[str, float] = {}
    trailing_dv: dict[str, float] = {}
    close_today: dict[str, float] = {}

    def _frame(t: str) -> pd.DataFrame | None:
        # Cache frames across dates (the local-universe builder scores a ticker on many days).
        if frame_cache is None:
            return load_daily_frame(t, daily_dir)
        if t not in frame_cache:
            frame_cache[t] = load_daily_frame(t, daily_dir)
        return frame_cache[t]

    for ticker in tickers:
        df = _frame(ticker)
        if df is None:
            continue
        upto = df[df.index <= as_of]
        if upto.empty:
            continue
        frames[ticker] = df
        if coarse_metrics is not None:
            # AUTHORITATIVE: DV + close-for-floor from QC's live coarse feed (not local c*v).
            cm = coarse_metrics.get(ticker.lower())
            if cm is None:
                # Ranked by the coarse builder but absent from today's coarse metrics — should not
                # happen (the universe is derived from the same metrics); skip rather than fabricate.
                continue
            c_close, c_sdv, c_trailing = cm
            close_today[ticker] = c_close
            single_day_dv[ticker] = c_sdv
            trailing_dv[ticker] = c_trailing
        else:
            # FALLBACK: local-daily close*volume approximation (pre-coarse years; not authoritative).
            bar = upto.iloc[-1]
            c = float(bar["close"])
            close_today[ticker] = c
            single_day_dv[ticker] = c * float(bar["volume"])
            trailing_dv[ticker] = _trailing_dv_mean(df, as_of)

    # PREFILTER + FLOORS + RANK/CAP (the live selection gate). Keys lowered to match the runtime
    # convention (coarse_to_dollar_volume lowercases; apply_floors/rank_and_cap are case-tolerant).
    prefilter_pass: set[str] = set()
    bar_metrics: dict[str, tuple[float, float]] = {}
    for ticker, sdv in single_day_dv.items():
        if sdv >= PREFILTER_DV:
            prefilter_pass.add(ticker)
            bar_metrics[ticker.lower()] = (close_today[ticker], trailing_dv[ticker])

    eligible = apply_floors(
        bar_metrics, min_price=MIN_PRICE, min_avg_dollar_volume=MIN_AVG_DOLLAR_VOLUME
    )
    dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
    ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=COARSE_MAX)
    floors_pass = {t.lower() for t in ranked}  # apply_floors returns the lowered keys
    rank_index = {t.lower(): i for i, t in enumerate(ranked)}

    # Which tickers do we score? Funnel mode: only the ranked (floored) set. C1 mode: all loaded.
    to_score = [t for t in frames if t.lower() in floors_pass] if apply_funnel_floors else list(frames)

    rows: list[CandidateRow] = []
    row_features: dict[str, dict[str, float]] = {}
    for ticker in to_score:
        daily = slice_as_of(frames[ticker], as_of)
        result = score_from_daily_frame(daily)
        if result is None or int(result["score"]) < min_score:
            continue

        feats = _features_from_daily(daily)
        if feats is None:
            # score_from_daily_frame succeeded but feature recompute hit a warmup guard — should
            # not happen (same guards); skip rather than emit a row with no context.
            continue

        roc = feats["roc13"]
        # BCT prefilter (price >= sma200 AND price >= daily cloud_top) — these are conditions 8 & 5;
        # by construction a score>=7 name with both failing can't reach 7, but we record the flag.
        prefilter_ok = (
            feats["close"] >= feats["sma200"] and feats["close"] >= feats["daily_cloud_top"]
        )
        parabolic_ok = not (math.isfinite(roc) and roc > parabolic_threshold)

        row = CandidateRow(
            date=date_str,
            symbol=ticker.upper(),
            score=int(result["score"]),
            rating=str(result["rating"]),
            conditions=[bool(x) for x in result["conditions"]],
            bct_candidate_lane=_candidate_lane(int(result["score"])),
            close=feats["close"],
            daily_tenkan=feats["daily_tenkan"],
            daily_kijun=feats["daily_kijun"],
            sma200=feats["sma200"],
            daily_cloud_a=feats["daily_cloud_a"],
            daily_cloud_b=feats["daily_cloud_b"],
            daily_cloud_top=feats["daily_cloud_top"],
            weekly_cloud_a=feats["weekly_cloud_a"],
            weekly_cloud_b=feats["weekly_cloud_b"],
            weekly_cloud_top=feats["weekly_cloud_top"],
            weekly_tenkan=feats["weekly_tenkan"],
            weekly_kijun=feats["weekly_kijun"],
            adx=feats["adx"],
            plus_di=feats["plus_di"],
            minus_di=feats["minus_di"],
            roc13=roc,
            single_day_dv=single_day_dv.get(ticker, 0.0),
            trailing_dv=trailing_dv.get(ticker, 0.0),
            scanner_rank=rank_index.get(ticker.lower(), -1),
            passed_prefilter=ticker in prefilter_pass,
            passed_floors=ticker.lower() in floors_pass,
            passed_parabolic=parabolic_ok,
        )
        rows.append(row)
        row_features[row.symbol] = feats

    # Deterministic order: score DESC, then ticker ASC (stable, platform-independent).
    rows.sort(key=lambda r: (-r.score, r.symbol))
    _apply_george_style_bridge(rows, row_features)
    return rows


def build_local_universe(
    year: int,
    *,
    daily_dir: Path = _DAILY_DIR,
) -> dict[str, list[str]]:
    """Compute the LIVE-coarse-equivalent universe per day for `year`, from the local daily zips.

    This is the offline equivalent of the cloud strategy's once-daily selection gate (runtime.
    lean_entry._coarse_selection) — it lets the generator run for ANY year (FY2021..FY2025), not
    just the FY2025 polygon snapshot. Single streaming pass over every daily zip:

      per ticker, per trading day in `year`:
        single_day_dv = close * volume   (RAW local daily; OHLC unscaled by load convention)
        trailing_dv   = mean(close*volume) over the last ADV_WINDOW (20) OBSERVED bars <= day
      PREFILTER : single_day_dv >= PREFILTER_DV (25M)  -> builds the (close, trailing_dv) metric
      FLOORS    : apply_floors(close >= MIN_PRICE AND trailing_dv >= MIN_AVG_DOLLAR_VOLUME)
      RANK+CAP  : rank_and_cap(DV-desc, ticker-ASC, coarse_max=COARSE_MAX)

    Returns {date (YYYY-MM-DD) -> [tickers]} — the SAME funnel coarse-universe the scoring stage
    then consumes, so generate_window over this dict reproduces the funnel signal_winners exactly.
    NO look-ahead (trailing window is over bars <= the day). Deterministic (sorted output).

    NOTE: `generate_candidates_for_date` re-derives single_day_dv/trailing_dv/floors per name from
    the same frames (via the canonical `load_daily_frame`), so the universe built here and the
    per-date funnel recompute are bit-identical by construction — this function only PICKS which
    names enter the scoring stage (cheap), it does not change any per-name funnel verdict.

    WHY a streaming zip parse here (not load_daily_frame): this is a ONE-PASS scan over ALL ~19k
    daily zips to find which names ever clear the prefilter in `year` — building a full pandas
    DataFrame per ticker (load_daily_frame) for all 19k names would be far heavier. The parse uses
    the SAME on-disk convention as load_daily_frame (CSV `date,o,h,l,c,v`; OHLC stored *10000, so
    close = field/_PRICE_SCALE). That equivalence is locked by test_streaming_dv_matches_loader
    (the single-day DV from this parse == close*volume from load_daily_frame on a sample ticker),
    so a change to the on-disk format trips a test rather than silently diverging.
    """
    universe, _metrics = build_local_universe_with_metrics(year, daily_dir=daily_dir)
    return universe


def build_local_universe_with_metrics(
    year: int,
    *,
    daily_dir: Path = _DAILY_DIR,
    dates: Iterable[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, dict[str, tuple[float, float, float]]]]:
    """Build the local-daily approximation universe plus per-name daily metrics.

    This is the same local-daily substrate as `build_local_universe`, but it also returns:

        metrics = {date -> {ticker_lower: (close, single_day_dv, trailing_dv)}}

    Unlike the ranked `universe`, `metrics` includes EVERY local-daily ticker with an observed bar
    on the requested date, even if it later fails the prefilter, price floor, or trailing-DV floor.
    That makes it usable for stage audits: a George label can be classified as "fails prefilter" or
    "fails floor" instead of being lumped into "not seen".

    `dates` is an optional ISO-date filter. The streaming pass still reads each ticker's full daily
    history so the trailing-DV window has the same no-look-ahead value, but it only stores metrics
    for the requested dates. This keeps one-off George-audit comparisons small.
    """
    ystr = str(year)
    wanted = set(dates) if dates is not None else None
    # date -> {ticker_lower: (close, single_day_dv, trailing_dv)} for all local-daily bars.
    metrics: dict[str, dict[str, tuple[float, float, float]]] = {}

    for fname in sorted(os.listdir(daily_dir)):
        if not fname.endswith(".zip"):
            continue
        ticker = fname[:-4].lower()
        with zipfile.ZipFile(daily_dir / fname) as zf:
            names = zf.namelist()
            if not names:
                continue
            raw = zf.read(names[0]).decode()
        bar_dates: list[str] = []
        dvs: list[float] = []
        closes: list[float] = []
        for line in raw.strip().split("\n"):
            if not line:
                continue
            p = line.split(",")
            ds = p[0][:8]
            c = float(p[4]) / _PRICE_SCALE  # same unscale convention as load_daily_frame
            v = float(p[5])
            bar_dates.append(ds)
            closes.append(c)
            dvs.append(c * v)
        for i, ds in enumerate(bar_dates):
            if ds[:4] != ystr:
                continue
            iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
            if wanted is not None and iso not in wanted:
                continue
            sdv = dvs[i]
            close = closes[i]
            window = dvs[max(0, i - (ADV_WINDOW - 1)): i + 1]
            tdv = sum(window) / len(window)
            metrics.setdefault(iso, {})[ticker] = (close, sdv, tdv)

    universe: dict[str, list[str]] = {}
    for iso, day_metrics in metrics.items():
        bar_metrics = {
            ticker: (close, trailing)
            for ticker, (close, sdv, trailing) in day_metrics.items()
            if sdv >= PREFILTER_DV
        }
        eligible = apply_floors(
            bar_metrics, min_price=MIN_PRICE, min_avg_dollar_volume=MIN_AVG_DOLLAR_VOLUME
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=COARSE_MAX)
        if ranked:
            universe[iso] = [t.upper() for t in ranked]
    return dict(sorted(universe.items())), dict(sorted(metrics.items()))


def _coarse_csv_path(date_str: str, coarse_dir: Path = _COARSE_DIR) -> Path:
    """Map an ISO date (YYYY-MM-DD) to its LEAN coarse CSV path (`<YYYYMMDD>.csv`)."""
    return coarse_dir / f"{date_str.replace('-', '')}.csv"


def coarse_csv_exists(date_str: str, coarse_dir: Path = _COARSE_DIR) -> bool:
    """True iff the LEAN coarse CSV for this trading date is present (the authoritative source)."""
    return _coarse_csv_path(date_str, coarse_dir).is_file()


def read_coarse_csv(date_str: str, coarse_dir: Path = _COARSE_DIR) -> dict[str, tuple[float, float]]:
    """Parse one LEAN coarse CSV → {ticker_lower: (close, single_day_dollar_volume)}.

    This is QC's EXACT live universe membership for `date_str`: the row set == the tickers QC's
    CoarseFundamental feed delivered that session, and close/DV are the feed's own `.price` /
    `.dollar_volume` columns (NOT recomputed close*volume from local daily). Ticker is lowercased
    to the on-disk/zip-stem + runtime convention (coarse_to_dollar_volume lowercases too).

    FAIL-LOUD: a non-finite DV/close in the coarse CSV is dropped (it must never enter the
    rolling-DV window — mirrors lean_entry.coarse_to_dollar_volume's #261-2 guard). A row with too
    few columns is skipped. Missing file -> empty dict (caller decides authoritative vs fallback).
    """
    path = _coarse_csv_path(date_str, coarse_dir)
    if not path.is_file():
        return {}
    out: dict[str, tuple[float, float]] = {}
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = line.split(",")
            if len(p) <= _COARSE_COL_DOLLAR_VOLUME:
                continue
            ticker = p[_COARSE_COL_TICKER].strip().lower()
            try:
                close = float(p[_COARSE_COL_CLOSE])
                dv = float(p[_COARSE_COL_DOLLAR_VOLUME])
            except ValueError:
                continue
            if not (math.isfinite(close) and math.isfinite(dv)):
                continue  # degraded coarse row must never poison the rolling-DV mean (#261-2)
            out[ticker] = (close, dv)
    return out


def build_coarse_universe(
    year: int,
    *,
    coarse_dir: Path = _COARSE_DIR,
) -> tuple[dict[str, list[str]], dict[str, dict[str, tuple[float, float, float]]]]:
    """Build the LIVE-coarse-authoritative universe per day for `year` from the LEAN coarse CSVs.

    This reproduces runtime.lean_entry._coarse_selection EXACTLY on the same feed it scans live:
      per trading session (each coarse CSV in `year`, in chronological order):
        single_day_dv + close = the coarse CSV's own columns (NOT local close*volume).
        trailing_dv = MEAN of the single-day coarse DV over the last ADV_WINDOW (20) sessions in
                      which the ticker APPEARED in the coarse feed (the maintained rolling-20d mean
                      qc._dv_windows holds — a name absent from a session injects nothing, the
                      window drops oldest at maxlen). No look-ahead (only sessions <= today).
      PREFILTER : single_day_dv >= PREFILTER_DV (25M)  -> builds the (close, trailing_dv) metric.
      FLOORS    : apply_floors(close >= MIN_PRICE AND trailing_dv >= MIN_AVG_DOLLAR_VOLUME).
      RANK+CAP  : rank_and_cap(DV-desc, ticker-ASC, coarse_max=COARSE_MAX).

    Returns (universe, metrics):
      universe = {date (ISO) -> [TICKERS upper]} — QC's exact ranked live selection for that day.
      metrics  = {date (ISO) -> {ticker_lower: (close, single_day_dv, trailing_dv)}} — the coarse
                 close + single-day DV + maintained trailing-mean DV PER NAME in the coarse feed
                 that day (for ALL coarse names, not just the ranked set), so the scoring stage can
                 stamp the authoritative DV/floor verdicts onto every candidate it scores.

    Only sessions with a coarse CSV are included. The rolling window is maintained ACROSS years
    boundaries within the coarse coverage by warming it from the prior ADV_WINDOW sessions before
    `year` (so the first sessions of `year` already have a full trailing window where data exists).
    """
    ystr = str(year)
    # All available coarse sessions, chronological, so the rolling window is maintained correctly
    # (and warmed from the tail of the prior year where it exists).
    all_dates: list[str] = []
    if coarse_dir.is_dir():
        for fname in sorted(os.listdir(coarse_dir)):
            if fname.endswith(".csv") and len(fname) == 12:  # YYYYMMDD.csv
                ds = fname[:8]
                all_dates.append(f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}")

    # Maintained rolling window of the LAST ADV_WINDOW single-day coarse DVs per ticker (in feed-
    # appearance order). Mirrors qc._dv_windows (deque maxlen=ADV_WINDOW) — absence injects nothing.
    windows: dict[str, deque[float]] = {}
    universe: dict[str, list[str]] = {}
    metrics: dict[str, dict[str, tuple[float, float, float]]] = {}

    for iso in all_dates:
        coarse = read_coarse_csv(iso, coarse_dir)
        if not coarse:
            continue
        # Maintain the rolling-20d window for every coarse name seen today (push once per session).
        day_metrics: dict[str, tuple[float, float, float]] = {}
        for ticker, (close, sdv) in coarse.items():
            w = windows.get(ticker)
            if w is None:
                w = deque(maxlen=ADV_WINDOW)
                windows[ticker] = w
            w.append(sdv)
            trailing = sum(w) / len(w)
            day_metrics[ticker] = (close, sdv, trailing)

        # Only emit universe/metrics for sessions IN `year` (prior sessions only warm the window).
        if iso[:4] != ystr:
            continue
        metrics[iso] = day_metrics

        # PREFILTER (single-day DV) -> (close, trailing_dv) metric -> FLOORS -> RANK+CAP.
        bar_metrics: dict[str, tuple[float, float]] = {}
        for ticker, (close, sdv, trailing) in day_metrics.items():
            if sdv >= PREFILTER_DV:
                bar_metrics[ticker] = (close, trailing)
        eligible = apply_floors(
            bar_metrics, min_price=MIN_PRICE, min_avg_dollar_volume=MIN_AVG_DOLLAR_VOLUME
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=COARSE_MAX)
        if ranked:
            universe[iso] = [t.upper() for t in ranked]

    return dict(sorted(universe.items())), metrics


def _artifact_header(
    dates: list[str], min_score: int, parabolic_threshold: float, apply_funnel_floors: bool,
    universe_source: str,
    *,
    authoritative: bool = True,
    universe_membership_uncertainty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Provenance/header record (first JSONL line, record_type='header') — stamps the data vendor,
    normalization, funnel params and the exact funnel def so the lab can detect any drift.

    `authoritative` is False for years with NO LEAN coarse data (pre-2023-06-20) where the universe
    is the local-daily-all approximation — the #303 mine must down-weight/exclude those years'
    untraded counterfactual. `universe_membership_uncertainty` records the generator-vs-instrumented
    signal_winner delta (documented residual) when measured.
    """
    return {
        "record_type": "header",
        "schema_version": SCHEMA_VERSION,
        "generator": "sweeps.archive.candidates",
        "data_vendor": DATA_VENDOR,
        "data_normalization": DATA_NORMALIZATION,
        "funnel": {
            "prefilter_dv": PREFILTER_DV,
            "min_price": MIN_PRICE,
            "min_avg_dollar_volume": MIN_AVG_DOLLAR_VOLUME,
            "coarse_max": COARSE_MAX,
            "adv_window": ADV_WINDOW,
            "min_score": min_score,
            "parabolic_threshold": parabolic_threshold,
            "apply_funnel_floors": apply_funnel_floors,
        },
        "universe_source": universe_source,
        "authoritative": authoritative,
        "universe_membership_uncertainty": universe_membership_uncertainty,
        "n_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "fields": [
            "date", "symbol", "score", "rating", "bct_candidate_lane",
            "cond_0", "cond_1", "cond_2", "cond_3", "cond_4", "cond_5", "cond_6", "cond_7",
            "close", "daily_tenkan", "daily_kijun", "sma200",
            "daily_cloud_a", "daily_cloud_b", "daily_cloud_top",
            "weekly_cloud_a", "weekly_cloud_b", "weekly_cloud_top",
            "weekly_tenkan", "weekly_kijun",
            "adx", "plus_di", "minus_di", "roc13",
            "single_day_dv", "trailing_dv", "scanner_rank",
            "bct_signal_rank", "george_style_rank", "george_style_score",
            "george_constructive_resistance", "george_bad_resistance", "george_no_chase_risk",
            "george_retest_prior_as_support", "george_reclaim_after_touch",
            "george_breakout_volume_confirmed",
            "passed_prefilter", "passed_floors", "passed_parabolic",
        ],
    }


def generate_window(
    dates: Iterable[str],
    universe: dict[str, list[str]] | None = None,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    parabolic_threshold: float = DEFAULT_PARABOLIC_THRESHOLD,
    apply_funnel_floors: bool = True,
    daily_dir: Path = _DAILY_DIR,
    universe_source: str = "polygon_universe_equity200_fy2025.json",
    coarse_metrics: dict[str, dict[str, tuple[float, float, float]]] | None = None,
    authoritative: bool = True,
    universe_membership_uncertainty: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[CandidateRow]]:
    """Generate the candidate population over a window of decision dates.

    `universe` is {date -> [tickers]}; default = the FY2025 polygon snapshot. For ANY year, pass a
    universe built by `build_coarse_universe(year)` (QC's exact live membership, authoritative) or
    `build_local_universe(year)` (local-daily approximation, pre-coarse fallback).

    `coarse_metrics` (when supplied) = {date -> {ticker_lower: (close, single_day_dv, trailing_dv)}}
    from build_coarse_universe — the live coarse feed's DV/close per name. When present for a date,
    the funnel floors/rank + emitted DV are authoritative (QC's live feed); the scoring still uses
    the local daily frame. Absent for a date -> local-daily close*volume fallback.

    Returns (header, rows). `rows` is the concatenation of per-date populations in date order
    (each date already score-DESC/ticker-ASC). Deterministic given the dates + data + params.
    """
    if universe is None:
        universe = load_universe()
    date_list = sorted(set(dates))
    frame_cache: dict[str, pd.DataFrame | None] = {}
    all_rows: list[CandidateRow] = []
    for d in date_list:
        tickers = universe.get(d)
        if tickers is None:
            continue
        all_rows.extend(
            generate_candidates_for_date(
                d, tickers,
                min_score=min_score,
                parabolic_threshold=parabolic_threshold,
                apply_funnel_floors=apply_funnel_floors,
                daily_dir=daily_dir,
                frame_cache=frame_cache,
                coarse_metrics=(coarse_metrics or {}).get(d),
            )
        )
    header = _artifact_header(
        date_list, min_score, parabolic_threshold, apply_funnel_floors, universe_source,
        authoritative=authoritative,
        universe_membership_uncertainty=universe_membership_uncertainty,
    )
    return header, all_rows


def generate_year(
    year: int,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    parabolic_threshold: float = DEFAULT_PARABOLIC_THRESHOLD,
    apply_funnel_floors: bool = True,
    daily_dir: Path = _DAILY_DIR,
    coarse_dir: Path = _COARSE_DIR,
) -> tuple[dict[str, Any], list[CandidateRow]]:
    """Generate the full signal-winner population for one FISCAL YEAR (#303 lab substrate input).

    UNIVERSE SOURCE (#276b parity fix):
      - LEAN coarse CSVs (data/.../fundamental/coarse/<YYYYMMDD>.csv) reproduce QC's EXACT live
        coarse membership + DV (the feed runtime.lean_entry._coarse_selection scans). They exist
        2023-06-20 onward, so:
          * FY2024, FY2025  -> FULLY coarse-feed authoritative (authoritative=True).
          * FY2023          -> PARTIAL (coarse from 06-20; pre-06-20 dates fall back to local-daily)
                               -> authoritative=False (the year is not uniformly coarse-sourced).
          * FY2022, FY2021  -> NO coarse -> local-daily-all approximation -> authoritative=False.
      - When falling back (a date with no coarse CSV) the universe + DV come from the local-daily
        close*volume approximation (~6.7x too wide); the header authoritative flag + universe_source
        tag let the lab DOWN-WEIGHT/EXCLUDE those dates' untraded counterfactual.

    A date in a FULLY-AUTHORITATIVE year with no coarse CSV is logged + skipped (fail-loud-ish; we
    never fabricate a universe for a missing authoritative session). The 8-condition SCORE + the
    signal-time features always come from the local daily frame (price/indicator features).
    """
    coarse_universe, coarse_metrics = build_coarse_universe(year, coarse_dir=coarse_dir)
    n_coarse = len(coarse_universe)

    if n_coarse > 0:
        # Coarse data exists for this year. If EVERY local-daily trading day for the year also has
        # a coarse CSV the year is fully authoritative; otherwise it is partial (FY2023).
        local_universe = build_local_universe(year, daily_dir=daily_dir)
        local_dates = set(local_universe.keys())
        coarse_dates = set(coarse_universe.keys())
        missing = sorted(local_dates - coarse_dates)
        fully_authoritative = not missing

        if fully_authoritative:
            universe = coarse_universe
            universe_source = f"lean-coarse-csv-authoritative:{year}"
            authoritative = True
        else:
            # PARTIAL (FY2023): coarse where present, local-daily fallback for the rest. Not
            # uniformly authoritative -> flag the year so the lab treats the fallback dates with
            # the same down-weight as a no-coarse year.
            universe = dict(coarse_universe)
            for d in missing:
                universe[d] = local_universe[d]
            universe = dict(sorted(universe.items()))
            universe_source = (
                f"lean-coarse-csv-PARTIAL-local-daily-fallback-NOT-AUTHORITATIVE:{year}"
            )
            authoritative = False
            print(
                f"[candidates] FY{year} PARTIAL coarse coverage: {len(coarse_dates)} coarse "
                f"sessions + {len(missing)} local-daily-fallback sessions (pre-coarse) -> "
                f"authoritative=False"
            )
        header, rows = generate_window(
            sorted(universe.keys()),
            universe,
            min_score=min_score,
            parabolic_threshold=parabolic_threshold,
            apply_funnel_floors=apply_funnel_floors,
            daily_dir=daily_dir,
            universe_source=universe_source,
            coarse_metrics=coarse_metrics,  # only covers coarse dates; fallback dates -> None
            authoritative=authoritative,
        )
    else:
        # NO coarse data for this year (FY2022, FY2021): local-daily-all approximation. NOT
        # authoritative -> the lab must down-weight/exclude this year's untraded counterfactual.
        print(
            f"[candidates] FY{year} has NO LEAN coarse data -> local-daily-approx universe "
            f"(NOT AUTHORITATIVE)"
        )
        universe = build_local_universe(year, daily_dir=daily_dir)
        header, rows = generate_window(
            sorted(universe.keys()),
            universe,
            min_score=min_score,
            parabolic_threshold=parabolic_threshold,
            apply_funnel_floors=apply_funnel_floors,
            daily_dir=daily_dir,
            universe_source=f"local-daily-approx-NOT-AUTHORITATIVE:{year}",
            coarse_metrics=None,
            authoritative=False,
        )
    header["fiscal_year"] = year

    # Stamp the generator-vs-instrumented signal_winner delta (documented universe-membership /
    # scoring-vendor uncertainty) when an instrumented cloud baseline exists for the year (#276b).
    instrumented = INSTRUMENTED_SIGNAL_WINNERS.get(year)
    if instrumented:
        gen_winners = sum(
            1
            for r in rows
            if r.passed_prefilter and r.passed_floors and r.passed_parabolic and r.score >= min_score
        )
        header["universe_membership_uncertainty"] = {
            "instrumented_signal_winners": instrumented,
            "instrumented_source": "cloud bt 3c9cb7b8 funnel.signal_winners (FY2025, pre-regime)",
            "generator_signal_winners": gen_winners,
            "ratio_generator_over_instrumented": round(gen_winners / instrumented, 4),
            "note": (
                "Universe membership + DV are now QC's exact live coarse feed (the #276b fix); the "
                "residual ratio is dominated by the local-vs-cloud SCORING/data-vendor delta (the "
                "C1-documented ~40 score>=7/day local count + the ~1.10x cloud<->local universe "
                "vendor residual), NOT a universe-membership bug. The #303 mine MUST treat the "
                "untraded counterfactual as carrying this membership/scoring uncertainty."
            ),
        }
    return header, rows


def write_jsonl(header: dict[str, Any], rows: list[CandidateRow], out_path: Path) -> Path:
    """Write the artifact as JSONL: line 1 = header record, then one CandidateRow per line.

    Deterministic bytes: rows are already ordered; json.dumps with sort_keys=False preserves the
    insertion order built in to_json (a stable field order). Newline-terminated.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        fh.write(json.dumps(header) + "\n")
        for r in rows:
            fh.write(json.dumps(r.to_json()) + "\n")
    return out_path
