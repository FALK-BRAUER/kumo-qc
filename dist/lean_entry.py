"""LEAN entry (#213) — the single code path that runs the engine LOCAL and CLOUD.

This is the historic #182 divergence site. The legacy main.py diverged because it loaded
the universe from DISK locally but ObjectStore on cloud, AND silently fell through when
the cloud key was missing — so cloud and local selected different stocks from day 1. This
module kills that at the source:

  - ONE loader, ObjectStore both sides (qc.object_store works identically under local LEAN
    and cloud). NO `if cloud:` branch.
  - FAIL-LOUD on a missing key (UniverseLoadError) — never fall through to trade-everything.
  - FINGERPRINT-VERIFY on load: recompute the loaded artifact's fingerprint with the SAME
    function used at build time (runtime.fingerprints) and assert it equals the pinned
    value. Same key but DIFFERENT bytes (cloud ObjectStore != local) raises
    UniverseFingerprintError instead of silently diverging. This is the structural guarantee
    that local and cloud loaded the SAME artifact.
  - RAW normalization on every subscription (the 2649e2e lesson — adjusted prices corrupt
    Ichimoku).
  - ACTIVE-SET hash logged each rebalance (count + sha256 of the sorted subscribed symbols)
    — the diff-ladder rung between order-fp and trades for divergence-debug.

The pure functions (load_universe / verify_fingerprint / active_set_hash) carry the
#182-critical logic and are unit-tested with a fake qc. BctEngineAlgorithm is a thin
QCAlgorithm shell (QC runtime only); its wiring is integration-verified on a LEAN run.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import timedelta
from hashlib import sha256
from typing import Any

import pandas as pd

from base import UniverseFingerprintError, UniverseLoadError
from context import PhaseContext
from engine import StrategyEngine
from fingerprints import membership_hash, order_hash
from indicators import INDICATOR_KEYS, weekly_aggregate


def _read_object_store(qc: Any, key: str) -> Any:
    """Read + JSON-parse an ObjectStore artifact. FAIL-LOUD if the key is absent — the
    legacy silent-fallback (trade-everything / SPY-ETF) is exactly the #182 bug. A missing
    key at runtime is a deploy/upload error and must stop the algorithm."""
    store = qc.object_store
    if not store.contains_key(key):
        raise UniverseLoadError(
            f"ObjectStore key '{key}' missing — refusing to run (upload the artifact both "
            f"sides; never fall through to trade-everything). This is the #182 guard."
        )
    raw = store.read(key)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise UniverseLoadError(f"ObjectStore key '{key}' is not a JSON object")
    return parsed


def _strip_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the leading-underscore meta block(s); keep only date-keyed entries."""
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def verify_fingerprint(name: str, recomputed: str, expected: str) -> None:
    """Assert a recomputed artifact fingerprint equals the pinned build-time value.
    Mismatch => same key, DIFFERENT bytes (the silent-divergence #182 failure mode) => raise."""
    if recomputed != expected:
        raise UniverseFingerprintError(
            f"{name} fingerprint mismatch: loaded artifact hashes to {recomputed} but the "
            f"pinned value is {expected}. ObjectStore bytes differ from the build — local "
            f"and cloud are NOT running the same universe. Refusing to run (the #182 guard)."
        )


def load_universe(
    qc: Any,
    *,
    eligible_key: str,
    universe_key: str,
    expected_membership_fp: str,
    expected_order_fp: str,
) -> None:
    """Load + verify both universe artifacts from ObjectStore and assign them onto qc.

    Sets qc._eligible (filter artifact, date -> {ticker: dv}) and qc._universe (ranked
    artifact, date -> [ranked tickers]). IDENTICAL code + IDENTICAL artifacts both sides.
    Recomputes each fingerprint and verifies it against the pinned value before assigning —
    on any mismatch or missing key it RAISES and the algorithm does not run.
    """
    eligible_payload = _strip_meta(_read_object_store(qc, eligible_key))
    universe_payload = _strip_meta(_read_object_store(qc, universe_key))

    verify_fingerprint("membership (filter)", membership_hash(eligible_payload), expected_membership_fp)
    verify_fingerprint("order (universe)", order_hash(universe_payload), expected_order_fp)

    qc._eligible = eligible_payload
    qc._universe = universe_payload


def ranked_for_date(universe: dict[str, list[str]], date_str: str) -> list[str]:
    """Today's ranked candidate tickers from OUR artifact — the SINGLE source of the active
    set (artifact-driven, fintrack ruling). Empty for a non-trading / out-of-range date.
    The subscription is built from THIS list, never from QC's coarse-fundamental feed (that
    would be a second universe source that can diverge local-vs-cloud — the #182 class)."""
    return list(universe.get(date_str, []))


def active_set_hash(symbols: Iterable[str]) -> tuple[int, str]:
    """(count, sha256-of-sorted-symbols) for the subscribed active set. Logged each
    rebalance so divergence-debug can diff the active set local-vs-cloud — the rung between
    the order fingerprint and the trade list. A small delta is the accepted cloud-vendor
    residual; a material delta gets root-caused."""
    syms = sorted(symbols)
    h = sha256(",".join(syms).encode("utf-8")).hexdigest()
    return len(syms), h


# --------------------------------------------------------------------------------------
# QCAlgorithm shell — QC runtime only. Thin: delegates the #182-critical work to the pure
# functions above. Integration-verified on a LEAN run, not unit-tested (no QC locally).
# main.py (generated by build/cloud_package.py) sets the class attributes below.
# --------------------------------------------------------------------------------------
try:  # pragma: no cover - QC runtime import; absent in the dev venv / unit tests
    from AlgorithmImports import (
        Calendar,
        DataNormalizationMode,
        IchimokuKinkoHyo,
        Market,
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


class BctEngineAlgorithm(QCAlgorithm):  # pragma: no cover - QC runtime
    """Thin LEAN wrapper. Subclass in main.py sets STRATEGY_CONFIG / UNIVERSE_SPEC / dates /
    cash. initialize() subscribes RAW, fail-loud + fp-verify loads the universe, schedules on
    the trading calendar, and runs StrategyEngine per scheduled bar."""

    # set by the generated main.py subclass
    STRATEGY_CONFIG: Any = None
    UNIVERSE_SPEC: dict[str, str] = {}  # eligible_key, universe_key, membership_fp, order_fp
    START_DATE: tuple[int, int, int] = (2025, 1, 1)
    END_DATE: tuple[int, int, int] = (2025, 12, 31)
    CASH: int = 100_000

    # Indicator warmup length — EXACT legacy value (750d). Warmup drives first-ready ->
    # first-trade date -> parity; must match the champion.
    WARMUP_DAYS: int = 750

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

        # FAIL-LOUD + FP-VERIFY universe load (the #182 guard). Raises before any trading.
        spec = self.UNIVERSE_SPEC
        load_universe(
            self,
            eligible_key=spec["eligible_key"],
            universe_key=spec["universe_key"],
            expected_membership_fp=spec["membership_fp"],
            expected_order_fp=spec["order_fp"],
        )

        # Artifact-driven subscription (fintrack ruling): a scheduled universe selector that
        # returns OUR ranked symbols for the date — NOT QC's coarse feed. Every ranked ticker
        # has substrate data by construction, so coverage is complete both sides; the only
        # residual is data-vendor price differences. self.universe.dollar_volume etc. are NOT
        # used — the artifact IS the universe.
        self.add_universe(self._select_universe)

        self.engine = StrategyEngine(config=self.STRATEGY_CONFIG, qc=self)

        # Pin provenance on startup (substrate + both universe fps + config-hash + commit
        # live in dist/_metadata.py, logged by the engine's STRATEGY_INIT).
        self.log(
            f"LEAN_ENTRY_INIT|membership_fp={spec['membership_fp']}|"
            f"order_fp={spec['order_fp']}|start={self.START_DATE}|end={self.END_DATE}"
        )

    def _select_universe(self, _trigger: Any) -> Any:
        """Scheduled-universe selector: build today's subscription DIRECTLY from our ranked
        artifact (artifact-driven). Returns constructed equity Symbols for today's ranked
        tickers; QC subscribes them and drops any without data (the natural ∩ substrate).
        Sets qc._active and logs the active-set hash (the diff-ladder rung). NO coarse feed.

        Artifact tickers are canonically lowercase (zip stems); we upper-case to the QC
        convention before Symbol.create. The phases compare case-insensitively vs qc._active.
        _active itself is owned by on_securities_changed (the truly-subscribed set); this
        selector only requests + logs the artifact-driven active-set hash (the diff-ladder rung)."""
        date_str = self.time.strftime("%Y-%m-%d")
        tickers = ranked_for_date(self._universe, date_str)
        symbols = [Symbol.create(t.upper(), SecurityType.EQUITY, Market.USA) for t in tickers]
        count, h = active_set_hash(t.upper() for t in tickers)
        self.log(f"ACTIVE_SET|{date_str}|count={count}|hash={h}")
        return symbols

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
                del self._indicators[sym]

    def _register_indicators(self, sym: Any) -> None:
        """Build the per-symbol indicators into the qc._indicators[sym] contract (INDICATOR_KEYS).
        Daily ichimoku 9/26/26/52/26/26 + sma200 (QC native), weekly ichimoku fed by a MANUAL
        TradeBarConsolidator (Calendar.WEEKLY) — the proven QC-cloud resample-timeout fix
        (8048c29). EXACT legacy carve."""
        d_ichi = self.ichimoku(sym, 9, 26, 26, 52, 26, 26)
        sma200 = self.sma(sym, 200)
        w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)
        w_close = RollingWindow[float](28)
        consolidator = TradeBarConsolidator(Calendar.WEEKLY)

        def _on_weekly(_: Any, bar: TradeBar) -> None:
            w_ichi.update(bar)
            w_close.add(bar.close)

        consolidator.data_consolidated += _on_weekly
        self.subscription_manager.add_consolidator(sym, consolidator)

        # With the 750-day warmup the consolidator receives enough weekly bars automatically;
        # only seed manually outside warmup (avoid N× history() calls at init).
        if not self.is_warming_up:
            self._seed_weekly(sym, w_ichi, w_close)

        self._indicators[sym] = {
            "d_ichi": d_ichi,
            "w_ichi": w_ichi,
            "w_close": w_close,
            "sma200": sma200,
            "consolidator": consolidator,
        }
        assert set(self._indicators[sym]) == set(INDICATOR_KEYS)  # contract guard

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
            # EXACT legacy positional TradeBar ctor incl. period=1wk (main.py _seed_weekly) —
            # an empty TradeBar() defaults period=0 (end_time==time), deviating from legacy.
            bar = TradeBar(
                wb["friday"], sym,
                wb["open"], wb["high"], wb["low"], wb["close"],
                wb["volume"], timedelta(weeks=1),
            )
            w_ichi.update(bar)
            w_close.add(float(wb["close"]))

    def on_data(self, data: Any) -> None:
        """Per-bar entry: build the PhaseContext and run the engine. The engine fires on the
        QC trading calendar (on_data only ticks on trading days → closed days never read)."""
        ctx = PhaseContext(qc=self, time=self.time, data=data)
        self.engine.on_data_with_ctx(ctx)
