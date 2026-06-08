"""LEAN entry (#213 / #238) — the single code path that runs the engine LOCAL and CLOUD.

This is the historic #182 divergence site. The legacy main.py diverged because it loaded
the universe from DISK locally but ObjectStore on cloud, AND silently fell through when the
cloud key was missing — so cloud and local selected different stocks from day 1.

#238 replaces the stored-universe-file mechanism (the 326 scar — a frozen date→ticker file
shipped to ObjectStore) with a LIVE once-daily computation. Per Falk's Y ruling, the floors
+ rank are applied AT THE SELECTION GATE (here, in _coarse_selection) — NOT in a per-bar
phase. The filtering is NOT removed: it MOVES to selection, where it now bounds SUBSCRIPTION
(only qualifying names get tracked + Ichimoku'd). The redundant per-bar filter phase is
dropped. This is Falk's exact model: "filter selects tickers, passes them to Ichimoku."

  - QC's coarse-fundamental feed is GROUND TRUTH. `add_universe(coarse_selection)` runs the
    selection ONCE-DAILY:
      1. MAINTAIN a rolling 20-day dollar-volume per coarse name from the coarse feed's
         single-day DV (qc._dv_windows; NO history() call) → bar_metrics {ticker: (close,
         trailing_dv)} where close = the coarse row's close and trailing_dv = mean of the
         maintained window. (SCALING FIX: replaces the per-day RAW history() fan-out over the
         survivors — ~20x slower on cloud — with an O(1)/name maintained rolling mean. Local:
         coarse single-day DV is bit-identical to RAW close*volume by the #238 conform (GATE 1
         — a local tautology, NOT cloud proof). Cloud robustness rests on DV being split-
         invariant — sound for a LIQUIDITY floor, does not cover dividend-adjust; validated at
         the cloud Step-A active-set parity, not asserted here. ASSUMPTION: the rolling-20d mean
         equals the old history(20) mean only if the coarse feed delivers every tradeable name
         each day it trades; a 1-19d coarse gap would blend stale DV on reappearance — benign
         under the normal QC coarse contract.);
      2. `apply_floors` (close >= MIN_PRICE AND trailing_dv >= MIN_AVG_DOLLAR_VOLUME) →
         eligible (the SELECTION GATE — the floor that used to be a per-bar phase);
      3. `rank_and_cap` (DV-desc, ticker-asc tiebreak, cap COARSE_MAX) → ranked.
    `qc._ranked_today` = the floored+ranked+capped selection (the universe phase exposes it);
    `qc._trailing_dv` = the dv view for the signal's tiebreak; `qc._bar_metrics` = the full
    survivor metric map, kept for the diff-ladder (no phase reads it). SUBSCRIBE ONLY the
    ranked qualifying set — the whole point of Y: only what passes the floors gets tracked +
    Ichimoku'd → no 2x indicator load. NO stored universe file, NO ObjectStore artifact, NO
    fingerprint-verify-on-file (those guarded the file mechanism that no longer exists).
  - LOCAL SIMULATES CLOUD: local runs the IDENTICAL coarse_selection over conformed-coarse
    data (the local-coarse conform is a separate HQ decision — see #238 step E flag). NO
    `if cloud:` branch — one code path both sides.
  - RAW normalization on every subscription (the 2649e2e lesson — adjusted prices corrupt
    Ichimoku). The maintained rolling-DV needs no history() at all; the rolling window FILLS
    DURING WARMUP (the coarse callback runs each warmup day too), so with WARMUP_DAYS ≥ 20 the
    window is full before live trading — NO startup history() seed needed.
  - ACTIVE-SET hash logged each rebalance (count + sha256 of the sorted ranked tickers) —
    the diff-ladder selection rung between the universe selection and the trades.

`coarse_to_dollar_volume` is PURE (no QC types) and unit-tested with a fake coarse list.
`apply_floors` / `rank_and_cap` (runtime.universe_select) are golden-mastered. The QC-runtime
glue (coarse_selection's history() + add_universe + Symbol construction) is integration-
verified on a LEAN run — pragma:no cover, not unit-testable in the dev venv.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

import pandas as pd

from engine.base import DegradedDataError, DegradedScheduleError
from engine.context import OrderIntent, PhaseContext
from engine.engine import StrategyEngine
from engine.symbol_key import canonical_symbol_key
from phases.shared.oracle_helpers import score_symbol_native
from runtime.cost_model import wire_cost_models
from runtime.george_attention import load_george_attention_maps
from runtime.tag_schema import encode_entry_tag
from runtime.indicators import INDICATOR_KEYS, TBounceTracker, weekly_aggregate
from runtime.security_profiles import load_security_profile_maps
# #336/#338 continuous-weekly fix: WeeklyIchimokuAsOf is imported LAZILY inside
# _continuous_weekly_scalars (the flag-ON path only) so the default flag-OFF load path adds NO new
# import dependency — keeps the cloud bundle byte-untouched until the cloud leg is taken (deferred).
from runtime.universe_select import (
    DvWindow,
    apply_floors,
    rank_and_cap,
    rolling_dv_mean,
    update_dv_windows,
)
from runtime.watchlist_carry import select_watchlist_carry


def coarse_to_dollar_volume(coarse: Iterable[Any]) -> dict[str, float]:
    """Extract {ticker -> single-day dollar volume} from a coarse-fundamental feed.

    PURE (no QC types): each `c` is any object exposing `.symbol.value` (the ticker) and
    `.dollar_volume` (single-day $). Ticker is lower-cased to the on-disk/zip-stem convention
    so it matches qc._active.value.lower() downstream (the universe phase + signal compare
    case-insensitively). This is the prefilter input AND the per-day value pushed into the
    maintained rolling-DV windows (qc._dv_windows) — a LOOSE perf-bound on which names build a
    (close, trailing_dv) metric, NOT a strategy threshold.
    """
    out: dict[str, float] = {}
    for c in coarse:
        ticker = str(c.symbol.value).lower()
        dv = float(c.dollar_volume)
        # FAIL-LOUD GUARD (#261-2): a NaN/Inf single-day DV must NOT enter the rolling-DV window
        # (it would poison the trailing mean, then pass apply_floors / dominate the DV-desc rank
        # — the silent-garbage-selected mirage). Crash with the offending ticker + value.
        if not math.isfinite(dv):
            raise DegradedDataError(
                f"non-finite coarse dollar_volume: ticker={ticker!r} dollar_volume={dv!r}; "
                f"degraded data must fail loud, never enter the rolling-DV window (#261-2)"
            )
        out[ticker] = dv
    return out


def coarse_to_close(coarse: Iterable[Any]) -> dict[str, float]:
    """Extract {ticker -> RAW close price} from a coarse-fundamental feed for the price floor.

    PURE (no QC types): each `c` exposes `.symbol.value` + `.price`. Uses `.price` (the RAW
    price — LEAN CoarseFundamental.Price, verified against the LEAN docs) NOT `.adjusted_price`
    (split/dividend-adjusted prices corrupt the RAW-price contract — the 2649e2e lesson). This
    replaces the per-day history() close. (LOCAL: coarse `.price` == RAW history close exactly,
    0.000% over the 2025 sample — but that is bit-identical BY the #238 conform, a tautology
    that confirms the field mapping, NOT cloud proof. On cloud the price floor reads QC's coarse
    `.price`, which is the RAW price per the LEAN field contract.) Ticker lower-cased to the
    zip-stem / qc._active convention. The price floor (apply_floors close-leg) reads this map."""
    out: dict[str, float] = {}
    for c in coarse:
        ticker = str(c.symbol.value).lower()
        price = float(c.price)
        # FAIL-LOUD GUARD (#261-2): a NaN/Inf coarse close is degraded data — it must NOT feed
        # the price floor (NaN silently fails the floor → name vanishes; Inf silently passes).
        # Crash with the offending ticker + value rather than absorb it into the gate.
        if not math.isfinite(price):
            raise DegradedDataError(
                f"non-finite coarse price (close): ticker={ticker!r} price={price!r}; "
                f"degraded data must fail loud, never feed the price floor (#261-2)"
            )
        out[ticker] = price
    return out


# #276b-1 FUNNEL stages — the 9 CUMULATIVE candidate-collapse counters. The collapse STAGE localizes
# Falk's "78 is too sparse" verdict (legit selectivity vs a bug). Order = the candidate's path
# through the two clocks:
#   DAILY:    signal_winners → regime_pass  (+ regime_blocked_days, the SEPARATE regime cut)
#   INTRADAY: preflight_pass → gap_eligible → confirm_fire → injection_survives → sized → cash_ok
#   FIRE:     orders
# The INTRADAY stages are recorded as per-tick survivor SETS on ctx.bar_state.funnel by the gate
# phases (observe-only, zero behavior change); the runtime folds them at session end.
FUNNEL_DAILY_STAGES: tuple[str, ...] = ("signal_winners", "regime_pass", "regime_blocked_days")
FUNNEL_INTRADAY_STAGES: tuple[str, ...] = (
    "preflight_pass", "gap_eligible", "confirm_fire", "injection_survives", "sized", "cash_ok",
)
FUNNEL_FIRE_STAGES: tuple[str, ...] = ("orders",)
FUNNEL_STAGES: tuple[str, ...] = (
    FUNNEL_DAILY_STAGES + FUNNEL_INTRADAY_STAGES + FUNNEL_FIRE_STAGES
)

# #276b-1 FIX (#303 mine clean-counter): the SEMANTIC LEGEND. Each stage counts ONE of three units —
# the mine MUST NOT compute a cross-stage pass-RATE without first reading this legend, because the
# units differ (a "rate" between two different units is nonsense). The clean funnel run showed
# preflight_pass (7817) + injection_survives (12239) EXCEEDING signal_winners (7007) → a misread
# >100% rate: an unentered candidate persists in the snapshot and RE-INJECTS every day until
# entered/refreshed, so a per-DAY count of those two stages counts candidate-DAYS-incl-reinjection,
# not distinct candidates. Fix: those two stages count DISTINCT candidates (each symbol once, the
# first time it EVER reaches the stage, via a run-cumulative symbol set). The semantics:
#   "distinct"        — each distinct candidate (by symbol) counted ONCE over the whole run (the
#                       run-cumulative symbol set; reinjection/re-evaluation does NOT re-count).
#   "candidate_days"  — a (candidate, day) pair counted once: a name reaching the stage on N
#                       distinct days legitimately counts N (a per-day survivor set, accumulated).
#   "daily"           — a per-decision count summed across days (signal_winners = winners/day summed;
#                       regime_pass likewise; regime_blocked_days = #days blocked).
#   "fire"            — distinct order fires (each entry fire is one order; no dedup).
# DISTINCT-candidate stages (a name counted once over the run): preflight_pass, injection_survives.
# CANDIDATE-DAY stages (a name reaching the stage on N days counts N): gap_eligible, confirm_fire,
# sized, cash_ok. The asymmetry is intentional — a gap on N distinct days IS N gap-eligible-days.
FUNNEL_DISTINCT_STAGES: tuple[str, ...] = ("preflight_pass", "injection_survives")
# the per-day-accumulated intraday stages (the original per-candidate-DAY semantics).
FUNNEL_CANDIDATE_DAY_STAGES: tuple[str, ...] = tuple(
    s for s in FUNNEL_INTRADAY_STAGES if s not in FUNNEL_DISTINCT_STAGES
)
# stage → semantic-unit map (module-level constant; the robust, machine-readable legend the mine
# reads to avoid misreading a rate). DO NOT rename the runtime-stat keys (that breaks the existing
# read) — this legend is the ADDITIVE label.
FUNNEL_STAGE_SEMANTICS: dict[str, str] = {
    "signal_winners": "daily",
    "regime_pass": "daily",
    "regime_blocked_days": "daily",
    "preflight_pass": "distinct",
    "gap_eligible": "candidate_days",
    "confirm_fire": "candidate_days",
    "injection_survives": "distinct",
    "sized": "candidate_days",
    "cash_ok": "candidate_days",
    "orders": "fire",
}


def active_set_hash(symbols: Iterable[str]) -> tuple[int, str]:
    """(count, sha256-of-sorted-symbols) for the live-selected ranked set. Logged each
    rebalance so divergence-debug can diff the selection local-vs-cloud — the rung between
    the universe selection and the trade list. A small delta is the accepted cloud-vendor
    coverage residual; a material delta gets root-caused."""
    syms = sorted(symbols)
    h = sha256(",".join(syms).encode("utf-8")).hexdigest()
    return len(syms), h


# --------------------------------------------------------------------------------------
# QCAlgorithm shell — QC runtime only. Thin: the SELECTION GATE (_coarse_selection) delegates
# the pure extraction (coarse_to_dollar_volume) + the pure floors/rank (apply_floors,
# rank_and_cap) to the tested functions above, then subscribes ONLY the ranked qualifying set
# (Falk's Y model — floors at selection, no per-bar filter phase). Integration-verified on a
# LEAN run, not unit-tested (no QC locally). main.py (generated by build/cloud_package.py)
# sets the class attributes below.
# --------------------------------------------------------------------------------------
try:  # pragma: no cover - QC runtime import; absent in the dev venv / unit tests
    from AlgorithmImports import (
        Calendar,
        DataNormalizationMode,
        Field,
        IchimokuKinkoHyo,
        Market,
        MovingAverageType,
        OrderStatus,
        QCAlgorithm,
        Resolution,
        RollingWindow,
        SecurityType,
        Symbol,
        TradeBar,
        TradeBarConsolidator,
    )
except ImportError:  # pragma: no cover
    QCAlgorithm = object
    DataNormalizationMode = Resolution = SecurityType = Market = Symbol = None
    Calendar = IchimokuKinkoHyo = RollingWindow = TradeBar = TradeBarConsolidator = None
    Field = MovingAverageType = OrderStatus = None


def _to_decimal(x: Any) -> Decimal:
    """python float → System.Decimal-safe value (#318 FY crash). Cloud pythonnet rejects a raw
    python ``float`` on a Decimal-typed property ("'float' value cannot be converted to
    System.Decimal") AND rejects NaN/inf. So convert to ``decimal.Decimal`` and finite-guard
    (a missing-volume bar → NaN → would otherwise crash deep in the run, as the FY did at ~69%)."""
    xf = float(x)
    if not math.isfinite(xf):
        return Decimal("0")
    return Decimal(str(xf))


def _make_trade_bar(
    time: Any, symbol: Any, open_: float, high: float, low: float, close: float,
    volume: float, period: Any,
) -> Any:
    """Cloud-safe SYNTHETIC TradeBar construction (#318) — used by ``_seed_weekly`` ONLY (the
    aggregated weekly bar has no native-history source to read). The two real-history seeds
    (``_seed_intraday`` / ``_seed_daily``) read native bars via ``self.history[TradeBar]`` and
    construct NOTHING — that kills the cloud-interop class at those sites entirely.

    Two cloud pythonnet failure modes are avoided here, both observed in #318:
      1. the 8-positional-arg ctor's overload resolution on a ``datetime.timedelta`` period (the
         first crash, at ``_seed_intraday``) → use the no-arg ctor + single-target property setters
         (no overload ambiguity);
      2. ``float → System.Decimal`` coercion on the Decimal OHLCV/volume setters (the FY crash at
         ~69%) → assign ``decimal.Decimal`` values, finite-guarded (``_to_decimal``).
    Behaviour-identical to the positional ctor: same OHLCV + period ⇒ same bar
    (``end_time == time + period``)."""
    bar = TradeBar()
    bar.symbol = symbol
    bar.time = time
    bar.period = period
    bar.open = _to_decimal(open_)
    bar.high = _to_decimal(high)
    bar.low = _to_decimal(low)
    bar.close = _to_decimal(close)
    bar.volume = _to_decimal(volume)
    return bar


class BctEngineAlgorithm(QCAlgorithm):  # pragma: no cover - QC runtime
    """Thin LEAN wrapper. Subclass in main.py sets STRATEGY_CONFIG / dates / cash / the
    universe-selection knobs. initialize() subscribes SPY+VIX RAW, registers the live
    coarse-driven SELECTION GATE (add_universe → maintain rolling-DV → prefilter → apply_floors
    → rank_and_cap → qc._ranked_today; subscribe ONLY the ranked qualifying set — Falk's Y
    model, floors at selection, no per-bar filter phase), and runs StrategyEngine per
    scheduled bar."""

    # set by the generated main.py subclass
    STRATEGY_CONFIG: Any = None
    START_DATE: tuple[int, int, int] = (2025, 1, 1)
    END_DATE: tuple[int, int, int] = (2025, 12, 31)
    CASH: int = 100_000

    # Live universe selection knobs — the floors now live HERE (Y: floors at the selection
    # gate, no per-bar filter phase). MIN_PRICE / MIN_AVG_DOLLAR_VOLUME drive apply_floors;
    # COARSE_MAX caps rank_and_cap; PREFILTER_DV + ADV_WINDOW govern the prefilter + the
    # maintained rolling-DV window (qc._dv_windows). The single source for all of them.
    PREFILTER_DV: float = 25_000_000.0
    MIN_PRICE: float = 10.0
    MIN_AVG_DOLLAR_VOLUME: float = 100_000_000.0
    COARSE_MAX: int = 9999
    ADV_WINDOW: int = 20  # trailing trading-day window for the maintained mean-DV decision

    # FAIL-LOUD threshold (#261-6, broken-0 guard) — EXPLICIT + parameterized, never a hidden
    # cap. A real QC coarse session delivers THOUSANDS of names (FY2025 feeds carry >10k rows);
    # a feed of >= this many names that COLLAPSES to a zero selection is the −0.616 mirage and
    # must fail loud. Below this count the feed is too sparse to call a collapse "broken" (an
    # early/thin synthetic or genuinely-sparse day → benign correct-0, no raise). This is a
    # diagnostic guard threshold, NOT a strategy knob: it is NOT in STRATEGY_CONFIG and does
    # NOT enter the config_hash (the happy path — a populated feed selecting names — is
    # byte-unchanged). Conservative default (100) sits far below the real feed size and far
    # above any legitimate sparse day.
    BROKEN_ZERO_MIN_FEED: int = 100

    # Indicator warmup length — DERIVED, not copied (the 750d was an un-derived "exact legacy"
    # carve in #213c). Binding constraint = the WEEKLY IchimokuKinkoHyo(9,26,26,52,26,26).
    # Its EXACT readiness (LEAN source Indicators/IchimokuKinkoHyo.cs):
    #     WarmUpPeriod = max(tenkan+senkouADelay, kijun+senkouADelay, senkouB+senkouBDelay)
    #                  = max(9+26, 26+26, 52+26) = 78 bars   (SenkouB = Delay(26) of Max(52))
    # IsReady requires SenkouA && SenkouB && Tenkan && Kijun -> 78 WEEKLY bars to be fully ready.
    #   78 weekly-Ichimoku readiness bars = 78 weeks; +1 leading partial-week (no complete bar)
    #   = 79 weeks x 7 = 553 cal days; +7d (1 week) holiday/Monday-seed-alignment buffer = 560.
    # Cross-check (weekly is BINDING): daily Ichimoku(78 trading days) ≈ 109 cal days; the
    # 200-day SMA (200 trading days) ≈ 280 cal days — both < 560. So 560d covers all signals.
    # NOTE: this is the FULL-SIGNAL warmup. A Step-A-parity-only override may set ~40d; that is
    # NOT the strategy default and must never be hardcoded here.
    WARMUP_DAYS: int = 560
    # #368 the WEEKLY warmup floor (bars): the weekly Ichimoku needs Senkou-B(52wk) + 26wk forward
    # displacement ≈ 78 weeks; 560 daily bars ≈ 112 weeks ≥ 78. The fail-loud guard re-derives a
    # weekly-cache MISS from max(WARMUP_DAYS, WEEKLY_FLOOR_DAYS) so an in-window cache GAP is DETECTED
    # (computable) vs a legit pre-78wk/post-delist miss (uncomputable) — even when WARMUP_DAYS is
    # trimmed below the weekly floor (the trim+cache speed path: daily indicators warm at the trimmed
    # WARMUP_DAYS, the weekly comes from the cache, this floor = the fail-loud/computability test).
    WEEKLY_FLOOR_DAYS: int = 560
    # #336/#338 ws1 — CONTINUOUS-WEEKLY fix (default OFF = byte-untouched ship path). When True, the
    # daily decision re-derives each candidate's weekly Ichimoku from full CONTINUOUS daily history
    # (WeeklyIchimokuAsOf over self.history — bypasses the subscription-gated consolidator at the
    # source, the #336 root) + populates qc._warmup_cache so the BctScoreFull cache branch scores the
    # CONTINUOUS weekly. LIVE-behavior change → flag-gated; the offline cache + gate validate it.
    CONTINUOUS_WEEKLY: bool = False
    # #358 warmup-cache CONSUMPTION HOOK (default OFF/None = byte-untouched ship path). When the
    # CONTINUOUS_WEEKLY decision re-derives each candidate's weekly from history(560d) per day (the
    # ~38-120s/cell cost), these let it LOAD the precomputed weekly from the #332 cache via the LEAN
    # ObjectStore instead (QC-native in-container delivery). The LOCAL harness injects ONLY the data
    # fingerprint here; the ObjectStore KEY is DERIVED from it via the shared keys.weekly_cache_key()
    # formula — the SAME formula the offline writer uses → write_key == read_key by construction (no
    # drift). FAIL-CLOSED cloud guard (the 8b50c1a lesson), TWO layers: (1) the key is validity-scoped
    # (type+fp+params) + LOCAL-ONLY (never uploaded) → cloud object_store.contains_key False → no load;
    # (2) the blob's embedded fingerprint must also match. Cloud sets no fp → live re-derivation
    # (canonical). A HIT is byte-identical to the re-derive (same WeeklyIchimokuAsOf, same data).
    WARMUP_WEEKLY_CACHE_FP: str | None = None
    # #348 instrumentation flag (default OFF → live path byte-untouched): when set (via
    # SWEEP_CLASS_ATTRS for a trace run) the signal phase emits DECISIONTRACE log lines per scored
    # candidate (the NON-TRADES substrate). Pure logging — no decision effect.
    DECISION_TRACE: bool = False
    # #313: the daily DECISION fires on a scheduled AFTER-CLOSE event (decoupled from on_data
    # bar-presence). Minutes after SPY's close → T's daily data is complete (no T+1 look-ahead),
    # the daily indicators are warm with T's bar, the universe selection for T is current.
    AFTER_CLOSE_MIN: int = 10

    # #275b INTRADAY execution clock (Option C): the daily selection produces candidates for T+1;
    # on T+1 those names get a 5-min subscription (our Massive is natively 5-min, stored as LEAN
    # "minute" → subscribe Resolution.MINUTE, consume directly, NO consolidator). The subscription
    # set is candidate∩CAP + current holdings ONLY — NEVER the whole universe (the #213e OOM scar).
    # INTRADAY_SUBSCRIBE_CAP is the EXPLICIT, parameterized, logged ceiling on the daily-candidate
    # slice that gets an intraday feed (a scan-breadth cap, NOT a position count-cap — distinct,
    # like COARSE_MAX). INTRADAY_TENKAN / INTRADAY_VOL_WINDOW are in 5-MIN-BAR units (Tenkan(9) =
    # 45 min) — the GH#25 intraday-confirm inputs the #276 entry phase reads.
    INTRADAY_SUBSCRIBE_CAP: int = 50
    INTRADAY_TENKAN: int = 9
    INTRADAY_VOL_WINDOW: int = 20

    # #321 realistic IBKR cost+slippage. SLIPPAGE_PERCENT = the EXPLICIT, version-pinned per-side
    # slippage fed to ConstantSlippageModel (5 bps; conservative for the liquid ADV>=$100M universe).
    # Same treatment as the universe knobs above: a lean_entry class attr (single source), NOT in
    # STRATEGY_CONFIG → config_hash is byte-unchanged; the GIT COMMIT records the cost change. The
    # IB fee + this slippage are installed on every equity via a security initializer in initialize()
    # (runtime.cost_model.wire_cost_models) — local AND cloud, one code path, no `if cloud` branch.
    SLIPPAGE_PERCENT: float = 0.0005

    # #archive B2: the per-entry context tag length cap. The entry order's `tag` is the ONE durable
    # learn-substrate channel (recovered via /orders/read; logs/charts/ObjectStore are dead). The
    # tag NEVER silently truncates — over the cap is fail-loud (a truncated tag = corrupt learn
    # data). PROVISIONAL 200; refine via the EMPIRICAL probe (submit increasing-length tags to QC,
    # find the real truncation/reject point, set this to <90% of it + a CI assert). #archive-followup.
    ENTRY_TAG_MAX: int = 200

    # George-context runtime hooks (#416 PR2 foundation). Default OFF/None and deliberately inert
    # in this PR: the selection-gate carry behavior lands in the next PR after these knobs are
    # typed, hashable, and emitted by the build.
    WATCHLIST_CARRY_MAX: int = 0
    WATCHLIST_CARRY_MIN_PRICE: float = 10.0
    WATCHLIST_CARRY_MIN_AVG_DOLLAR_VOLUME: float = 100_000_000.0
    SECURITY_PROFILE_SOURCE: str | None = None
    GEORGE_ATTENTION_SOURCE: str | None = None

    def initialize(self) -> None:
        self.set_start_date(*self.START_DATE)
        self.set_end_date(*self.END_DATE)
        self.set_cash(self.CASH)
        self.set_benchmark("SPY")
        self.set_time_zone("America/New_York")  # match legacy champion (scheduling/timestamps)
        self.set_warmup(timedelta(days=self.WARMUP_DAYS))
        # #336/#338 continuous-weekly: CONTINUOUS_WEEKLY is the class-attr master switch (default OFF =
        # byte-untouched ship path; set True via class-attr injection for a flag-on run). flag-on → arm
        # qc._warmup_cache so the BctScoreFull cache branch consumes the per-decision
        # continuous-weekly scalars populated in _on_after_close_decision.
        if self.CONTINUOUS_WEEKLY:
            self._warmup_cache: dict[str, dict[str, Any]] = {}

        # #358 consumption hook: load the precomputed weekly cache IF the local harness injected the
        # dir + the expected data fingerprint AND it matches (FAIL-CLOSED — load_weekly_cache returns
        # None on cloud / mismatch / missing → _weekly_scalars_for re-derives live, no divergence).
        # #358 per-SYMBOL LAZY consumption: arm with the data fingerprint + an empty per-symbol memo;
        # each symbol's weekly loads from its own ObjectStore key on FIRST query (covers ALL active
        # names without a giant blob — the 1.8GB-OOM avoidance). _weekly_cache_fp is set ONLY flag-on
        # AND when an object_store exists; cloud sets no fp → None → live re-derivation (fail-closed).
        self._weekly_cache_hits: int = 0    # #358 engagement signal — proves the cache actually served
        self._weekly_cache_misses: int = 0  # lookups, not just that it armed (HQ: speedup w/o hits = silent fail-closed)
        self._symbol_sparse: dict[str, bool] = {}  # #370 (2')-(i): per-symbol sparsity, classified once
        self._weekly_cache_fp: str | None = None
        self._weekly_loaded: dict[str, dict[Any, dict[str, float]] | None] = {}  # per-sym memo (None = attempted-missing)
        if self.CONTINUOUS_WEEKLY and self.WARMUP_WEEKLY_CACHE_FP and getattr(self, "object_store", None) is not None:
            self._weekly_cache_fp = self.WARMUP_WEEKLY_CACHE_FP
            self.log(f"#358 weekly-cache: per-symbol lazy-load ARMED (fp {self._weekly_cache_fp[:12]}…)")
        else:
            self.log("#358 weekly-cache: NOT armed (fail-closed → live re-derivation)")

        # RAW normalization everywhere — adjusted prices corrupt Ichimoku (2649e2e).
        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.data_normalization_mode = DataNormalizationMode.RAW

        self.spy = self.add_equity("SPY", Resolution.DAILY)
        self.spy.set_data_normalization_mode(DataNormalizationMode.RAW)
        self.spy_sma200 = self.sma("SPY", 200)  # regime gate (spy_200ma phase reads this)
        # VIX is the CBOE INDEX (add_index), matching the proven legacy champion — NOT
        # add_equity("VIX") (a different USA-equity symbol the regime gate must not read).
        # Indices carry no splits/dividends, so no normalization mode applies.
        self.vix = self.add_index("VIX", Resolution.DAILY).symbol
        self.vix_ichi = self.ichimoku(self.vix, 9, 26, 26, 52, 26, 26)  # vix regime phase

        # Per-symbol indicator lifecycle state (#213c). _active = currently-subscribed set
        # (managed by on_securities_changed); _indicators = qc._indicators contract the phases
        # read; _position_meta is populated by the engine on fills.
        self._active: set[Any] = set()
        self._indicators: dict[Any, dict[str, Any]] = {}
        self._position_meta: dict[Any, Any] = {}
        self._security_profiles: dict[str, dict[str, Any]] = {}
        self._industry_by_ticker: dict[str, str] = {}
        self._sector_by_ticker: dict[str, str] = {}
        self._proxy_by_ticker: dict[str, str] = {}
        self._george_attention_ticker: dict[str, float] = {}
        self._george_attention_industry: dict[str, float] = {}
        self._george_source_role_counts: dict[str, int] = {}
        self._load_optional_george_context()

        # #275b INTRADAY state — SEPARATE from _indicators (which carries the strict daily
        # INDICATOR_KEYS contract). _intraday[sym] = {intraday_tenkan, vol_window, last_close,
        # last_bar}, fed directly by the 5-min ("minute") bars in on_data. _intraday_active =
        # the symbols currently holding a 5-min subscription (candidate∩CAP + holdings). Kept
        # apart so the daily suite + its contract guard are untouched, and the intraday lifecycle
        # (subscribe/seed/remove) is isolated + independently testable.
        self._intraday: dict[Any, dict[str, Any]] = {}
        self._intraday_active: set[Any] = set()

        # #276b-0 daily→intraday SNAPSHOT handoff. _candidate_snapshot[sym] = {signal_price,
        # daily_kijun, decision_date}: each DECIDED candidate's thesis, captured on the daily clock
        # (in the #313 scheduled after-close callback) for the intraday clock (PreFlightStaleness +
        # confirm read it). REUSE-IDENTITY: keyed by the SAME canonical Symbol _active/_intraday use
        # — never a re-created Symbol (kills the subscribed≠decided desync by construction). Rebuilt
        # fresh each daily decision. _entry_confirm = the deferred intraday-confirm PROGRESS store
        # (populated by the #276b-1 confirm phase), cleared at session-end (on_end_of_day, H3/SG9).
        # _last_daily_date = the most-recent daily-decision date — serves BOTH #313's once-per-date
        # guard (_on_after_close_decision) AND 276b-0's H2 staleness check (snapshot_for_entry).
        self._candidate_snapshot: dict[Any, dict[str, Any]] = {}
        self._last_daily_date: Any = None
        self._entry_confirm: dict[Any, Any] = {}
        # #276b-1 candidate-injection PENDING-STATE (Gemini fix #1): syms with an entry order
        # IN-FLIGHT this session. Injection skips invested ∪ pending so an in-flight entry is not
        # re-injected (double-entry); a broker REJECT (Canceled/Invalid) drops it from pending →
        # re-injectable next tick (a transient reject is not a permanently-lost trade). Driven by
        # on_order_event terminal status; cleared at session end.
        self._pending_entry_today: set[Any] = set()
        # SAME-SESSION RE-ENTRY GUARD (the SHOP-churn fix): syms whose ENTRY FILLED this session.
        # A filled entry that then stops out (e.g. the #290 GTC floor firing intrabar → flat again,
        # no longer invested ∪ pending) was RE-INJECTABLE → re-confirmed → re-fired → instant
        # stop-out churn (SHOP fired 7× in 30min on the FY baseline). One entry-FILL per name per
        # session: injection also skips _entered_today. Marked on entry FILL (not submit, not a
        # reject — a Canceled/Invalid reject stays re-injectable, the retry-on-reject intent).
        # Cleared at session end (no T+2 bleed).
        self._entered_today: set[Any] = set()

        # #276b-1 FUNNEL — the 9 cumulative candidate-collapse counters (localizes Falk's "78 is too
        # sparse"). See FUNNEL_STAGE_SEMANTICS for the per-stage UNIT. _funnel_cum[stage] = the
        # FY-cumulative counter. _funnel_today[stage] = the per-DAY survivor SYMBOL SET for the
        # intraday stages (set membership = the per-day dedup: a candidate evaluated every 5-min tick
        # counts ONCE/day at each stage). _funnel_seen[stage] = the RUN-cumulative symbol set for the
        # DISTINCT stages (preflight_pass/injection_survives) — it persists across the whole run (never
        # reset per-day) so each distinct candidate is counted ONCE, the first time it EVER reaches the
        # stage (the reinjection-overcount fix; #303 mine clean-counter). The daily stages + the fire
        # stage (orders) accumulate DIRECTLY into _funnel_cum. At session end the intraday per-day sets
        # fold into _funnel_cum (candidate-day stages += len; distinct stages = len(_funnel_seen)).
        # Observe-only: NOTHING in the trading path reads these. Pushed as QC runtime stats.
        self._funnel_cum: dict[str, int] = {stage: 0 for stage in FUNNEL_STAGES}
        self._funnel_today: dict[str, set[Any]] = {stage: set() for stage in FUNNEL_INTRADAY_STAGES}
        self._funnel_seen: dict[str, set[Any]] = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}

        # #313 WATCHDOG (the permanent protection vs silent no-fire): the daily decision must keep
        # pace with elapsed trading days. _sched_trading_days counts post-warmup trading days (the
        # universe coarse callback, which fires reliably daily); _sched_decisions counts daily
        # decisions that actually ran. If they diverge beyond the 1-day pending tolerance, the
        # scheduled after-close event has gone dark → DegradedScheduleError (crash, never run blind).
        self._sched_trading_days: int = 0
        self._sched_decisions: int = 0

        # LIVE universe state (#238 / Y). _ranked_today = today's floored+ranked+capped
        # SELECTION (the universe phase exposes it ∩ active, in rank order); _trailing_dv =
        # the dv view of the selected set (the signal's dollar-volume tiebreak); _bar_metrics
        # = the full survivor metric map kept for the diff-ladder (no phase reads it).
        self._ranked_today: list[str] = []
        self._trailing_dv: dict[str, float] = {}
        self._bar_metrics: dict[str, tuple[float, float]] = {}

        # SCALING FIX (incremental-DV): the MAINTAINED rolling 20-day DV per coarse name.
        # _dv_windows[ticker] = DvWindow(deque(maxlen=ADV_WINDOW), last_seen). Pushed ONCE per
        # day from the coarse feed's single-day DV (NO history() fan-out). _dv_day_index is a
        # monotonic per-selection-day counter driving the stale-eviction (absent >= ADV_WINDOW
        # days). The window FILLS DURING WARMUP (coarse callback runs each warmup day), so it is
        # full by the time live trading starts — no startup history() seed.
        self._dv_windows: dict[str, DvWindow] = {}
        self._dv_day_index: int = -1

        # LIVE once-daily SELECTION GATE (#238 / Y): add_universe runs coarse_selection each
        # day (maintain rolling-DV + prefilter + apply_floors + rank_and_cap → subscribe ONLY
        # the ranked qualifying set). NO stored file, NO ObjectStore artifact, NO
        # fp-verify-on-file, NO history() fan-out — computed from QC's coarse feed, local+cloud.
        self.add_universe(self._coarse_selection)

        # #313: schedule the DAILY DECISION as an AFTER-CLOSE event — the proper #270 trigger,
        # decoupled from on_data bar-presence (the #275b SPY-bar proxy was broken both ways:
        # over-fire 390/day patched by #311 → under-fire 1/window revealed by the 276b-0 smoke,
        # because once SPY is intraday-subscribed its on_data slice is the 5-min bar). Fires once
        # per trading day after SPY's close → on_data carries ONLY the intraday execution clock now.
        self.schedule.on(
            self.date_rules.every_day(self.spy.symbol),
            self.time_rules.after_market_close(self.spy.symbol, self.AFTER_CLOSE_MIN),
            self._on_after_close_decision,
        )
        self._schedule_armed = True  # #313 watchdog engages only in a real armed run (not selection-harness unit tests)

        # #321: realistic IBKR cost+slippage — IB brokerage model + a security initializer that
        # installs InteractiveBrokersFeeModel + ConstantSlippageModel on every equity (universe,
        # intraday, SPY); indices (VIX) skipped. Single code path, no `if cloud` branch (charter).
        wire_cost_models(self, slippage_percent=self.SLIPPAGE_PERCENT)

        self.engine = StrategyEngine(config=self.STRATEGY_CONFIG, qc=self)

        # Pin provenance on startup (substrate fingerprint + config-hash + commit live in
        # dist/_metadata.py, logged by the engine's STRATEGY_INIT).
        self.log(
            f"LEAN_ENTRY_INIT|live_coarse_selectiongate|prefilter_dv={self.PREFILTER_DV}|"
            f"min_price={self.MIN_PRICE}|min_avg_dv={self.MIN_AVG_DOLLAR_VOLUME}|"
            f"coarse_max={self.COARSE_MAX}|adv_window={self.ADV_WINDOW}|"
            f"start={self.START_DATE}|end={self.END_DATE} "
            f"(prefilter -> floors -> rank+cap at selection; subscribe only qualifying)"
        )

    def _load_optional_george_context(self) -> None:
        if self.SECURITY_PROFILE_SOURCE:
            try:
                maps = load_security_profile_maps(self.SECURITY_PROFILE_SOURCE)
            except Exception as exc:
                self.log(
                    f"GEORGE_PROFILE_LOAD|source={self.SECURITY_PROFILE_SOURCE}|"
                    f"loaded=0|error={type(exc).__name__}:{exc}"
                )
            else:
                self._security_profiles = maps["security_profiles"]
                self._industry_by_ticker = maps["industry_by_ticker"]
                self._sector_by_ticker = maps["sector_by_ticker"]
                self._proxy_by_ticker = maps["proxy_by_ticker"]
                self.log(
                    f"GEORGE_PROFILE_LOAD|source={self.SECURITY_PROFILE_SOURCE}|"
                    f"loaded={len(self._security_profiles)}|error="
                )

        if self.GEORGE_ATTENTION_SOURCE:
            try:
                maps = load_george_attention_maps(self.GEORGE_ATTENTION_SOURCE)
            except Exception as exc:
                self.log(
                    f"GEORGE_ATTENTION_LOAD|source={self.GEORGE_ATTENTION_SOURCE}|"
                    f"loaded=0|error={type(exc).__name__}:{exc}"
                )
            else:
                self._george_attention_ticker = maps["ticker_attention"]
                self._george_attention_industry = maps["industry_attention"]
                self._george_source_role_counts = maps["source_role_counts"]
                self.log(
                    f"GEORGE_ATTENTION_LOAD|source={self.GEORGE_ATTENTION_SOURCE}|"
                    f"ticker={len(self._george_attention_ticker)}|"
                    f"industry={len(self._george_attention_industry)}|error="
                )

    def _coarse_selection(self, coarse: Any) -> Any:
        """Once-daily LIVE SELECTION GATE (#238 / Y, Falk): coarse feed → MAINTAIN rolling DV →
        build metrics → FLOORS → RANK+CAP. The floors live HERE (Falk's Y: "filter selects
        tickers, passes them to Ichimoku") — they bound SUBSCRIPTION, so only qualifying names
        get tracked + Ichimoku'd (no 2x indicator load). NO redundant per-bar filter phase.

        SCALING FIX (incremental-DV): the trailing DV is MAINTAINED as a rolling 20-day window
        per coarse name (qc._dv_windows), pushed once per day from the coarse feed's single-day
        DV — NO per-day history() fan-out (that was ~20x slower on cloud). The window fills
        DURING WARMUP (this callback runs each warmup day too), so with WARMUP_DAYS ≥ ADV_WINDOW
        it is full before live trading — no startup history() seed. NO history() anywhere here.

        One code path both sides (local simulates cloud). Steps:
          1. coarse_to_dollar_volume(coarse) / coarse_to_close(coarse) → today's single-day DV +
             RAW close per ticker (the coarse row's `.dollar_volume` / `.price`).
          2. update_dv_windows(qc._dv_windows, coarse_dv) → push today's DV into each rolling
             window (drop-oldest at ADV_WINDOW), evict long-absent names. PREFILTER (≥
             PREFILTER_DV, a loose perf-bound) restricts WHICH names build a (close, trailing)
             metric — trailing = rolling_dv_mean(window), close = the coarse RAW price.
          3. apply_floors (close >= MIN_PRICE AND trailing_dv >= MIN_AVG_DOLLAR_VOLUME) → the
             SELECTION GATE; then rank_and_cap (DV-desc, ticker-asc tiebreak, cap COARSE_MAX).
          4. store qc._ranked_today (the floored+ranked+capped selection; the universe phase
             exposes it) + qc._trailing_dv (dv view of the selected set; signal tiebreak) +
             qc._bar_metrics (full survivor map; diff-ladder only). SUBSCRIBE ONLY the ranked
             qualifying set; log the active-set hash (selection rung); return the Symbols.
        QC subscribes the returned Symbols (on_securities_changed owns qc._active); names
        without substrate data drop naturally (the ∩-substrate residual)."""
        date_str = self.time.strftime("%Y-%m-%d")
        coarse_dv = coarse_to_dollar_volume(coarse)
        coarse_close = coarse_to_close(coarse)

        # FAIL-LOUD GUARD (#261-5): missing-coarse-on-a-known-trading-day. QC drives
        # CoarseFundamentalUniverseSelection off its OWN NYSE trading calendar — the callback fires
        # once per real session and is NOT invoked on a market holiday (no session → no callback),
        # regardless of which files happen to sit on disk. That calendar is the actual guarantee.
        # (Belt-and-suspenders only: the local conform's clean_orphan_files is MEANT to purge stale
        # non-session files, but the tree currently still carries ~14 US-holiday orphans — header-
        # only or foreign-exchange tickers; SPY has no bars on those days so QC's calendar excludes
        # them anyway. Do NOT rely on the purge having run; rely on QC's calendar.) Real FY2025
        # session feeds carry >10k rows each. Therefore reaching this callback with an EMPTY feed
        # means "QC fired on a real trading day but the coarse data is missing" = a DATA GAP that
        # would otherwise read as a silent empty/holiday feed (the #173 mirage). Empty == ALWAYS
        # broken here → RAISE with the day, never silently select [].
        # (Reconciled with #263's correct-0 contract: there is NO legitimate empty-feed case —
        # QC does not fire the callback on a non-trading day — so the prior "empty = correct-0"
        # pin is FLIPPED to assert this raise; see tests/data/test_active_set_nonempty.py.)
        n_in = len(coarse_dv)
        if n_in == 0:
            raise DegradedDataError(
                f"empty coarse feed on a trading day: date={date_str} (QC fired the coarse "
                f"selection callback — a real session — but 0 names arrived). A missing/empty "
                f"feed on a known trading day is a DATA GAP that must fail loud, never read as a "
                f"silent holiday/empty universe (the #173 empty-warmup mirage) (#261-5)"
            )

        # MAINTAIN the rolling 20-day DV from today's coarse feed (NO history()). Monotonic
        # day-index drives stale-eviction (a name absent >= ADV_WINDOW days is dropped).
        self._dv_day_index += 1
        update_dv_windows(
            self._dv_windows, coarse_dv, day_index=self._dv_day_index, maxlen=self.ADV_WINDOW,
        )

        # Build (close, trailing_dv) for the PREFILTER survivors (loose perf-bound) from the
        # MAINTAINED windows + the coarse RAW close. trailing_dv = rolling mean of the window.
        bar_metrics: dict[str, tuple[float, float]] = {}
        for ticker, sdv in coarse_dv.items():
            if sdv < self.PREFILTER_DV:
                continue
            window = self._dv_windows[ticker].dv  # just pushed above
            close = coarse_close.get(ticker)
            if close is None:
                continue
            bar_metrics[ticker] = (close, rolling_dv_mean(window))

        # FLOORS AT THE SELECTION GATE (Y): only qualifying names get subscribed + tracked.
        eligible = apply_floors(
            bar_metrics, min_price=self.MIN_PRICE,
            min_avg_dollar_volume=self.MIN_AVG_DOLLAR_VOLUME,
        )
        dv_by_ticker = {t: bar_metrics[t][1] for t in eligible}
        ranked = rank_and_cap(eligible, dv_by_ticker, coarse_max=self.COARSE_MAX)

        # FAIL-LOUD GUARD (#261-6): broken-0. A POPULATED coarse feed (>= BROKEN_ZERO_MIN_FEED
        # names — a real session delivers thousands) that COLLAPSES to a ZERO ranked selection is
        # DEGRADED data, not a legitimate holiday: e.g. the DV column corrupted to tiny values so
        # every name falls below the prefilter/floor, or the price column zeroed. This is exactly
        # the −0.616 mirage (a full feed in, an empty universe out, nothing crashing). The (n_in,
        # ranked) pair distinguishes it from correct-0: correct-0 (n_in == 0) already raised
        # above; here n_in is substantial yet 0 selected → RAISE with the input count so the
        # degradation is diagnosable. A SPARSE feed (n_in < the threshold) collapsing to zero is
        # too thin to call "broken" — benign correct-0, no raise. On healthy real data this never
        # fires (FY2025 sessions select hundreds).
        if not ranked and n_in >= self.BROKEN_ZERO_MIN_FEED:
            raise DegradedDataError(
                f"broken-0 selection on a populated coarse feed: date={date_str} "
                f"names_in={n_in} eligible={len(eligible)} ranked=0 — a full feed collapsed to "
                f"an EMPTY universe (degraded data: DV/price column corrupted, every name below "
                f"the floor?). A non-empty feed yielding zero selection must fail loud, never a "
                f"silent empty universe (the −0.616 empty-universe mirage) (#261-6)"
            )

        watchlist = getattr(self, "_george_watchlist", {})
        carry, carry_rejected = select_watchlist_carry(
            watchlist if isinstance(watchlist, dict) else {},
            bar_metrics,
            ranked,
            max_names=self.WATCHLIST_CARRY_MAX,
            min_price=self.WATCHLIST_CARRY_MIN_PRICE,
            min_avg_dollar_volume=self.WATCHLIST_CARRY_MIN_AVG_DOLLAR_VOLUME,
        )
        normal_ranked = list(ranked)
        if carry:
            ranked = normal_ranked + [c.ticker for c in carry]

        self._watchlist_carry_today = {
            c.ticker: {
                "score": c.score,
                "age_days": c.age_days,
                "price": c.price,
                "trailing_dv": c.trailing_dv,
                "reason": c.reason,
            }
            for c in carry
        }
        self._watchlist_carry_rejected = carry_rejected
        self._selection_sources = {t: "ranked" for t in normal_ranked}
        self._selection_sources.update({c.ticker: "watchlist_carry" for c in carry})
        for c in carry:
            self.log(
                f"WATCHLIST_CARRY|{date_str}|{c.ticker}|reason={c.reason}|price={c.price}|"
                f"trailing_dv={c.trailing_dv}|score={c.score}"
            )

        # Store the selected+ranked+capped set + the dv view (signal tiebreak) + the full
        # survivor map (diff-ladder only; no phase reads _bar_metrics under Y).
        self._ranked_today = ranked
        self._trailing_dv = {t: bar_metrics[t][1] for t in ranked if t in bar_metrics}
        self._bar_metrics = bar_metrics

        # Subscribe ONLY the ranked qualifying set (the whole point of Y — no 2x load).
        count, h = active_set_hash(ranked)
        self.log(f"ACTIVE_SET|{date_str}|count={count}|hash={h}")
        # #313 WATCHDOG: this coarse callback is the reliable per-trading-day tick. Post-warmup,
        # count the trading day and assert the scheduled daily DECISION is keeping pace — if the
        # after-close event has silently stopped firing, decisions lag and this CRASHES (never dark).
        if getattr(self, "_schedule_armed", False) and not getattr(self, "is_warming_up", False):
            self._sched_trading_days = getattr(self, "_sched_trading_days", 0) + 1
            self._assert_schedule_health()
        # #275b-fix (LAG): the intraday-subscription sync is NOT done here. add_universe returns
        # the ranked symbols, but qc._active only updates in on_securities_changed which QC fires
        # AFTER this callback returns — so reconciling here would resolve candidates against the
        # PREVIOUS day's _active (a 1-day lag → a FRESH candidate's 5-min feed engages T+2, missing
        # its T+1 execution window). Instead the sync runs in on_data's daily-clock path (where
        # _active is current); we stash today's ranked set for it to consume.
        self._ranked_today = ranked  # (already set above; explicit for the on_data sync consumer)
        return [Symbol.create(t.upper(), SecurityType.EQUITY, Market.USA) for t in ranked]

    def on_securities_changed(self, changes: Any) -> None:
        """Register indicators for newly-subscribed symbols, dispose on removal — EXACT
        legacy carve. Owns qc._active (the truly-subscribed set the phases intersect against)."""
        for s in changes.added_securities:
            sym = s.symbol
            self._active.add(sym)
            if sym not in self._indicators:
                self._register_indicators(sym)
        for s in changes.removed_securities:
            sym = s.symbol
            self._active.discard(sym)
            if sym in self._indicators:
                self.subscription_manager.remove_consolidator(
                    sym, self._indicators[sym]["consolidator"]
                )
                # #253: dispose the daily consolidator too (added alongside the weekly one).
                self.subscription_manager.remove_consolidator(
                    sym, self._indicators[sym]["daily_consolidator"]
                )
                del self._indicators[sym]

    def _register_indicators(self, sym: Any) -> None:
        """Build the per-symbol indicators into the qc._indicators[sym] contract (INDICATOR_KEYS).
        Daily ichimoku 9/26/26/52/26/26 + sma200 (QC native), weekly ichimoku fed by a MANUAL
        TradeBarConsolidator (Calendar.WEEKLY) — the proven QC-cloud resample-timeout fix
        (8048c29). EXACT legacy carve."""
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        # #213f maintained indicators so the SIGNAL reads O(1)/candidate (no per-bar history).
        # ADX(9) → condition 7 (adx>=20, +DI>-DI). adx_window holds recent ADX values so
        # adx_rising = window[0] > window[3] (now vs 3 bars back, == legacy adx[-1]>adx[-4]).
        # ROC(13) → parabolic block (13-day run). [QC-API: adx.updated signature + roc
        # convention integration-verified on the LEAN run — flagged, not unit-testable here.]
        adx = self.adx(sym, 9)
        adx_window = RollingWindow[float](5)
        adx.updated += lambda _s, _pt: adx_window.add(adx.current.value)
        roc13 = self.roc(sym, 13)
        # #253 entry_selection (BctEntryConfirm §4 Gate 2) — ADDITIVE maintained indicators the
        # SIGNAL/exit phases never read (champion-asis parity intact). MACD(12/26/9) for C3, a
        # 20-day VOLUME SMA for C4, a 2-deep MACD-histogram window for the C3 turning direction,
        # and the daily-fed T-Bounce tracker for the C2 degrade state. All auto-warm during
        # warmup like the rest of the suite (O(1)/candidate, no per-bar history in the phase).
        macd = self.macd(sym, 12, 26, 9, MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        macd_hist_window = RollingWindow[float](2)
        macd.updated += lambda _s, _pt: macd_hist_window.add(macd.histogram.current.value)
        vol_sma20 = self.sma(sym, 20, Resolution.DAILY, Field.VOLUME)
        tbounce = TBounceTracker()
        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)
        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_: Any, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        # Daily consolidator feeds the T-Bounce tracker the completed daily bar + the live daily
        # Tenkan (the C2 sessions-below-Tenkan + gap-up degrade state). Separate from the weekly
        # consolidator; disposed alongside it on unsubscribe.
        daily_consolidator = TradeBarConsolidator(timedelta(days=1))

        def _on_daily(_: Any, bar: TradeBar) -> None:
            t = d_ichi.tenkan.current.value if d_ichi.is_ready else 0.0
            # Feed the FULL daily OHLC bar (HQ #253-P1: C2 reads the daily LOW + candle body/wick).
            tbounce.update(
                float(bar.open), float(bar.high), float(bar.low), float(bar.close), float(t)
            )

        daily_consolidator.data_consolidated += _on_daily
        self.subscription_manager.add_consolidator(sym, daily_consolidator)

        # With the derived warmup (WARMUP_DAYS, 560d -> ~78 weekly bars) the consolidator
        # receives enough weekly bars automatically; only seed manually outside warmup (a name
        # added mid-run after warmup) — avoid N× history() calls at init.
        #
        # #259 (the amplifier fix): a name that enters the universe AFTER warmup ends (the
        # dynamic mid-FY entrant) gets FRESHLY-registered daily indicators that would otherwise
        # accumulate LIVE from scratch — d_ichi/sma200/adx/roc need ~52/200/~30/13 daily bars
        # to become is_ready, so score_symbol_native returns None for ~9-10 months and the name
        # never qualifies (the #173 "wakes up in October" tell). DURING warmup QC auto-warms
        # the subscribed indicators (PART A ensures names ARE subscribed in warmup), so the seed
        # is ONLY for the post-warmup entrant — exactly mirroring the weekly-seed guard. Seed the
        # WEEKLY ichimoku AND the full DAILY suite from history so the name can qualify the day
        # it is first subscribed. NO if-cloud branch — single code path, RAW (history default
        # follows universe_settings.data_normalization_mode = RAW set in initialize()).
        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)
            self._seed_daily(
                sym, d_ichi, sma200, adx, adx_window, roc13, macd, vol_sma20, tbounce
            )

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "adx": adx,
            "adx_window": adx_window,
            "roc13": roc13,
            "consolidator": consolidator,
            # #253 entry_selection additions (additive — see INDICATOR_KEYS note).
            "macd": macd,
            "macd_hist_window": macd_hist_window,
            "vol_sma20": vol_sma20,
            "tbounce": tbounce,
            "daily_consolidator": daily_consolidator,
        }
        assert set(self._indicators[sym]) == set(INDICATOR_KEYS)  # contract guard

    # ------------------------------------------------------------------------------------
    # #275b — INTRADAY (5-min) subscription lifecycle (Option C: subscribe MINUTE, our Massive
    # is natively 5-min, consume directly, NO consolidator). The daily clock decides WHO gets an
    # intraday feed for T+1 (candidate∩CAP + holdings); these manage subscribe/seed/teardown.
    # ------------------------------------------------------------------------------------
    def _subscribe_intraday(self, sym: Any) -> None:
        """Add a 5-min ("minute") subscription + the intraday indicator suite for `sym`, seeding
        it so it is WARM before its first intraday score (#275b). Idempotent — a no-op if already
        subscribed. Periods are in 5-MIN-BAR units (INTRADAY_TENKAN(9) = 45 min)."""
        if sym in self._intraday:
            return
        # RAW minute subscription (delivers our 5-min Massive bars stored as minute-res zips).
        eq = self.add_equity(sym.value, Resolution.MINUTE)
        eq.set_data_normalization_mode(DataNormalizationMode.RAW)
        # The GH#25 intraday-confirm inputs (#276 reads these): an intraday Tenkan (midpoint of the
        # last INTRADAY_TENKAN 5-min highs/lows) + a 5-min volume SMA. Maintained from the 5-min
        # bars in on_data — NO consolidator (the data IS 5-min). We hold the rolling windows.
        intraday_tenkan = IchimokuKinkoHyo(
            self.INTRADAY_TENKAN, 26, 26, 52, 26, 26
        )  # only .tenkan is read by #276; full Ichimoku keeps the API uniform
        vol_window = RollingWindow[float](self.INTRADAY_VOL_WINDOW)
        self._intraday[sym] = {
            "intraday_tenkan": intraday_tenkan,
            "vol_window": vol_window,
            "last_close": None,
            "last_bar": None,
        }
        self._intraday_active.add(sym)
        # SEED-ON-SUBSCRIBE (avoid a cold-DegradedDataError on the first 5-min bar). Post-warmup
        # entrants need warming from history; during warmup the subscription auto-warms via QC.
        if not self.is_warming_up:
            self._seed_intraday(sym, intraday_tenkan, vol_window)
        self.log(f"INTRADAY_SUBSCRIBE|{sym.value}|n_active={len(self._intraday_active)}")

    def _seed_intraday(self, sym: Any, intraday_tenkan: Any, vol_window: Any) -> None:
        """Warm the intraday indicators from 5-min ("minute") history so a post-warmup entrant is
        ready before its first intraday score (#275b — the anti-cold-mirage seed, mirrors
        _seed_daily). Forward-only: history rows dated >= today are dropped (the #213f/#259 guard).
        Enough bars to warm the longest intraday pole (the Ichimoku 78-bar pole)."""
        # ~78 5-min bars/day; pull enough days to clear the 78-bar Ichimoku pole + a buffer.
        # #318: TYPED HISTORY — iterate NATIVE TradeBar objects (native Decimal fields, no manual
        # construction). Kills the cloud-interop class at this site (no ctor, no float→Decimal).
        today = self.time.date()
        for bar in self.history[TradeBar](sym, 8 * 78, Resolution.MINUTE):
            # forward-only: never seed a bar whose data is from today/future (look-ahead,
            # #275b/#268). end_time = when the bar's data became available (the safe reference).
            if bar.end_time.date() >= today:
                continue
            intraday_tenkan.update(bar)
            vol_window.add(float(bar.volume))

    def _unsubscribe_intraday(self, sym: Any) -> None:
        """Tear down `sym`'s 5-min subscription + intraday indicators on rotation out of the
        candidate set (#275b — THE LEAK AVOIDANCE: RemoveSecurity does NOT auto-dispose user
        indicators, confirmed in the LEAN source, so we explicitly drop our state + remove the
        subscription). Idempotent. NEVER remove a held name (don't drop a position's data feed)."""
        if sym not in self._intraday:
            return
        if self.portfolio[sym].invested:
            return  # keep the feed while invested — exits run on the intraday clock
        del self._intraday[sym]
        self._intraday_active.discard(sym)
        self.remove_security(sym)  # drop the 5-min subscription (no consolidator to remove — Option C)
        self.log(f"INTRADAY_UNSUBSCRIBE|{sym.value}|n_active={len(self._intraday_active)}")

    def _sync_intraday_subscriptions(self, candidates: list[str]) -> None:
        """Reconcile the intraday subscription set to (today's candidates ∩ CAP) + current
        holdings (#275b). Called once-daily after the selection produces the candidate list — the
        daily clock deciding WHO gets a 5-min feed for T+1. Subscribes new, tears down dropped
        (non-held). CAP is explicit + logged — never the whole universe (#213e OOM scar)."""
        # CASE: ranked `candidates` are lowercase (coarse value lowered); QC Symbol.value is
        # uppercase. Match case-INSENSITIVELY to the canonical _active symbol — the same fix the
        # universe phase (dv_rank_cap) uses. (Without this the lookup always missed → 0 intraday
        # subscriptions despite INTRADAY_CAP logging — the #275b bug GATE-0 caught.)
        active_by_key = {canonical_symbol_key(s): s for s in self._active}  # #276b-1 FIX3 canonical key
        # the capped candidate slice that gets an intraday feed (scan-breadth cap, not a position cap)
        capped = candidates[: self.INTRADAY_SUBSCRIBE_CAP]
        if len(candidates) > self.INTRADAY_SUBSCRIBE_CAP:
            self.log(
                f"INTRADAY_CAP|candidates={len(candidates)}|capped_to={self.INTRADAY_SUBSCRIBE_CAP}"
            )
        want: set[Any] = set()
        for tk in capped:
            sym = active_by_key.get(canonical_symbol_key(tk))
            if sym is not None:
                want.add(sym)
        # held names ALWAYS keep their feed (exits fire on the intraday clock)
        for sym in list(self._intraday_active):
            if self.portfolio[sym].invested:
                want.add(sym)
        # subscribe the new, tear down the dropped (non-held handled inside _unsubscribe_intraday)
        for sym in want - self._intraday_active:
            self._subscribe_intraday(sym)
        for sym in self._intraday_active - want:
            self._unsubscribe_intraday(sym)

    def _seed_weekly(self, sym: Any, w_ichi: Any, w_close: Any) -> None:
        """Seed the weekly ichimoku + close window from history using the MANUAL weekly
        aggregation (runtime.indicators.weekly_aggregate) — NOT df.resample (the cloud-timeout
        fix). Feeds each aggregated weekly bar to w_ichi/w_close in chronological order."""
        hist = self.history(sym, self.WARMUP_DAYS, Resolution.DAILY)
        if hist is None or hist.empty:
            return
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        for wb in weekly_aggregate(hist):
            # TIMESTAMP the seed bar at the week-START MONDAY to MATCH QC Calendar.Weekly
            # (confirmed via QC docs: Calendar.Weekly = start of week = previous Monday). The
            # live consolidator emits Monday-timed weekly bars; seeding at Friday made
            # seed-Friday > a later live-Monday → IchimokuKinkoHyo is forward-only → "forward
            # only indicator" rejection (#213f issue 2). Monday-seed → live-Monday = monotonic.
            # OHLC unaffected: equities have no weekend bars, so W-FRI grouping and Monday-start
            # bucket the identical Mon-Fri days — only the bar.time LABEL changes.
            monday = wb["friday"] - timedelta(days=4)
            bar = _make_trade_bar(
                monday, sym, wb["open"], wb["high"], wb["low"], wb["close"],
                wb["volume"], timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(wb["close"]))

    def _continuous_weekly_scalars(self, sym: Any) -> dict[str, Any] | None:
        """#336/#338 — the candidate's 15-scalar dict with a CONTINUOUS weekly. Daily/ADX/ROC come
        from the live (warm) maintained indicators (gate daily legs); the WEEKLY comes from
        _weekly_scalars_for (#358 cache-or-replay: the precomputed table when loaded+fingerprint-
        matched, else re-derived live from CONTINUOUS history — byte-identical either way). as-of
        (data <=T, no look-ahead). Returns None if the live indicators / weekly aren't ready
        (candidate skipped — mirrors score_symbol_native returning None)."""
        ind = self._indicators.get(sym)
        if ind is None:
            return None
        d_ichi = ind["d_ichi"]; sma200 = ind["sma200"]; adx = ind["adx"]
        adx_window = ind["adx_window"]; roc13 = ind["roc13"]
        if not (d_ichi.is_ready and sma200.is_ready and adx.is_ready and roc13.is_ready):
            return None
        if adx_window.count < 4:
            return None
        wk = self._weekly_scalars_for(sym, self.time.date())  # #358 cache-or-replay (fail-closed)
        if wk is None:
            return None  # weekly not ready (mirrors the live readiness gate)
        d_price = float(self.securities[sym].price)
        if d_price <= 0:
            return None
        return {
            "d_price": d_price,
            "d_tenkan": d_ichi.tenkan.current.value,
            "d_cloud_top": max(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value),
            "ma200": sma200.current.value,
            **wk,  # the 6 weekly scalars — cached or re-derived, byte-identical
            "adx_now": adx.current.value,
            "plus_di": adx.positive_directional_index.current.value,
            "minus_di": adx.negative_directional_index.current.value,
            "adx_3back": adx_window[3],
            "roc13": roc13.current.value,
        }

    def _log_cache_engagement(self) -> None:
        """#358 engagement signal (the assert-engaged): log per-symbol cache hits/misses at end-of-run
        when the cache was ARMED. A speedup with zero hits = a silent fail-closed → this log proves the
        cache actually SERVED lookups. Keyed on _weekly_cache_fp (armed), NOT a stale attr."""
        if getattr(self, "_weekly_cache_fp", None):
            self.log(f"#358 weekly-cache ENGAGED: hits={self._weekly_cache_hits} misses={self._weekly_cache_misses}")

    def _weekly_scalars_for(self, sym: Any, asof_date: Any) -> dict[str, float] | None:
        """The 6 weekly Ichimoku scalars for (sym, asof_date). #358: from the precomputed local cache
        (fail-closed fingerprint match, flag-ON) if present, else RE-DERIVED live from history(560d)
        — the canonical #336 path. None if the weekly isn't ready (mirrors the live gate). A cache HIT
        is byte-identical to the re-derive (same WeeklyIchimokuAsOf, same daily data, same as-of date)
        → trade-neutral. A MISS (all cloud, fingerprint-mismatch, not-ready dates) falls through to the
        live re-derive → no divergence (single canonical path; the cache is only an accelerator)."""
        fp = self._weekly_cache_fp
        key = sym.value
        is_sparse = self._symbol_sparse.get(key)  # None = unclassified; else the memoized bool

        # DENSE fast-path (classified-dense + armed): cache lookup = the SPEEDUP, no history load.
        if fp and is_sparse is False:
            wk = self._weekly_cache_get(fp, key, asof_date)
            if wk is not None:
                return wk  # dense HIT — byte-identical to the re-derive
            # dense MISS → fall through to re-derive (+ throw on a real gap)

        # RE-DERIVE / CLASSIFY: first-touch (classify sparsity), sparse (always), dense-miss, or unarmed.
        rd = self._weekly_from_history(sym, asof_date)  # ONE history(560) load → all the signals
        if rd is None:
            return None  # empty history
        ready, scalars, traded_on_asof, this_sparse = rd
        if is_sparse is None:  # FIRST TOUCH: memoize sparsity, then (if dense) re-check the cache so the
            self._symbol_sparse[key] = this_sparse  # throw fires only on a genuine dense miss, not on a
            is_sparse = this_sparse                  # coverable first query we hadn't yet looked up.
            # #370 KNOWN NARROW LIMITATION (HQ-flagged, deferred to the #376 follow-up): sparsity is
            # classified once, AS-OF first touch. A symbol DENSE at first-touch that DEVELOPS internal
            # gaps LATER (dense→sparse, a name losing liquidity) stays memoized dense → keeps hitting the
            # cache → a post-gap date could serve a sparse-zip cache value ≠ the ff-dense runtime value.
            # NARROW (dense-then-sparse is rare; sparse-then-dense + dense-then-delisted are handled), and
            # the byte-identical-vs-full-warmup + cloud-parity gate backstops the validated windows. The
            # as-of-advancing re-classification (option (a)) is the full close — deferred, NOT silent.
            if fp and not is_sparse:
                wk = self._weekly_cache_get(fp, key, asof_date)
                if wk is not None:
                    return wk

        from runtime.warmup_weekly_cache import WeeklyCacheGapError, weekly_miss_action
        action = weekly_miss_action(
            rederive_ready=bool(ready), armed=bool(fp),
            warmup_days=self.WARMUP_DAYS, weekly_floor=self.WEEKLY_FLOOR_DAYS,
            traded_on_asof=bool(traded_on_asof), is_sparse=bool(is_sparse),
        )
        if action == "skip":
            return None  # uncomputable (pre-78wk-from-listing / fully post-delisting) — legit
        if action == "throw":
            raise WeeklyCacheGapError(
                f"#368 weekly-cache GAP: {getattr(sym, 'value', sym)} @ {asof_date} is a DENSE name "
                f"computable (>=78wk) + traded on asof but MISSED the cache at trimmed warmup "
                f"(WARMUP_DAYS={self.WARMUP_DAYS}<{self.WEEKLY_FLOOR_DAYS}) — a real build gap. Rebuild "
                f"the weekly-cache to cover this (symbol,date); never ship a silent-divergence."
            )
        return scalars  # 'value' — canonical re-derive (== full-warmup), or sparse-always-re-derive

    def _weekly_cache_get(self, fp: str, key: str, asof_date: Any) -> dict[str, float] | None:
        """Per-symbol lazy cache lookup (memoized fetch-once). Returns the cached 6-scalar dict for
        asof_date, or None on miss. Increments hits/misses. Only the DENSE path calls this — sparse
        symbols bypass the cache entirely (#370 (2')-(i): their raw-zip cache can't match ff-dense)."""
        if key not in self._weekly_loaded:
            from runtime.warmup_weekly_cache import load_weekly_cache_for_symbol
            self._weekly_loaded[key] = load_weekly_cache_for_symbol(
                getattr(self, "object_store", None), fp, key)
        sym_rows = self._weekly_loaded[key]
        if sym_rows is not None:
            wk = sym_rows.get(asof_date)
            if wk is not None:
                self._weekly_cache_hits += 1
                return wk
        self._weekly_cache_misses += 1
        return None

    def _weekly_from_history(self, sym: Any, asof_date: Any) -> "tuple[bool, dict[str, float] | None, bool, bool] | None":
        """#358/#370 — re-derive the weekly from history(max(WARMUP_DAYS, WEEKLY_FLOOR_DAYS)) as-of
        asof_date — the canonical #336 path, IDENTICAL to the untrimmed full-warmup path (same
        WeeklyIchimokuAsOf port, same self.history data) → byte-identical to a (dense) cache hit.
        Returns (ready, scalars|None, traded_on_asof, is_sparse) or None on empty history.

        is_sparse = any vol==0 bar WITHIN [first vol>0 .. last vol>0] — an INTERNAL gap in the runtime's
        OWN ff-dense history (LEAN fill-forwards untraded days as vol==0) = a sparse-trading name. Its
        raw-zip-built cache can't match the ff-dense weekly (different aggregation → different readiness
        AND values) → routed around the cache (always re-derived). Classified from the runtime's own
        view → self-consistent, NO build-runtime agreement surface (the (2')-(i) safety).
        traded_on_asof = (last bar == asof AND vol>0) — a REAL bar (not a fill-forward vol==0 synthetic)."""
        from runtime.lean_indicators import WeeklyIchimokuAsOf  # lazy — flag-ON path only (#336/#338)
        rederive_days = max(self.WARMUP_DAYS, self.WEEKLY_FLOOR_DAYS)
        hist = self.history(sym, rederive_days, Resolution.DAILY)
        if hist is None or hist.empty:
            return None
        if isinstance(hist.index, pd.MultiIndex):
            hist = hist.droplevel(0)
        hist.columns = [c.lower() for c in hist.columns]
        w = WeeklyIchimokuAsOf()
        last_bar_date = None
        last_bar_volume = 0.0
        vols: list[float] = []
        for ts, row in hist.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            v = float(row["volume"])
            w.update(d, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]))
            last_bar_date = d
            last_bar_volume = v
            vols.append(v)
        reals = [i for i, v in enumerate(vols) if v > 0.0]
        is_sparse = bool(len(reals) >= 2 and any(vols[j] == 0.0 for j in range(reals[0], reals[-1] + 1)))
        asof_d = asof_date.date() if hasattr(asof_date, "date") else asof_date
        traded_on_asof = last_bar_date == asof_d and last_bar_volume > 0.0
        scalars = None
        if w.is_ready:
            scalars = {
                "w_tenkan": w.tenkan, "w_kijun": w.kijun,
                "w_senkou_a": w.senkou_a, "w_senkou_b": w.senkou_b,
                "w_close_0": w.w_close(0), "w_close_26": w.w_close(26),
            }
        return bool(w.is_ready), scalars, bool(traded_on_asof), is_sparse

    def _seed_daily(
        self,
        sym: Any,
        d_ichi: Any,
        sma200: Any,
        adx: Any,
        adx_window: Any,
        roc13: Any,
        macd: Any,
        vol_sma20: Any,
        tbounce: Any,
    ) -> None:
        """History-seed the DAILY indicator suite for a name subscribed AFTER warmup (#259).

        Mirrors _seed_weekly's idiom: pull WARMUP_DAYS of daily bars and replay them in
        chronological order, feeding each indicator the SAME way its live subscription would,
        so the suite is is_ready immediately rather than ~9-10 months later (the empty-warmup
        amplifier, #173).

        Per-indicator feed (matching the live wiring in _register_indicators):
          - d_ichi / adx  : consume the full TradeBar (.update(bar)). adx.updated fires the
            adx_window lambda automatically, so the rolling ADX window fills as a side effect.
          - sma200        : price-series indicator — .update(time, close).
          - roc13         : price-series indicator — .update(time, close).
          - macd          : price-series indicator — .update(time, close). macd.updated fires
            the macd_hist_window lambda automatically.
          - vol_sma20     : VOLUME-field SMA — .update(time, volume).
          - tbounce       : the daily consolidator's _on_daily feeds it OHLC + the live daily
            Tenkan; replay the same (using d_ichi's tenkan once d_ichi.is_ready, else 0.0).

        FORWARD-ONLY GUARD (the daily analogue of _seed_weekly's Monday-seed lesson, #213f):
        IchimokuKinkoHyo + ADX are forward-only — an .update() with a timestamp <= the
        indicator's last sample is REJECTED ("This is a forward only indicator"). On the day a
        name is subscribed, QC has ALREADY fed the live daily bar (timed at the session close,
        e.g. 16:00Z) to the auto-updated d_ichi/adx BEFORE on_securities_changed runs the seed,
        and history() returns that same current day as its LAST row at the intraday data time
        (e.g. 13:00Z) → seeding it would be a backward update (13:00 < 16:00) → rejected + a
        polluted partial bar. FIX: drop any history row dated >= the current algorithm DAY, so
        the seed feeds ONLY strictly-earlier complete bars and the live feed owns today's bar.
        This keeps the seed monotonic with the live stream (same invariant the Monday-seed
        gives the weekly path). Single code path, RAW (history inherits RAW). No cloud branch.
        """
        # #318: TYPED HISTORY — iterate NATIVE TradeBar objects (native Decimal, no manual
        # construction). Kills the cloud-interop class at this site (no ctor, no float→Decimal).
        # Forward-only guard: seed only bars whose data is STRICTLY BEFORE today (the live feed
        # owns today's bar, already fed to the auto-updated d_ichi/adx → seeding it = a backward
        # update + a polluted partial bar). end_time = when the bar's data became available.
        today = self.time.date()
        for bar in self.history[TradeBar](sym, self.WARMUP_DAYS, Resolution.DAILY):
            if bar.end_time.date() >= today:
                continue
            et = bar.end_time
            o, h, lo, c, v = (
                float(bar.open), float(bar.high), float(bar.low), float(bar.close),
                float(bar.volume),
            )
            # Full-bar consumers (adx.updated cascades into adx_window).
            d_ichi.update(bar)
            adx.update(bar)
            # Price-series consumers (macd.updated cascades into macd_hist_window).
            sma200.update(et, c)
            roc13.update(et, c)
            macd.update(et, c)
            # Volume-field consumer.
            vol_sma20.update(et, v)
            # T-Bounce tracker: replay the live _on_daily feed (OHLC + live daily Tenkan).
            tk = d_ichi.tenkan.current.value if d_ichi.is_ready else 0.0
            tbounce.update(o, h, lo, c, float(tk))

    def on_data(self, data: Any) -> None:
        """The INTRADAY execution clock ONLY (#313). on_data feeds the 5-min ("minute") bars to the
        intraday indicators + runs the engine's INTRADAY clock (on_intraday_bar). The DAILY DECISION
        clock NO LONGER runs here — it fires on a scheduled AFTER-CLOSE event
        (`_on_after_close_decision`, wired in initialize). (#274/#275b routed both clocks through
        on_data via SPY-bar-presence; #313 retired that proxy — it was broken both ways: over-fire
        390/day patched by #311 → under-fire 1/window revealed by the 276b-0 smoke.)

        WARMUP GUARD (exact legacy pattern): skip while warming up. Orders can't submit during
        warm-up, and the full pipeline over WARMUP_DAYS × the dynamic universe is wrong+slow. QC
        auto-warms registered indicators during warm-up independently of on_data."""
        if self.is_warming_up:
            return

        # --- intraday (5-min) clock: feed the intraday indicators for any minute bars present ---
        bars = getattr(data, "bars", None)
        fed_intraday = False
        if bars is not None and self._intraday:
            for sym, st in self._intraday.items():
                bar = bars.get(sym) if hasattr(bars, "get") else None
                if bar is None:
                    continue
                # the bar is a COMPLETED 5-min bar (Option C: our data is 5-min; the consolidator
                # is not used → on_data delivers the closed 5-min bar). Look-ahead-safe by
                # construction (LEAN delivers a bar at/after its EndTime; never the forming bar).
                st["intraday_tenkan"].update(bar)
                st["vol_window"].add(float(getattr(bar, "volume", 0.0)))
                st["last_close"] = float(bar.close)
                st["last_bar"] = bar
                fed_intraday = True
            if fed_intraday:
                ictx = PhaseContext(qc=self, time=self.time, data=data)
                ictx.clock = "intraday"
                # #386 2b: the two-clock entry decision. When an `entry_trigger` phase is wired (the
                # relocated intraday entry), it reads qc._armed DIRECTLY per-bar — no snapshot seed.
                # The LEGACY path (entry_selection/gap_vol_confirm) still needs the snapshot stubs
                # seeded into bar_state, so keep the inject ONLY when there is no entry_trigger.
                if not getattr(self.engine, "phases", {}).get("entry_trigger"):
                    self._inject_intraday_candidates(ictx)
                self.engine.on_intraday_bar(ictx)
                # #276b-1 FUNNEL: fold this tick's per-stage survivor sets into the per-DAY sets (set
                # membership = the per-day dedup — a candidate evaluated every tick counts ONCE/day at
                # each stage) and accumulate this tick's fired entries (stage 9). Observe-only.
                self._fold_intraday_funnel(ictx)

        # #313: the DAILY DECISION clock is NO LONGER triggered here. on_data carries ONLY the
        # intraday execution clock (above). The daily decision runs on a scheduled AFTER-CLOSE event
        # (_on_after_close_decision, wired in initialize) — the #275b SPY-bar-presence trigger was
        # broken both ways (over-fire 390/day → #311 → under-fire 1/window, the 276b-0 smoke).

    def _on_after_close_decision(self) -> None:
        """#313 — the DAILY DECISION clock, fired by a SCHEDULED AFTER-CLOSE event (decoupled from
        on_data / bar-presence). At T's close + AFTER_CLOSE_MIN: T's daily data is COMPLETE (no
        T+1 look-ahead), the daily indicators are warm with T's bar, and the universe selection for
        T is current (on_securities_changed has fired). Reconciles the intraday subscription set (so
        T's ranked candidates get their T+1 5-min feed — the #275b-fix LAG intent), then runs the
        daily pipeline ONCE. Fires reliably every trading day regardless of whether SPY is
        intraday-subscribed (kills the bar-presence failure class).

        SG8: this is the DECISION clock — it produces candidates only; it fires ZERO orders (all
        fills happen on the intraday execution clock). Warm-or-fail-loud: cold daily indicators at
        fire time raise DegradedDataError inside the phases (#261), never a silent skip."""
        if self.is_warming_up:
            return  # no decisions during indicator warmup (#213d)
        today = self.time.date()
        if today == getattr(self, "_last_daily_date", None):
            return  # once-per-date idempotency (defense-in-depth — the scheduled event fires once/day anyway)
        self._last_daily_date = today
        self._sched_decisions = getattr(self, "_sched_decisions", 0) + 1  # #313 watchdog: decision fired
        # #276b-1: run the daily pipeline FIRST, then hand the SIGNAL WINNERS (not the pre-signal
        # universe) to the intraday clock. The daily SIGNAL (BctScoreFull score>=7) is the WHO; the
        # intraday clock confirms the WHEN on exactly those names. (#276b-0 originally synced/snap'd
        # qc._ranked_today = the ~hundreds-name ranked UNIVERSE → the intraday feeds were starved by
        # the cap and the signal filter was bypassed → silent 0 orders; fixed here.)
        ctx = PhaseContext(qc=self, time=self.time, data=None)  # scheduled event — no slice; daily phases read maintained indicators
        ctx.clock = "daily"
        # #336/#338 CONTINUOUS_WEEKLY (flag-gated; default OFF = live path byte-untouched). Before the
        # phase chain reads scalars, populate qc._warmup_cache[sym][today] with the continuous-weekly
        # 15-scalar dict (daily/ADX/ROC from the live warm indicators; the WEEKLY re-derived continuous
        # via self.history → bypasses the subscription-gated consolidator, the #336 root). BctScoreFull's
        # cache branch (dec9947) then scores from these. Keyed by symbol.value + today (the decision date).
        if self.CONTINUOUS_WEEKLY:
            for sym in list(self._indicators):
                scalars = self._continuous_weekly_scalars(sym)
                if scalars is not None:
                    self._warmup_cache.setdefault(sym.value, {})[today] = scalars
        self.engine.on_data_with_ctx(ctx)
        # The daily pipeline's surviving intents == the signal winners (entry_selection/timing/sizing
        # are on the INTRADAY clock for the intraday champion, so the daily bar_state ends at signal).
        # #277 REGIME GATE → INTRADAY: if a regime/cash phase BLOCKED the daily bar, capture NO
        # candidates → ZERO intraday entries this session. Without this the daily regime gate was
        # confined to the daily clock; the intraday gap+loud entries ignored it → over-traded the
        # bad regimes (the W1/W2 robustness loss). A blocked regime now gates the intraday champion.
        # #276b-1 FUNNEL stage 1 (signal_winners): the daily SIGNAL output (BctScoreFull score>=7),
        # captured BEFORE the regime gate masks it. The signal phase runs ahead of regime in
        # PHASE_ORDER, so ctx.bar_state.sized_orders holds the raw signal winners regardless of the
        # block. This is the ~40-names/day C1 proved — the funnel's top of stack. Observe-only.
        signal_winner_tickers = [intent.ticker for intent in ctx.bar_state.sized_orders]
        blocked = bool(getattr(ctx.bar_state, "bar_blocked", False))
        self._accumulate_daily_funnel(signal_winner_tickers, blocked)
        if blocked:
            winners: list[str] = []
            log = getattr(self, "log", None)
            if callable(log):
                log(f"REGIME_GATE|{today}|blocked — zero intraday candidates captured (#277)")
        else:
            winners = signal_winner_tickers
        # subscribe ONLY the winners for T+1's 5-min feed (all fit INTRADAY_SUBSCRIBE_CAP) + held
        # names (handled inside _sync) — so every confirmable candidate actually has intraday data.
        self._sync_intraday_subscriptions(winners)
        # capture the WINNERS' theses (signal_price + daily_kijun) for the intraday confirm + floor.
        self._capture_candidate_snapshot(winners)
        # #386 STAGE-1 LIVE PARITY ASSERTION (additive, crash-on-divergence). When an `arm` phase is
        # wired it ran IN-CHAIN (after regime, line 1063) and wrote qc._armed. Prove the modular arm
        # reproduces the legacy daily decision EXACTLY before Stage-2 deletes the snapshot path: same
        # winner set, zone==signal_price, daily_kijun==daily_kijun. Divergence = the modular path does
        # NOT reproduce the legacy decision → CRASH, never run a half-migrated decision blind.
        if getattr(self.engine, "phases", {}).get("arm"):
            self._assert_arm_parity()

    def _assert_arm_parity(self) -> None:
        """#386 Stage-1: qc._armed (modular arm output) must == qc._candidate_snapshot (legacy daily
        handoff) on the winner set + zone/daily_kijun. Crash-on-divergence — the live proof the
        modular daily decision reproduces the legacy one before anything is deleted (Stage 2)."""
        armed = getattr(self, "_armed", {})
        snap = getattr(self, "_candidate_snapshot", {})
        a_keys, s_keys = set(armed), set(snap)
        if a_keys != s_keys:
            only_arm = sorted(str(getattr(k, "value", k)) for k in a_keys - s_keys)
            only_snap = sorted(str(getattr(k, "value", k)) for k in s_keys - a_keys)
            raise DegradedDataError(
                f"#386 ARM-PARITY set divergence ({self.time.date()}): armed∖snapshot={only_arm} "
                f"snapshot∖armed={only_snap} — modular arm does not reproduce the legacy winner set"
            )
        for k in a_keys:
            az, sz = armed[k]["zone"], snap[k]["signal_price"]
            ak, sk = armed[k]["daily_kijun"], snap[k]["daily_kijun"]
            if az != sz or ak != sk:
                raise DegradedDataError(
                    f"#386 ARM-PARITY field divergence ({self.time.date()}|{getattr(k, 'value', k)}): "
                    f"zone={az} vs signal_price={sz}; daily_kijun={ak} vs {sk}"
                )

    def _assert_schedule_health(self) -> None:
        """#313 WATCHDOG — the daily DECISION must keep pace with elapsed trading days. Called from
        the per-trading-day coarse tick (post-warmup). The scheduled after-close decision fires once
        per trading day; at this start-of-day check today's decision is still PENDING, so a
        trading_days − decisions gap of 1 is normal. A gap > 1 means a prior trading day's decision
        was MISSED — the scheduled after-close event has silently stopped firing (a LEAN/QC change or
        a cloud divergence — the 276b-0 under-fire class). The decision clock is dark → CRASH, never
        run blind (the charter anti-mirage mandate)."""
        gap = getattr(self, "_sched_trading_days", 0) - getattr(self, "_sched_decisions", 0)
        if gap > 1:
            raise DegradedScheduleError(
                f"daily-decision UNDER-FIRE (#313 watchdog): {self._sched_trading_days} post-warmup "
                f"trading days but only {self._sched_decisions} daily decisions ran (gap {gap} > 1) — "
                f"the scheduled after-close event is not firing. The daily DECISION clock has gone "
                f"DARK; refusing to run blind."
            )

    def on_end_of_algorithm(self) -> None:
        """#313 watchdog BACKSTOP (Gemini/HQ placement). The per-trading-day _assert_schedule_health
        is the PRIMARY guard (fails fast mid-run — essential for LIVE, where an end-of-run check
        would never fire). This is the end-of-backtest final reconciliation: total daily decisions
        must match elapsed post-warmup trading days within the 1-day pending tolerance, else the
        scheduled trigger under-fired across the run → CRASH (never silently report a dark run)."""
        # #276b-1 FUNNEL: final flush + publish BEFORE the watchdog raise — the collapse-stage
        # diagnostic is MOST valuable when the run ends (incl. a crash). Idempotent: the per-day sets
        # were already flushed + reset by the last on_end_of_day, so this folds at most the final
        # session's residual then re-publishes the cumulative counters. Observe-only.
        self._process_eod_funnel()
        # #358 engagement signal: log cache hits/misses so we KNOW the cache served lookups (a
        # speedup with zero hits = the in-container path silently failed-closed to live re-derivation).
        self._log_cache_engagement()
        if not getattr(self, "_schedule_armed", False):
            return  # scheduler never armed (selection-harness context) — nothing to reconcile
        gap = getattr(self, "_sched_trading_days", 0) - getattr(self, "_sched_decisions", 0)
        if gap > 1:
            raise DegradedScheduleError(
                f"daily-decision UNDER-FIRE at end-of-run (#313 watchdog backstop): "
                f"{self._sched_trading_days} post-warmup trading days vs {self._sched_decisions} "
                f"decisions (gap {gap} > 1) — the scheduled after-close trigger under-fired."
            )

    def _signal_min_score(self) -> int:
        """The configured BCT signal threshold (the score a winner was selected at) — for the
        snapshot drift tripwire. Reads the signal slot's params; default 7 (champion) if it can't
        resolve (never crash the snapshot over the guard's own input)."""
        try:
            slot = self.engine.config.phases.get("signal")
            if isinstance(slot, list):
                slot = slot[0]
            params = getattr(slot, "params", None)  # slot may be None → getattr returns None safely
            return int(getattr(params, "min_score", 7))
        except Exception:
            return 7

    def _build_entry_tag(self, sym: Any) -> str:
        """#archive B2 — the per-entry CONTEXT tag (URL-query), set on the entry order by the engine
        fire seam (the optional `_build_entry_tag` hook). Recovered post-run via /orders/read → the
        results archive's per-trade `decision_*` context (the conditions the entry SAW). The durable
        channel: logs/charts/ObjectStore are unretrievable; the order tag is.

        decision_* fields (HQ: separate decision-context from execution-fill): score + the 8 BCT
        conditions (the learn-substrate core, from the snapshot) + the intraday confirm context
        (gap_pct, vol_ratio, tenkan_dist, recomputed from _intraday + the snapshot's signal_price) +
        scanner rank. Best-effort + bounded: a piece that can't be cleanly resolved is OMITTED, never
        faked. Fail-LOUD (DegradedDataError) if the tag exceeds ENTRY_TAG_MAX — never silent-truncate
        (a truncated tag = corrupt learn data). Regime (spy>200ma, vix) = #archive-followup.

        #archive ①: the ENCODE lives in the SHARED tag_schema module (single source of truth) so
        this emit and the parse in sweeps.archive.snapshot CANNOT desync — a key/format change
        round-trips by construction (test_tag_schema). tag_schema is bundled into dist/ via the build
        import-closure (lean_entry imports it → the cloud side can emit)."""
        snap = getattr(self, "_candidate_snapshot", {}).get(sym, {})
        ist = getattr(self, "_intraday", {}).get(sym, {})
        # gather the RAW values; None = unresolvable → encode_entry_tag OMITS it (never fakes).
        sp = snap.get("signal_price")
        last_close = ist.get("last_close")
        gap = (last_close - sp) / sp if (sp and last_close is not None) else None
        vol = None
        vw = ist.get("vol_window")
        last_bar = ist.get("last_bar")
        n = getattr(vw, "count", 0) if vw is not None else 0
        if n > 0 and last_bar is not None:
            mean_vol = sum(vw[i] for i in range(n)) / n
            if mean_vol > 0:
                vol = float(last_bar.volume) / mean_vol
        tk = ist.get("intraday_tenkan")
        tdist = ((last_close - float(tk.current.value)) / last_close
                 if (tk is not None and getattr(tk, "is_ready", False) and last_close) else None)
        # SCANNER RANK — the candidate's position in today's ranked universe (_ranked_today).
        # #276b-1 FIX3: _ranked_today holds LOWERCASE tickers (coarse-derived) but sym.value is
        # UPPERCASE → the old `val in ranked` was ALWAYS False on cloud (rank omitted for EVERY
        # entry). Normalize BOTH sides through canonical_symbol_key (the single-source key form) so
        # rank resolves regardless of case. OMIT-on-genuine-absence preserved: a candidate not in
        # _ranked_today → key not in the index → rank=None (encode_entry_tag omits it; never faked).
        val = getattr(sym, "value", None)
        ranked = getattr(self, "_ranked_today", [])
        # first-occurrence wins (matches the old list.index semantics; _ranked_today is deduped).
        ranked_key_to_rank: dict[str, int] = {}
        for i, t in enumerate(ranked):
            ranked_key_to_rank.setdefault(canonical_symbol_key(t), i)
        rank = ranked_key_to_rank.get(canonical_symbol_key(sym)) if val is not None else None
        tag = encode_entry_tag(score=snap.get("score"), conditions=(snap.get("conditions") or None),
                               gap=gap, vol=vol, tdist=tdist, rank=rank)
        if len(tag) > self.ENTRY_TAG_MAX:
            raise DegradedDataError(
                f"entry tag {len(tag)} > ENTRY_TAG_MAX={self.ENTRY_TAG_MAX} for {val} — would "
                f"truncate the learn-substrate context; fail loud (#archive B2, never silent-truncate)"
            )
        return tag

    def _capture_candidate_snapshot(self, winners: "list[str]") -> None:
        """#276b-0/#276b-1 daily→intraday handoff. Snapshot each DECIDED candidate's thesis
        ({signal_price, daily_kijun, decision_date}) so the intraday clock (PreFlightStaleness +
        confirm, #276b-1) can validate against it.

        `winners` = the daily SIGNAL winners (BctScoreFull score>=7, from the daily pipeline's
        ctx.bar_state.sized_orders) — the WHO. #276b-1 fix: snapshot THESE, not the pre-signal
        ranked universe (qc._ranked_today) — snapshotting the universe bypassed the signal filter +
        starved the capped intraday feeds → silent 0 orders.

        REUSE-IDENTITY (the desync killer, HQ): key the snapshot by the SAME canonical Symbol that
        `_active`/`_intraday` already hold — resolve the winner tickers via `_active` (the
        `{value.lower(): sym}` idiom), NEVER `Symbol.create(...)`. If we never re-create a Symbol,
        a subscribed≠decided key drift cannot occur by construction.

        signal_price = T's decision-bar close (the gap reference); daily_kijun = the maintained
        daily Ichimoku (O(1), no history). Rebuilt fresh each daily decision → a name dropped from
        today's winner set disappears. A candidate not yet subscribed (on_securities_changed lag) or
        with a cold daily Ichimoku is SKIPPED here — the intraday side's H1 then treats a subscribed
        name with no snapshot as not-enterable (skip-loud), so a missing thesis can never fire."""
        # canonical identity, reused — never Symbol.create (the desync killer).
        active_by_key = {canonical_symbol_key(s): s for s in getattr(self, "_active", set())}  # #276b-1 FIX3
        indicators = getattr(self, "_indicators", {})
        decision_date = self.time.date()
        snap: dict[Any, dict[str, Any]] = {}
        for ticker in winners:
            sym = active_by_key.get(canonical_symbol_key(ticker))
            if sym is None:
                continue  # decided but not yet subscribed — H1 covers it on the intraday side
            ind = indicators.get(sym)
            d_ichi = ind.get("d_ichi") if ind else None
            if d_ichi is None or not getattr(d_ichi, "is_ready", False):
                continue  # cold daily thesis → not enterable; never snapshot a half-formed thesis
            # #archive B1: capture the LEARN-SUBSTRATE at decision time — the BCT score + the 8
            # conditions INDIVIDUALLY (the mine learns WHICH of George's conditions predict R, not
            # just "score>=7"). score_symbol_native re-reads the SAME maintained indicators (O(1),
            # history-free) the signal phase scored on → identical result, no signal-phase threading.
            # BIT ORDER (STABLE — a change is a schema_version bump; see results-archive-design.md):
            #   0 weekly price>cloud · 1 weekly tenkan>kijun · 2 weekly chikou(price>price26ago) ·
            #   3 weekly cloud green(SpanA>SpanB) · 4 daily price>cloud · 5 daily price>tenkan ·
            #   6 ADX rising ∧ +DI>-DI ∧ ADX>=20 · 7 daily price>200ma  (== CLAUDE.md BCT stack).
            # Winners just passed score_symbol_native in the signal phase (same decision, same
            # maintained ind) → re-scoring here succeeds in prod. Guard defensively: a re-score
            # failure must NOT crash the snapshot (→ silent-0 entries); log it LOUD as a context gap
            # and proceed on the already-validated signal_price/daily_kijun (conditions just absent
            # from the learn-substrate for this name — a data gap, not a trade blocker).
            # #348 FEATURE-CAPTURE FIX: read the pass-time features the SIGNAL phase stamped
            # (qc._signal_features), keyed by the same canonical Symbol. These ARE the score + 8
            # conditions the signal selected this name on (native or cached path) → authoritative by
            # construction, NO re-score. The old re-score path threw for ~5/36 entries incl the biggest
            # winners HOOD/GLW (score_symbol_native on a live ind that went cold between signal-eval and
            # here) → context_status=CORE_MISSING, blind winners with null features — the #348 blind
            # spot. No drift check needed on this path: it is the signal's own decision, not a re-derive.
            feat = getattr(self, "_signal_features", {}).get(sym)
            scored: dict[str, Any] | None
            if feat is not None:
                scored = {"score": int(feat["score"]), "conditions": list(feat["conditions"])}
            else:
                assert ind is not None  # non-None by the d_ichi guard above (continue'd if ind None)
                # Defensive fallback (a winner somehow absent from _signal_features — should not occur):
                # re-score + the DRIFT TRIPWIRE (a sub-min_score re-score = desynced ind → booleans
                # untrustworthy → drop to None rather than record drifted truth).
                try:
                    scored = score_symbol_native(self, sym, ind)
                except Exception as exc:  # incomplete/edge ind
                    scored = None
                    _log = getattr(self, "log", None)
                    if callable(_log):
                        _log(f"CONTEXT_GAP|{decision_date}|{getattr(sym, 'value', sym)}|rescore-failed:{type(exc).__name__}")
                min_score = self._signal_min_score()
                if scored is not None and int(scored["score"]) < min_score:
                    _log = getattr(self, "log", None)
                    if callable(_log):
                        _log(f"CONTEXT_GAP|{decision_date}|{getattr(sym, 'value', sym)}|score-drift:"
                             f"rescore={scored['score']}<min_score={min_score} — booleans suspect, dropped")
                    scored = None
            conditions = [bool(c) for c in scored["conditions"]] if scored else []
            snap[sym] = {
                "signal_price": float(self.securities[sym].price),
                "daily_kijun": float(d_ichi.kijun.current.value),
                # #339: cloud bottom (min Senkou A/B) — the structural floor for CloudProtectiveStop
                # (the G3-winning cloud-bottom stop). Additive; KijunProtectiveStop ignores it.
                "daily_cloud_bottom": float(min(d_ichi.senkou_a.current.value,
                                                d_ichi.senkou_b.current.value)),
                "decision_date": decision_date,
                "score": int(scored["score"]) if scored else None,   # the aggregate (back-compat)
                "conditions": conditions,                            # the 8 booleans (learn-substrate core)
            }
        self._candidate_snapshot = snap
        log = getattr(self, "log", None)
        if callable(log):
            log(f"SNAPSHOT|{decision_date}|candidates={len(snap)}")

    def snapshot_for_entry(self, sym: Any) -> "dict[str, Any] | None":
        """#276b-0 H1 + H2 — the guarded accessor the intraday entry phases (#276b-1) MUST use to
        read a candidate's thesis. SINGLE authority gate so the desync/staleness checks cannot be
        bypassed per-phase.

        H1 (snapshot-is-authority): a symbol with NO snapshot entry is NOT enterable → return None
        + skip-loud (logged); the caller skips it, NEVER falls back to entering. A subscribed name
        the daily clock did not decide cannot fire an unauthorized entry.

        H2 (staleness fail-loud): the snapshot's decision_date MUST be the most-recent daily
        decision (`_last_daily_date`). An older date = a missed/failed daily handoff → acting on it
        would trade a stale thesis → DegradedDataError (the SG9 desync tripwire), never a silent
        2-day-stale entry."""
        snap = self._candidate_snapshot.get(sym)
        if snap is None:
            log = getattr(self, "log", None)
            if callable(log):
                log(f"SNAPSHOT_SKIP|{getattr(sym, 'value', sym)}|no decided thesis — not enterable (H1)")
            return None
        if self._last_daily_date is not None and snap["decision_date"] != self._last_daily_date:
            raise DegradedDataError(
                f"stale candidate snapshot for {getattr(sym, 'value', sym)}: decision_date="
                f"{snap['decision_date']} but last daily decision={self._last_daily_date} — a "
                f"missed daily→intraday handoff. Refusing to enter a stale thesis (#276b-0 H2, SG9)."
            )
        return snap

    def _decision_score_for(self, sym: Any) -> "int | None":
        """#339 rotation hook (called by the engine at FIRE_ENTRIES to stamp _position_meta). The
        entered name's daily decision_score from its snapshot thesis — so the rotation phase can rank
        HELD positions by signal strength vs new candidates. None if no snapshot/score (never raises:
        this is a metadata stamp, not an authority gate — the entry already passed snapshot_for_entry)."""
        snap = self._candidate_snapshot.get(sym)
        if snap is None:
            return None
        score = snap.get("score")
        return int(score) if score is not None else None

    def _inject_intraday_candidates(self, ictx: PhaseContext) -> None:
        """#276b-1 CANDIDATE INJECTION (the two-clock seam, HQ/Gemini-reviewed). ctx.bar_state is
        FRESH per 5-min tick; the standing daily candidates live in `_candidate_snapshot` (276b-0).
        Seed a qty=0 OrderIntent STUB per ELIGIBLE candidate into ictx.bar_state.sized_orders so the
        intraday entry_selection phases (PreFlightStaleness → BctIntradayConfirm) can gate them, then
        entry_timing → sizing → FIRE_ENTRIES fire the confirmed/sized ones.

        RANK-PRESERVING (Gemini fix #3): `_candidate_snapshot` is built by iterating `_ranked_today`
        into an insertion-ordered dict, so iterating it here preserves rank → on a capital-constrained
        tick, sizing/BP is consumed highest-rank first.

        ELIGIBILITY (Gemini fix #1): inject iff NOT invested AND NOT pending. `invested` blocks
        re-entry on a held name (its EXITS run on the intraday clock via exit_hard, never re-injected
        as an entry — SG8). `pending` (an entry order in-flight this session) blocks double-entry; a
        broker reject drops it from pending (on_order_event) → re-injectable next tick.

        The qty=0 stub is an INTERNAL artifact — FIRE_ENTRIES's `qty <= 0` guard (Gemini fix #2)
        ensures a stub that no phase sized NEVER reaches the broker."""
        snapshot = getattr(self, "_candidate_snapshot", {})
        if not snapshot:
            return
        pending: set[Any] = getattr(self, "_pending_entry_today", set())
        entered: set[Any] = getattr(self, "_entered_today", set())  # same-session re-entry guard (SHOP churn)
        injected = 0
        for sym in snapshot:  # insertion order == rank order (rank-preserving)
            # skip invested ∪ pending ∪ already-entered-this-session. The last kills the instant
            # stop-out → re-inject → re-fire churn: a name whose entry FILLED today is done for the
            # session even if its protective floor sold it back to flat.
            if self.portfolio[sym].invested or sym in pending or sym in entered:
                continue
            # ticker=sym.value (the QC Symbol's identity string) — #276b-1 FIX3: ALL downstream
            # resolvers (sizing/FIRE_ENTRIES, the intraday gate phases, the snapshot) now key active
            # symbols by canonical_symbol_key, which normalizes case at lookup → the emitted case no
            # longer has to match any resolver's convention. (Pre-FIX3 the resolvers open-coded
            # .value vs .value.lower(); a case-inconsistent emit here would silently skip a confirmed
            # candidate — the silent-0 class this migration eliminates.)
            ictx.bar_state.sized_orders.append(
                OrderIntent(ticker=sym.value, qty=0, price=0.0, stop=0.0,
                            module="signal", risk_dollars=0.0)
            )
            ictx.record_funnel("injection_survives", sym)  # #276b-1 funnel stage 6
            injected += 1
        if injected:
            log = getattr(self, "log", None)
            if callable(log) and getattr(self, "LOG_INTRADAY_INJECT_EVENTS", True):
                log(f"INTRADAY_INJECT|{self.time.date()}|candidates={injected}")

    def _mark_entry_pending(self, sym: Any) -> None:
        """#276b-1 (Gemini fix #1) — engine hook called when an ENTRY order is SUBMITTED. Marks the
        sym as having an entry in-flight so `_inject_intraday_candidates` won't re-inject it before
        the order resolves. Resolved by `on_order_event` (filled → invested covers it; rejected →
        re-injectable). Optional hook (engine guards with getattr) — no-op if the runtime omits it."""
        self._pending_entry_today.add(sym)

    def on_order_event(self, order_event: Any) -> None:
        """#276b-1 entry PENDING-STATE machine + #277 GTC-floor-fill cleanup.

        ENTRY pending (Gemini fix #1): an entry submission is NOT a success — a broker reject
        (insufficient BP, halt, locate, gross-cap) leaves the position un-invested. So on any
        TERMINAL status for a pending sym, drop it from pending — Filled/PartiallyFilled → now
        invested (invested-check blocks re-injection); Canceled/Invalid → re-injectable next tick.

        GTC-FLOOR-FILL cleanup (#277): the #290 protective stop (protective_stop_ticket in
        _position_meta) is a BROKER-side GTC — it can FIRE intrabar (gap/halt) WITHOUT the runtime
        FIRE_EXITS path running. FIRE_EXITS is the ONLY path that pops _position_meta; so a
        broker-floor fill leaves STALE meta → a later re-entry of that name (no longer invested, the
        floor sold it) hits GUARD-3 fail-loud (#276a — re-entry with a 'live' tracked stop). Fix:
        when the order that FILLED IS the tracked protective_stop_ticket (match by order id), pop
        _position_meta[sym] + clear pending so the re-entry is clean. Distinct from the deferred
        #181 cancel-replace (resize-on-trim/add); this is just the broker-floor-fill cleanup.
        A runtime FIRE_EXITS already popped meta → this is then a harmless no-op (idempotent pop)."""
        sym = getattr(order_event, "symbol", None)
        if sym is None:
            return
        status = getattr(order_event, "status", None)
        if OrderStatus is None:
            return  # dev venv / no QC enum — nothing to compare statuses against
        # ENTRY pending machine
        if sym in self._pending_entry_today and status in {
            OrderStatus.Filled, OrderStatus.PartiallyFilled, OrderStatus.Canceled, OrderStatus.Invalid
        }:
            self._pending_entry_today.discard(sym)
            # SHOP-churn guard: a real entry FILL (not a Canceled/Invalid reject) marks the name as
            # entered THIS session → not re-injectable even if its protective floor sells it back to
            # flat. A reject is NOT marked → stays re-injectable (retry-on-reject intent preserved).
            if status in {OrderStatus.Filled, OrderStatus.PartiallyFilled}:
                self._entered_today.add(sym)  # always init'd in __init__ (mutate the real set, not a default)
        # GTC-floor-fill cleanup: the FULLY-filled order IS the tracked protective stop → floor done.
        # FILLED-ONLY (NOT PartiallyFilled — Gemini): a partial stop-fill leaves the REMAINDER LIVE at
        # the broker; popping _position_meta on a partial would LOSE the ticket → orphan stop → the
        # orphan fires later + over-sells (long→short). A stop is "done" only when fully Filled or
        # Canceled. (The entry-pending path above correctly uses Filled∪PartiallyFilled — a partial
        # ENTRY = position open → invested-check covers it. Different terminal semantics per path.)
        if status == OrderStatus.Filled:
            meta = getattr(self, "_position_meta", {}).get(sym)
            ticket = meta.get("protective_stop_ticket") if meta else None
            if ticket is not None:
                ev_id = getattr(order_event, "order_id", getattr(order_event, "OrderId", None))
                tk_id = getattr(ticket, "order_id", getattr(ticket, "OrderId", None))
                if ev_id is not None and tk_id is not None and ev_id == tk_id:
                    self._position_meta.pop(sym, None)        # floor sold the position — clear its meta
                    self._pending_entry_today.discard(sym)    # and any stale pending (re-entry now clean)

    # ------------------------------------------------------------------------------------
    # #276b-1 FUNNEL — the 9 cumulative candidate-collapse counters. Observe-only: nothing in the
    # trading path reads these; they localize WHERE the ~40-names/day daily signal collapses to ~78
    # orders/FY (Falk's "78 is too sparse" verdict — the collapse stage IS the legit-vs-bug answer).
    # ------------------------------------------------------------------------------------
    def _ensure_funnel_state(self) -> None:
        """Lazy-init the funnel state. initialize() sets it for a real run; a bare-constructed algo
        (a unit-test fixture that never runs initialize()) reaches the accumulators without it. Init
        on demand (idempotent) so the funnel is observe-only AND robust — never crashes a hot path."""
        if not hasattr(self, "_funnel_cum"):
            self._funnel_cum = {stage: 0 for stage in FUNNEL_STAGES}
        if not hasattr(self, "_funnel_today"):
            self._funnel_today = {stage: set() for stage in FUNNEL_INTRADAY_STAGES}
        if not hasattr(self, "_funnel_seen"):
            self._funnel_seen = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}

    def _accumulate_daily_funnel(self, signal_winner_tickers: "list[str]", blocked: bool) -> None:
        """Fold the DAILY funnel stages into the cumulative counters (called once per daily decision).
        signal_winners += the raw signal-winner count (pre-regime). regime_pass += that same count on
        a non-blocked day (the winners passed the regime gate) or 0 on a blocked day; regime_blocked_days
        += 1 on a blocked day — kept SEPARATE so the regime cut never masquerades as the confirm cut."""
        self._ensure_funnel_state()
        n = len(signal_winner_tickers)
        self._funnel_cum["signal_winners"] += n
        if blocked:
            self._funnel_cum["regime_blocked_days"] += 1
            # regime_pass += 0 (no winner survived the gate this day)
        else:
            self._funnel_cum["regime_pass"] += n

    def _fold_intraday_funnel(self, ictx: Any) -> None:
        """Fold ONE intraday tick's per-stage survivor sets (ctx.bar_state.funnel, written by the gate
        phases) into the per-DAY sets, and accumulate this tick's fired entries (stage 9 `orders`).
        Set membership IS the per-day dedup — a candidate evaluated every 5-min tick is counted ONCE
        per day at each stage. The per-day sets accumulate into _funnel_cum at session end
        (_flush_funnel_day). `orders` accumulates directly (each fire is a distinct order, no dedup)."""
        self._ensure_funnel_state()
        bar_funnel = getattr(ictx.bar_state, "funnel", {})
        for stage in FUNNEL_INTRADAY_STAGES:
            survivors = bar_funnel.get(stage)
            if survivors:
                self._funnel_today[stage].update(survivors)
        # stage 9 (orders): the entries the engine ACTUALLY fired this tick (the FIRE_ENTRIES count).
        self._funnel_cum["orders"] += int(getattr(self.engine, "_fired_entries", 0))

    def _process_eod_funnel(self) -> None:
        """End-of-day funnel processing (DRY — called by on_end_of_day AND the on_end_of_algorithm
        backstop): flush the per-day intraday survivor sets into the cumulative counters + reset, then
        re-publish the runtime stats. GUARDED for a selection-harness/test path that never ran
        initialize() (no funnel state). Idempotent (flush resets the sets → a repeat call adds 0)."""
        if hasattr(self, "_funnel_today") and hasattr(self, "_funnel_cum"):
            self._flush_funnel_day()
            self._push_funnel_runtime_stats()

    def _flush_funnel_day(self) -> None:
        """At session end: fold each intraday per-day survivor set into its cumulative counter, then
        reset the per-day sets for T+1. The daily stages + `orders` already accumulated directly
        (per-decision / per-fire), so only the intraday per-day sets flush here. Two semantics (see
        FUNNEL_STAGE_SEMANTICS):
          - CANDIDATE-DAY stages (gap_eligible/confirm_fire/sized/cash_ok): += len(per-day set). A
            name reaching the stage on N distinct days legitimately counts N (a gap on N days IS N
            gap-eligible-days).
          - DISTINCT stages (preflight_pass/injection_survives): UNION the per-day set into the
            RUN-cumulative _funnel_seen[stage], then set the counter = len(that run-set). Each distinct
            candidate is counted ONCE the first time it EVER reaches the stage — re-injection /
            re-evaluation on later days does NOT re-count (the #303 reinjection-overcount fix that made
            those two stages misread as a >100% pass-rate vs signal_winners). Idempotent under QC's
            per-symbol on_end_of_day: the per-day set resets to empty, so a repeat flush unions {} (no
            change) and re-asserts the same len (no double-count)."""
        # defensive: a hand-constructed fixture may set _funnel_today/_funnel_cum but not _funnel_seen
        # (the real __init__/_ensure_funnel_state always create all three together). Ensure it here so
        # the distinct-stage fold below never AttributeErrors. Idempotent (only creates if absent).
        if not hasattr(self, "_funnel_seen"):
            self._funnel_seen = {stage: set() for stage in FUNNEL_DISTINCT_STAGES}
        for stage in FUNNEL_CANDIDATE_DAY_STAGES:
            self._funnel_cum[stage] += len(self._funnel_today[stage])
            self._funnel_today[stage] = set()
        for stage in FUNNEL_DISTINCT_STAGES:
            self._funnel_seen[stage] |= self._funnel_today[stage]
            self._funnel_cum[stage] = len(self._funnel_seen[stage])
            self._funnel_today[stage] = set()

    def _push_funnel_runtime_stats(self) -> None:
        """Expose the 9 cumulative funnel counters as QC RUNTIME STATISTICS (the retrievable channel:
        logs/charts/ObjectStore are dead; runtime stats survive). GUARDED — set_runtime_statistic /
        SetRuntimeStatistic may be ABSENT locally (QCAlgorithm==object in the dev venv); the
        _funnel_cum attrs always hold the numbers regardless, for local/tests. Single code path, no
        if-cloud branch. Best-effort: a missing API is a silent no-op (the attrs are the source).

        #303 legend: ALSO push the per-stage SEMANTIC UNIT under a SEPARATE key namespace
        (funnel._sem.<stage> → distinct|candidate_days|daily|fire). The existing funnel.<stage> count
        keys are UNCHANGED (renaming them breaks the existing read) — the legend is purely additive so
        the mine can tell a distinct-candidate count from a candidate-DAY count and never compute a
        nonsense cross-unit pass-rate (the preflight/injection >100% misread)."""
        setter = getattr(self, "set_runtime_statistic", None) or getattr(self, "SetRuntimeStatistic", None)
        if not callable(setter):
            return
        for stage in FUNNEL_STAGES:
            setter(f"funnel.{stage}", str(self._funnel_cum[stage]))
            setter(f"funnel._sem.{stage}", FUNNEL_STAGE_SEMANTICS[stage])

    def _clear_intraday_session_state(self) -> None:
        """#276b-0 H3/SG9 — clear the deferred intraday-confirm PROGRESS + the entry PENDING set at
        session end so neither an unconfirmed candidate nor an in-flight-entry marker bleeds into
        T+2's session. _candidate_snapshot is NOT cleared here (it is overwritten by the next daily
        decision — a held thesis legitimately survives the same-day boundary); only the per-session
        confirm progress + pending-entry markers reset."""
        self._entry_confirm = {}
        self._pending_entry_today = set()
        self._entered_today = set()  # SHOP-churn guard resets each session (next session re-allows entry)
        # #276b-1 FUNNEL: flush the per-day intraday survivor sets into the cumulative counters and
        # reset for T+1, then re-publish the runtime stats. SAFE under QC's per-symbol on_end_of_day
        # firing: the first call accumulates len(set) + resets the sets to empty, so subsequent calls
        # this session add 0 (idempotent). Observe-only, never affects trading.
        self._process_eod_funnel()

    def on_end_of_day(self, symbol: Any = None) -> None:
        """QC session-end hook — clear the intraday-confirm progress (H3/SG9). Idempotent (QC fires
        it per-symbol; clearing an already-empty store is a no-op)."""
        self._clear_intraday_session_state()
