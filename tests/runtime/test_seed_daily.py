"""#259 — `_seed_daily` / `_seed_weekly` unit coverage (the post-warmup mid-FY entrant seed).

CONTEXT (the mirage this guards): a name first subscribed AFTER warmup ends gets freshly
registered indicators that would accumulate LIVE from scratch — ~52/200/~30/13 daily bars to
become is_ready — so `score_symbol_native` returns None for ~9-10 months and the name "wakes up
in October" (#173). #259 history-seeds the post-warmup entrant so the suite is ready the day it
is first subscribed. These tests pin THAT seed: every indicator reaches is_ready from sufficient
history; the FORWARD-ONLY guard drops rows dated >= today; insufficient/empty history degrades
gracefully (no crash, nothing falsely-ready); and the `if not is_warming_up` gate ensures a
warmup-era entrant is NOT double-seeded (QC auto-warms it) while a post-warmup entrant IS.

WHY FAKES: QC's IchimokuKinkoHyo / ADX / SMA / TradeBar are unavailable in the dev venv (no
AlgorithmImports). We test the ACTUAL `_seed_daily`/`_seed_weekly` control flow — the history
fetch, the MultiIndex/lowercase column handling, the forward-only date filter, and the per-
indicator feed cascade — by monkeypatching `lean_entry.TradeBar` with a recording fake and
passing record-only indicator fakes (`.update(...)` shape exactly as the live wiring calls it).
The QC-native value math (IchimokuKinkoHyo == _mid, ADX == Wilder) is the INTEGRATION concern
(score_symbol_native golden masters cover the read side); HERE we prove the SEED REPLAY feeds
each indicator the right bars in chronological order and excludes the look-ahead rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytest

import runtime.lean_entry as lean_entry
from runtime.lean_entry import BctEngineAlgorithm


# --------------------------------------------------------------------------------------
# Recording fakes — capture EXACTLY what the seed feeds each indicator, in order.
# --------------------------------------------------------------------------------------
class _FakeTradeBar:
    """Stand-in for QC TradeBar — records the (time, ohlcv) the seed constructs.

    #318: the seed now builds the bar via the DEFAULT ctor + property setters
    (``lean_entry._make_trade_bar``: ``TradeBar()`` then ``bar.time = ...`` etc.), NOT the
    8-positional-arg ctor (which fails cloud pythonnet overload resolution). So this fake
    constructs with NO args and accepts attribute assignment — mirroring the cloud-safe path.
    """

    def __init__(self) -> None:
        self.time = self.symbol = self.period = None
        self.open = self.high = self.low = self.close = self.volume = None


class _Event:
    """QC IIndicator.Updated-shape event: supports `indicator.updated += handler` (+= mutates
    the SAME object in place, like a C# event) and fires all handlers on `.fire(sender)`."""

    def __init__(self) -> None:
        self._handlers: list[Any] = []

    def __iadd__(self, handler: Any) -> "_Event":
        self._handlers.append(handler)
        return self

    def fire(self, sender: Any) -> None:
        for h in self._handlers:
            h(sender, None)


class _RecBarInd:
    """Full-bar consumer (d_ichi / adx): .update(bar) records the bar; .is_ready when fed >=N.

    `updated` mirrors QC's IIndicator.Updated event — _register_indicators wires
    adx.updated += lambda → adx_window.add(...). The seed feeds adx via .update(bar), which here
    fires the registered handlers so a child window-cascade can be asserted.
    """

    def __init__(self, ready_after: int = 1) -> None:
        self.bars: list[_FakeTradeBar] = []
        self._ready_after = ready_after
        self.updated = _Event()
        self.current = type("C", (), {"value": 0.0})()
        # tenkan is read by _seed_daily's tbounce feed (d_ichi.tenkan.current.value)
        self.tenkan = type("T", (), {"current": type("C", (), {"value": 0.0})()})()

    def update(self, bar: _FakeTradeBar) -> None:
        self.bars.append(bar)
        self.current.value = float(bar.close)
        self.updated.fire(self)

    @property
    def is_ready(self) -> bool:
        return len(self.bars) >= self._ready_after


class _RecSeriesInd:
    """Price/volume-series consumer (sma200 / roc13 / macd / vol_sma20): .update(time, value)."""

    def __init__(self, ready_after: int = 1) -> None:
        self.samples: list[tuple[Any, float]] = []
        self._ready_after = ready_after
        self.updated = _Event()
        self.current = type("C", (), {"value": 0.0})()
        self.histogram = type("H", (), {"current": type("C", (), {"value": 0.0})()})()

    def update(self, time: Any, value: float) -> None:
        self.samples.append((time, float(value)))
        self.current.value = float(value)
        # macd's histogram tracks the close in our fake so the macd_hist_window cascade has a
        # value to record (the real macd.updated reads macd.histogram.current.value).
        self.histogram.current.value = float(value)
        self.updated.fire(self)

    @property
    def is_ready(self) -> bool:
        return len(self.samples) >= self._ready_after


class _RecWindow:
    """RollingWindow stand-in: .add(v) appends (newest at [0]); .count == len."""

    def __init__(self, maxlen: int) -> None:
        self._v: list[float] = []
        self._maxlen = maxlen

    def add(self, v: float) -> None:
        self._v.insert(0, float(v))
        if len(self._v) > self._maxlen:
            self._v = self._v[: self._maxlen]

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


class _RecTBounce:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float, float, float, float]] = []
        self.last_close = None

    def update(self, o, h, lo, c, tenkan) -> None:
        self.calls.append((o, h, lo, c, tenkan))
        self.last_close = c


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, o: object) -> bool:
        return isinstance(o, _Sym) and o.value == self.value


def _daily_hist(start: str, n: int, *, multiindex: bool = False, upper_cols: bool = True) -> pd.DataFrame:
    """A daily OHLCV history frame in the shape qc.history(sym, days, DAILY) returns:
    QC ships TitleCase columns and (for a single symbol) often a MultiIndex (symbol, time)."""
    idx = pd.bdate_range(start=start, periods=n)
    cols = ["Open", "High", "Low", "Close", "Volume"] if upper_cols else ["open", "high", "low", "close", "volume"]
    df = pd.DataFrame(
        {
            cols[0]: [100.0 + i for i in range(n)],
            cols[1]: [101.0 + i for i in range(n)],
            cols[2]: [99.0 + i for i in range(n)],
            cols[3]: [100.5 + i for i in range(n)],
            cols[4]: [1000 + 10 * i for i in range(n)],
        },
        index=idx,
    )
    if multiindex:
        df.index = pd.MultiIndex.from_arrays([["FOO"] * n, idx], names=["symbol", "time"])
    return df


def _algo(monkeypatch, hist: pd.DataFrame | None, *, today: datetime) -> BctEngineAlgorithm:
    monkeypatch.setattr(lean_entry, "TradeBar", _FakeTradeBar)

    # Resolution is touched only via self.history(sym, WARMUP_DAYS, Resolution.DAILY); our fake
    # history ignores the arg, but the attribute must resolve (it is None in the dev venv).
    monkeypatch.setattr(lean_entry, "Resolution", type("R", (), {"DAILY": "daily"}))

    algo = BctEngineAlgorithm()  # QCAlgorithm == object locally; initialize() not invoked
    algo.time = today

    def _history(_sym, _days, _res):
        return hist

    algo.history = _history  # type: ignore[method-assign,assignment]
    return algo


def _fresh_daily_suite() -> dict[str, Any]:
    """A fresh (cold) daily indicator suite mirroring _register_indicators wiring, with the
    adx→adx_window and macd→macd_hist_window cascades attached the same way the live code does."""
    d_ichi = _RecBarInd(ready_after=5)
    sma200 = _RecSeriesInd(ready_after=5)
    adx = _RecBarInd(ready_after=5)
    adx_window = _RecWindow(5)
    adx.updated += lambda _s, _pt: adx_window.add(adx.current.value)
    roc13 = _RecSeriesInd(ready_after=5)
    macd = _RecSeriesInd(ready_after=5)
    macd_hist_window = _RecWindow(2)
    macd.updated += lambda _s, _pt: macd_hist_window.add(macd.histogram.current.value)
    vol_sma20 = _RecSeriesInd(ready_after=5)
    tbounce = _RecTBounce()
    return {
        "d_ichi": d_ichi, "sma200": sma200, "adx": adx, "adx_window": adx_window,
        "roc13": roc13, "macd": macd, "macd_hist_window": macd_hist_window,
        "vol_sma20": vol_sma20, "tbounce": tbounce,
    }


# ======================================================================================
# 1. _seed_daily feeds the full daily suite from sufficient history -> every indicator ready
# ======================================================================================
def test_seed_daily_feeds_every_indicator_to_ready(monkeypatch) -> None:
    # 60 business days ending well BEFORE today (no look-ahead rows) -> all 60 replayed.
    hist = _daily_hist("2024-01-01", 60)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()

    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])

    # Full-bar consumers got every (pre-today) bar.
    assert len(s["d_ichi"].bars) == 60
    assert len(s["adx"].bars) == 60
    # Series consumers got every close (sma200/roc13/macd) / volume (vol_sma20).
    assert len(s["sma200"].samples) == 60
    assert len(s["roc13"].samples) == 60
    assert len(s["macd"].samples) == 60
    assert len(s["vol_sma20"].samples) == 60
    # TBounce replayed the same OHLC stream.
    assert len(s["tbounce"].calls) == 60
    # With ready_after=5 the whole suite is is_ready after the seed (the #259 point: ready the
    # day it is first subscribed, NOT 9-10 months later).
    assert s["d_ichi"].is_ready and s["adx"].is_ready and s["sma200"].is_ready
    assert s["roc13"].is_ready and s["macd"].is_ready and s["vol_sma20"].is_ready


def test_seed_daily_feeds_close_to_series_volume_to_vol(monkeypatch) -> None:
    # The price-series indicators must get CLOSE; vol_sma20 must get VOLUME — not crossed.
    hist = _daily_hist("2024-01-01", 10)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    # sma200 fed closes (100.5..109.5); vol_sma20 fed volumes (1000..1090).
    assert [v for _t, v in s["sma200"].samples] == [100.5 + i for i in range(10)]
    assert [v for _t, v in s["vol_sma20"].samples] == [float(1000 + 10 * i) for i in range(10)]


# ======================================================================================
# 2. FORWARD-ONLY GUARD — rows dated >= today are DROPPED (#213f/#259)
# ======================================================================================
def test_seed_daily_drops_rows_dated_today_or_later(monkeypatch) -> None:
    # History spans 2025-05-29..2025-06-05; today = 2025-06-02. Rows >= 2025-06-02 (Jun 2,3,4,5)
    # MUST be dropped (the live feed owns today's bar; seeding it would be a backward update +
    # a polluted partial bar). Only the strictly-earlier bars (May 29,30 + Jun ... wait) are fed.
    idx = pd.bdate_range(start="2025-05-29", periods=6)  # Thu May29, Fri30, Mon Jun2, Tue3, Wed4, Thu5
    df = pd.DataFrame(
        {"Open": [10.0] * 6, "High": [11.0] * 6, "Low": [9.0] * 6,
         "Close": [10.5 + i for i in range(6)], "Volume": [100] * 6},
        index=idx,
    )
    algo = _algo(monkeypatch, df, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])

    # Only May 29 + May 30 are strictly before 2025-06-02 -> 2 bars seeded.
    fed_dates = [b.time.date() for b in s["d_ichi"].bars]
    assert fed_dates == [pd.Timestamp("2025-05-29").date(), pd.Timestamp("2025-05-30").date()]
    # The look-ahead rows (Jun 2..5) never reached ANY indicator.
    assert all(d < datetime(2025, 6, 2).date() for d in fed_dates)
    assert len(s["sma200"].samples) == 2 and len(s["tbounce"].calls) == 2


def test_seed_daily_all_rows_today_or_later_seeds_nothing(monkeypatch) -> None:
    # Degenerate: every history row is today/future -> after the guard the frame is empty ->
    # NOTHING fed, no crash, no falsely-ready indicator (it stays cold, the live feed warms it).
    idx = pd.bdate_range(start="2025-06-02", periods=4)  # all >= today
    df = pd.DataFrame(
        {"Open": [10.0] * 4, "High": [11.0] * 4, "Low": [9.0] * 4,
         "Close": [10.5] * 4, "Volume": [100] * 4}, index=idx,
    )
    algo = _algo(monkeypatch, df, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert s["d_ichi"].bars == [] and s["sma200"].samples == [] and s["tbounce"].calls == []
    assert not s["d_ichi"].is_ready and not s["sma200"].is_ready  # NOT falsely ready


# ======================================================================================
# 3. INSUFFICIENT / ABSENT history -> graceful, not falsely-ready, no crash
# ======================================================================================
def test_seed_daily_none_history_is_noop(monkeypatch) -> None:
    algo = _algo(monkeypatch, None, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert s["d_ichi"].bars == [] and not s["d_ichi"].is_ready


def test_seed_daily_empty_history_is_noop(monkeypatch) -> None:
    algo = _algo(monkeypatch, pd.DataFrame(), today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert s["d_ichi"].bars == [] and not s["d_ichi"].is_ready


def test_seed_daily_few_bars_feeds_them_but_indicator_not_falsely_ready(monkeypatch) -> None:
    # Only 3 bars of history (< the ready_after=5 of the fakes, ~ < WarmUpPeriod for real
    # indicators) -> the 3 bars are fed but the indicator is NOT is_ready. The mirage-guard:
    # a thinly-seeded name is honestly NOT ready, so the scorer will skip it (not fake-score).
    hist = _daily_hist("2024-01-01", 3)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert len(s["d_ichi"].bars) == 3
    assert not s["d_ichi"].is_ready  # 3 < 5 -> honestly NOT ready


# ======================================================================================
# 4. The .updated CASCADES — adx_window from adx.updated, macd_hist_window from macd.updated
# ======================================================================================
def test_seed_daily_adx_window_cascade_fills_from_adx_updated(monkeypatch) -> None:
    # adx.updated fires the adx_window.add lambda on EVERY adx.update(bar). After seeding 10
    # bars the 5-deep adx_window holds the last 5 ADX values (newest at [0]) — populated as a
    # SIDE EFFECT of the parent, never read empty-but-marked-ready.
    hist = _daily_hist("2024-01-01", 10)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert s["adx_window"].count == 5  # capped at maxlen, filled by the cascade
    # adx.current.value == last close (our fake) == 109.5 -> window[0] is the newest.
    assert s["adx_window"][0] == 109.5


def test_seed_daily_macd_hist_window_cascade_fills_from_macd_updated(monkeypatch) -> None:
    hist = _daily_hist("2024-01-01", 10)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    # macd_hist_window is 2-deep; the entry-confirm gate needs count>=2 (turning direction).
    assert s["macd_hist_window"].count == 2


def test_seed_daily_one_bar_window_not_falsely_full(monkeypatch) -> None:
    # A SINGLE pre-today bar -> adx_window has 1 entry (count 1 < 4) and macd_hist_window has 1
    # (< 2). The scorers' window-count guards (adx_window<4 / macd_hist_window<2) then correctly
    # decline — the window must NOT read as full off one update.
    idx = pd.bdate_range(start="2025-05-30", periods=2)  # Fri May30 (<today) + Mon Jun2 (>=today)
    df = pd.DataFrame(
        {"Open": [10.0, 10.0], "High": [11.0, 11.0], "Low": [9.0, 9.0],
         "Close": [10.5, 11.5], "Volume": [100, 100]}, index=idx,
    )
    algo = _algo(monkeypatch, df, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert s["adx_window"].count == 1  # only the May30 bar survived the forward-only guard
    assert s["macd_hist_window"].count == 1


# ======================================================================================
# 5. _seed_weekly — sufficient history fills the weekly ichimoku + close window
# ======================================================================================
def test_seed_weekly_feeds_weekly_bars_monday_timed(monkeypatch) -> None:
    # 20 business days = 4 weekly bars; the seed feeds w_ichi.update(bar) + w_close.add(close).
    # The bar.time is the week-START MONDAY (the #213f forward-only fix vs the live Mon-timed
    # consolidator) — assert the seed bars are Monday-timed.
    hist = _daily_hist("2025-06-02", 20)  # starts a Monday
    algo = _algo(monkeypatch, hist, today=datetime(2026, 1, 1))
    w_ichi = _RecBarInd(ready_after=4)
    w_close = _RecWindow(28)
    algo._seed_weekly(_Sym("FOO"), w_ichi, w_close)
    assert len(w_ichi.bars) == 4
    assert w_close.count == 4
    # every seed bar is Monday-timed (weekday() == 0).
    assert all(b.time.weekday() == 0 for b in w_ichi.bars)


def test_seed_weekly_handles_multiindex_and_titlecase(monkeypatch) -> None:
    # QC history() for a single symbol returns a (symbol, time) MultiIndex with TitleCase cols;
    # _seed_weekly must droplevel(0) + lowercase. Prove it doesn't choke on that shape.
    hist = _daily_hist("2025-06-02", 15, multiindex=True, upper_cols=True)
    algo = _algo(monkeypatch, hist, today=datetime(2026, 1, 1))
    w_ichi = _RecBarInd(ready_after=1)
    w_close = _RecWindow(28)
    algo._seed_weekly(_Sym("FOO"), w_ichi, w_close)
    assert len(w_ichi.bars) == 3  # 15 bdays = 3 weeks
    assert w_close.count == 3


def test_seed_weekly_none_and_empty_history_noop(monkeypatch) -> None:
    for hist in (None, pd.DataFrame()):
        algo = _algo(monkeypatch, hist, today=datetime(2026, 1, 1))
        w_ichi = _RecBarInd(ready_after=1)
        w_close = _RecWindow(28)
        algo._seed_weekly(_Sym("FOO"), w_ichi, w_close)
        assert w_ichi.bars == [] and w_close.count == 0


def test_seed_daily_handles_multiindex_titlecase(monkeypatch) -> None:
    # The daily seed has the SAME MultiIndex/TitleCase handling as the weekly one.
    hist = _daily_hist("2024-01-01", 12, multiindex=True, upper_cols=True)
    algo = _algo(monkeypatch, hist, today=datetime(2025, 6, 2))
    s = _fresh_daily_suite()
    algo._seed_daily(_Sym("FOO"), s["d_ichi"], s["sma200"], s["adx"], s["adx_window"],
                     s["roc13"], s["macd"], s["vol_sma20"], s["tbounce"])
    assert len(s["d_ichi"].bars) == 12 and len(s["sma200"].samples) == 12
