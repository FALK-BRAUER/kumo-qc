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
from engine.context import PhaseContext
from engine.engine import StrategyEngine
from runtime.indicators import INDICATOR_KEYS, TBounceTracker, weekly_aggregate
from runtime.universe_select import (
    DvWindow,
    apply_floors,
    rank_and_cap,
    rolling_dv_mean,
    update_dv_windows,
)


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
    Field = MovingAverageType = None


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

    def initialize(self) -> None:
        self.set_start_date(*self.START_DATE)
        self.set_end_date(*self.END_DATE)
        self.set_cash(self.CASH)
        self.set_benchmark("SPY")
        self.set_time_zone("America/New_York")  # match legacy champion (scheduling/timestamps)
        self.set_warmup(timedelta(days=self.WARMUP_DAYS))

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
        active_by_lower = {s.value.lower(): s for s in self._active}
        # the capped candidate slice that gets an intraday feed (scan-breadth cap, not a position cap)
        capped = candidates[: self.INTRADAY_SUBSCRIBE_CAP]
        if len(candidates) > self.INTRADAY_SUBSCRIBE_CAP:
            self.log(
                f"INTRADAY_CAP|candidates={len(candidates)}|capped_to={self.INTRADAY_SUBSCRIBE_CAP}"
            )
        want: set[Any] = set()
        for tk in capped:
            sym = active_by_lower.get(tk.lower())
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
                self.engine.on_intraday_bar(ictx)

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
        # #275b-fix (LAG): reconcile intraday subs BEFORE the pipeline — qc._active/_ranked_today are
        # CURRENT for T (on_securities_changed has fired), so T's candidates get their T+1 5-min feed.
        self._sync_intraday_subscriptions(getattr(self, "_ranked_today", []))
        ctx = PhaseContext(qc=self, time=self.time, data=None)  # scheduled event — no slice; daily phases read maintained indicators
        ctx.clock = "daily"
        self.engine.on_data_with_ctx(ctx)
        # #276b-0: capture the daily→intraday thesis snapshot AFTER the pipeline (relocated
        # here from the removed on_data daily block — #313 Q-D). The intraday clock reads it.
        self._capture_candidate_snapshot()

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
        if not getattr(self, "_schedule_armed", False):
            return  # scheduler never armed (selection-harness context) — nothing to reconcile
        gap = getattr(self, "_sched_trading_days", 0) - getattr(self, "_sched_decisions", 0)
        if gap > 1:
            raise DegradedScheduleError(
                f"daily-decision UNDER-FIRE at end-of-run (#313 watchdog backstop): "
                f"{self._sched_trading_days} post-warmup trading days vs {self._sched_decisions} "
                f"decisions (gap {gap} > 1) — the scheduled after-close trigger under-fired."
            )

    def _capture_candidate_snapshot(self) -> None:
        """#276b-0 daily→intraday handoff. Snapshot each DECIDED candidate's thesis
        ({signal_price, daily_kijun, decision_date}) so the intraday clock (PreFlightStaleness +
        confirm, #276b-1) can validate against it.

        REUSE-IDENTITY (the desync killer, HQ): key the snapshot by the SAME canonical Symbol that
        `_active`/`_intraday` already hold — resolve today's ranked tickers via `_active` (the L615
        `{value.lower(): sym}` idiom), NEVER `Symbol.create(...)`. If we never re-create a Symbol,
        a subscribed≠decided key drift cannot occur by construction.

        signal_price = T's decision-bar close (the gap reference); daily_kijun = the maintained
        daily Ichimoku (O(1), no history). Rebuilt fresh each daily decision → a name dropped from
        today's ranked set disappears. A candidate not yet subscribed (on_securities_changed lag) or
        with a cold daily Ichimoku is SKIPPED here — the intraday side's H1 then treats a subscribed
        name with no snapshot as not-enterable (skip-loud), so a missing thesis can never fire."""
        # canonical identity, reused — never Symbol.create (the desync killer).
        active_by_lower = {s.value.lower(): s for s in getattr(self, "_active", set())}
        indicators = getattr(self, "_indicators", {})
        decision_date = self.time.date()
        snap: dict[Any, dict[str, Any]] = {}
        for ticker in getattr(self, "_ranked_today", []):
            sym = active_by_lower.get(ticker.lower())
            if sym is None:
                continue  # decided but not yet subscribed — H1 covers it on the intraday side
            ind = indicators.get(sym)
            d_ichi = ind.get("d_ichi") if ind else None
            if d_ichi is None or not getattr(d_ichi, "is_ready", False):
                continue  # cold daily thesis → not enterable; never snapshot a half-formed thesis
            snap[sym] = {
                "signal_price": float(self.securities[sym].price),
                "daily_kijun": float(d_ichi.kijun.current.value),
                "decision_date": decision_date,
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

    def _clear_intraday_session_state(self) -> None:
        """#276b-0 H3/SG9 — clear the deferred intraday-confirm PROGRESS at session end so an
        unconfirmed candidate at T+1 close does NOT bleed into T+2's session. _candidate_snapshot is
        NOT cleared here (it is overwritten by the next daily decision — a held thesis legitimately
        survives the same-day boundary); only the per-session confirm progress resets."""
        self._entry_confirm = {}

    def on_end_of_day(self, symbol: Any = None) -> None:
        """QC session-end hook — clear the intraday-confirm progress (H3/SG9). Idempotent (QC fires
        it per-symbol; clearing an already-empty store is a no-op)."""
        self._clear_intraday_session_state()
