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
from runtime.universe_select import apply_floors, rank_and_cap

# Reuse the C1 harness loaders verbatim (the proven local LEAN daily-zip reader + as-of slicer).
from scripts.funnel_signal_count import (  # noqa: E402
    _DAILY_DIR,
    _PRICE_SCALE,
    load_daily_frame,
    load_universe,
    slice_as_of,
)

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
SCHEMA_VERSION: int = 1

# Number of float decimals retained in emitted feature values (determinism — no platform jitter).
_ROUND: int = 6


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

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "date": self.date,
            "symbol": self.symbol,
            "score": self.score,
            "rating": self.rating,
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


def generate_candidates_for_date(
    date_str: str,
    tickers: list[str],
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    parabolic_threshold: float = DEFAULT_PARABOLIC_THRESHOLD,
    apply_funnel_floors: bool = True,
    daily_dir: Path = _DAILY_DIR,
    frame_cache: dict[str, pd.DataFrame | None] | None = None,
) -> list[CandidateRow]:
    """Emit EVERY score>=min_score signal-winner on one decision date as a CandidateRow.

    Funnel order (the live def): prefilter (single-day DV) -> floors (close + trailing DV) ->
    rank+cap (DV-desc) -> bct prefilter (price>=sma200 & price>=cloud_top) -> parabolic (roc13) ->
    score>=min_score. Every name that scores >= min_score is emitted (with its passed_* flags) so
    the artifact is BOTH the (B)-emit AND the (A)-parity audit; the funnel signal_winners are the
    rows where passed_prefilter & passed_floors & passed_parabolic are all True.

    `apply_funnel_floors=False` = C1-parity mode: skip the prefilter/floors/rank gate (score the
    full coarse universe), so the score>=min_score count matches funnel_signal_count.py exactly.

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
        bar = upto.iloc[-1]
        c = float(bar["close"])
        sdv = c * float(bar["volume"])
        frames[ticker] = df
        close_today[ticker] = c
        single_day_dv[ticker] = sdv
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

        rows.append(
            CandidateRow(
                date=date_str,
                symbol=ticker.upper(),
                score=int(result["score"]),
                rating=str(result["rating"]),
                conditions=[bool(x) for x in result["conditions"]],
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
        )

    # Deterministic order: score DESC, then ticker ASC (stable, platform-independent).
    rows.sort(key=lambda r: (-r.score, r.symbol))
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
    ystr = str(year)
    # date -> {ticker_lower: (close, trailing_dv)} for names passing the single-day prefilter.
    per_date: dict[str, dict[str, tuple[float, float]]] = {}

    for fname in sorted(os.listdir(daily_dir)):
        if not fname.endswith(".zip"):
            continue
        ticker = fname[:-4].lower()
        with zipfile.ZipFile(daily_dir / fname) as zf:
            names = zf.namelist()
            if not names:
                continue
            raw = zf.read(names[0]).decode()
        dates: list[str] = []
        dvs: list[float] = []
        closes: list[float] = []
        for line in raw.strip().split("\n"):
            if not line:
                continue
            p = line.split(",")
            ds = p[0][:8]
            c = float(p[4]) / _PRICE_SCALE  # same unscale convention as load_daily_frame
            v = float(p[5])
            dates.append(ds)
            closes.append(c)
            dvs.append(c * v)
        for i, ds in enumerate(dates):
            if ds[:4] != ystr:
                continue
            sdv = dvs[i]
            if sdv < PREFILTER_DV:
                continue
            close = closes[i]
            window = dvs[max(0, i - (ADV_WINDOW - 1)): i + 1]
            tdv = sum(window) / len(window)
            iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
            per_date.setdefault(iso, {})[ticker] = (close, tdv)

    universe: dict[str, list[str]] = {}
    for iso, bar_metrics in per_date.items():
        eligible = apply_floors(
            bar_metrics, min_price=MIN_PRICE, min_avg_dollar_volume=MIN_AVG_DOLLAR_VOLUME
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=COARSE_MAX)
        if ranked:
            universe[iso] = [t.upper() for t in ranked]
    return dict(sorted(universe.items()))


def _artifact_header(
    dates: list[str], min_score: int, parabolic_threshold: float, apply_funnel_floors: bool,
    universe_source: str,
) -> dict[str, Any]:
    """Provenance/header record (first JSONL line, record_type='header') — stamps the data vendor,
    normalization, funnel params and the exact funnel def so the lab can detect any drift."""
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
        "n_dates": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "fields": [
            "date", "symbol", "score", "rating",
            "cond_0", "cond_1", "cond_2", "cond_3", "cond_4", "cond_5", "cond_6", "cond_7",
            "close", "daily_tenkan", "daily_kijun", "sma200",
            "daily_cloud_a", "daily_cloud_b", "daily_cloud_top",
            "weekly_cloud_a", "weekly_cloud_b", "weekly_cloud_top",
            "weekly_tenkan", "weekly_kijun",
            "adx", "plus_di", "minus_di", "roc13",
            "single_day_dv", "trailing_dv", "scanner_rank",
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
) -> tuple[dict[str, Any], list[CandidateRow]]:
    """Generate the candidate population over a window of decision dates.

    `universe` is {date -> [tickers]}; default = the FY2025 polygon snapshot. For ANY year, pass a
    universe built by `build_local_universe(year)` (live-coarse-equivalent from local daily).

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
            )
        )
    header = _artifact_header(
        date_list, min_score, parabolic_threshold, apply_funnel_floors, universe_source
    )
    return header, all_rows


def generate_year(
    year: int,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    parabolic_threshold: float = DEFAULT_PARABOLIC_THRESHOLD,
    apply_funnel_floors: bool = True,
    daily_dir: Path = _DAILY_DIR,
) -> tuple[dict[str, Any], list[CandidateRow]]:
    """Generate the full signal-winner population for one FISCAL YEAR, computing the coarse
    universe per-day from the local daily zips (live-coarse-equivalent). Works for any year the
    local data covers. The per-year artifact the #303 lab joins onto its forward-outcome oracle.
    """
    universe = build_local_universe(year, daily_dir=daily_dir)
    header, rows = generate_window(
        sorted(universe.keys()),
        universe,
        min_score=min_score,
        parabolic_threshold=parabolic_threshold,
        apply_funnel_floors=apply_funnel_floors,
        daily_dir=daily_dir,
        universe_source=f"local-daily-coarse-equivalent:{year}",
    )
    header["fiscal_year"] = year
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
