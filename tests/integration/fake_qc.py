"""Realistic FakeQC for the #247 E2E lifecycle integration test.

This is NOT the minimal stub the engine unit tests use (tests/harness/stub_phases.py
drive STUB phases). This harness drives the REAL champion_asis phases, so the FakeQC must
faithfully supply everything the real phases read off `qc` / `bar_state`:

  universe (dv_rank_cap)      -> qc._ranked_today, qc._active (Symbol.value), qc.log
  signal (bct_score_full)     -> qc._active, qc.portfolio[sym].invested,
                                 qc.transactions.get_open_orders(sym), qc._indicators[sym]
                                 (d_ichi/w_ichi/w_close/sma200/adx/adx_window/roc13 — the
                                 exact QC accessors score_symbol_native reads),
                                 qc.securities[sym].price, qc._trailing_dv
  regime/spy_200ma            -> qc.spy, qc.spy_sma200 (.is_ready/.current.value),
                                 qc.securities[spy].price
  regime/vix_percentile       -> DISABLED in CONFIG (early skip) — no fidelity needed
  sizing (flat_pct_heatcap)   -> qc.portfolio.cash, qc.portfolio.total_portfolio_value,
                                 qc.securities[sym].price
  exit (kijun_g3_exits)       -> qc.portfolio.items() (invested holdings), qc.securities[sym]
                                 .close, d_ichi.kijun/senkou_a/senkou_b, qc._position_meta
  diagnostics (version_marker,
   chart_emit)                -> qc.log, qc.plot, qc._ranked_today, bar_state
  engine._fire                -> qc.market_on_open_order(sym, qty), qc.securities[sym].price,
                                 qc._position_meta
  ComponentLogger             -> qc.Log

The indicator fakes mirror tests/phases/shared/test_score_symbol_native.py exactly (the
QC-native accessor shapes: .current.value / .is_ready / .positive_directional_index /
RollingWindow[i] + .count) so score_symbol_native runs verbatim.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Maintained-indicator fakes — exact QC accessor shapes (mirror test_score_symbol_native)
# ---------------------------------------------------------------------------


class _Cur:
    def __init__(self, v: float) -> None:
        self.value = v


class _Ind:
    """A maintained scalar indicator: .current.value + .is_ready (e.g. SMA200, ROC)."""

    def __init__(self, v: float, ready: bool = True) -> None:
        self.current = _Cur(v)
        self.is_ready = ready


class _Ichi:
    """IchimokuKinkoHyo-shape: tenkan/kijun/senkou_a/senkou_b each a _Ind, + .is_ready."""

    def __init__(self, tenkan: float, kijun: float, sa: float, sb: float, ready: bool = True) -> None:
        self.tenkan = _Ind(tenkan)
        self.kijun = _Ind(kijun)
        self.senkou_a = _Ind(sa)
        self.senkou_b = _Ind(sb)
        self.is_ready = ready


class _Adx:
    """ADX-shape: .current.value + .positive/negative_directional_index + .is_ready."""

    def __init__(self, adx: float, pdi: float, ndi: float, ready: bool = True) -> None:
        self.current = _Cur(adx)
        self.positive_directional_index = _Ind(pdi)
        self.negative_directional_index = _Ind(ndi)
        self.is_ready = ready


class _Window:
    """RollingWindow-shape: [i] (0=most-recent) + .count."""

    def __init__(self, vals: list[float]) -> None:
        self._v = vals

    def __getitem__(self, i: int) -> float:
        return self._v[i]

    @property
    def count(self) -> int:
        return len(self._v)


def all_pass_indicators() -> dict[str, Any]:
    """An 8/8-passing maintained indicator set at a reference price of 100.

    Identical value layout to test_score_symbol_native._ind (the golden set): every BCT
    condition passes when the LIVE price is 100. score_symbol_native therefore returns
    score=8, and the pre-filter (price>=sma200, price>=daily-cloud-top) passes.
    """
    return {
        "d_ichi": _Ichi(tenkan=90.0, kijun=88.0, sa=85.0, sb=80.0),
        "w_ichi": _Ichi(tenkan=70.0, kijun=60.0, sa=75.0, sb=65.0),
        "w_close": _Window([90.0] + [50.0] * 26),
        "sma200": _Ind(50.0),
        "adx": _Adx(adx=25.0, pdi=30.0, ndi=10.0),
        "adx_window": _Window([25.0, 24.0, 23.0, 22.0]),
        "roc13": _Ind(0.10),
        # #253 entry_selection (BctEntryConfirm §4 Gate 2) — ADDITIVE; an ENTRY-CONFIRMING set at
        # price 100: C1 regime (price>cloud-top 85 AND tenkan 90>kijun 88), C2 T-Bounce (price
        # within 0.5% of tenkan? tenkan 90 -> NOT near; this set confirms C1/C3/C4 = 3/4 with
        # regime+volume mandatory -> qualifies). MACD positive+turning-up (C3); vol 200k>=1.0x
        # avg 100k (C4); tbounce clean (0 sessions below, no gap). The signal/exit phases ignore
        # these keys (champion-asis behavior unchanged).
        "macd": _Ind(0.5),  # is_ready proxy (only .is_ready is read for macd)
        "macd_hist_window": _Window([0.5, 0.2]),  # positive, turning up
        "vol_sma20": _Ind(100_000.0),
        "tbounce": _TBounce(sessions=0, gap=0.0),
        "daily_consolidator": object(),
    }


class _TBounce:
    """TBounceTracker-shape: the C2 degrade state the entry phase reads (sessions + gap)."""

    def __init__(self, sessions: int = 0, gap: float = 0.0) -> None:
        self.sessions_below_tenkan = sessions
        self.gap_up_frac = gap


def below_sma200_indicators() -> dict[str, Any]:
    """A declined-by-pre-filter set: sma200 ABOVE the reference price (120 > 100).

    THE DECLINE MECHANISM IS THE PRE-FILTER, NOT A LOW SCORE. The signal pre-filter
    (bct_score_full, `if price < sma200_ind.current.value: continue`) drops this ticker
    BEFORE score_symbol_native ever runs, because the LIVE price (100) is below sma200 (120).

    NOTE — do NOT assume "score <= 6": if this set DID reach the scorer it would score 7,
    not 6. score_symbol_native uses the LIVE price only for conditions 1/5/6/8; only
    condition 8 (price > ma200) fails here, while the daily/weekly cloud conditions still
    pass off the all_pass structure → 7/8 >= min_score 7. The decline-arm therefore relies
    entirely on the price-gate pre-filter catching it first. Lowering sma200 below the live
    price (or removing the pre-filter) would let this ticker FIRE and break the entry-funnel
    assertion — the price-gate is the load-bearing reason it declines, not the score.
    """
    ind = all_pass_indicators()
    ind["sma200"] = _Ind(120.0)
    return ind


# ---------------------------------------------------------------------------
# Portfolio / securities / transactions fakes
# ---------------------------------------------------------------------------


class FakeSecurity:
    """A subscribed security. The phases read DIFFERENT fields:
      - signal / sizing / engine._fire read `.price` (live)
      - exit (kijun_g3_exits) reads `.close`
    Both are settable independently so the exit bar can breach the Kijun on `.close`
    without disturbing the entry-side `.price` reads.
    """

    def __init__(self, price: float, close: float | None = None, volume: float = 200_000.0) -> None:
        self.price = price
        self.close = close if close is not None else price
        # #253: the entry_selection phase (C4 volume) reads `.volume`. Default 200k clears the
        # 1.0x gate vs the all_pass vol_sma20 (100k); existing tests ignore it.
        self.volume = volume


class FakeHolding:
    def __init__(self, invested: bool = False, quantity: int = 0) -> None:
        self.invested = invested
        self.quantity = quantity


class FakePortfolio:
    """dict-like Portfolio: [sym] -> FakeHolding (uninvested default for unknown syms),
    .items() over the KNOWN holdings only (what the exit phase iterates), plus the
    scalar .cash / .total_portfolio_value the sizing phase reads."""

    def __init__(self, cash: float, total_value: float) -> None:
        self.cash = cash
        self.total_portfolio_value = total_value
        self._holdings: dict[Any, FakeHolding] = {}

    def __getitem__(self, sym: Any) -> FakeHolding:
        return self._holdings.setdefault(sym, FakeHolding())

    def __setitem__(self, sym: Any, holding: FakeHolding) -> None:
        self._holdings[sym] = holding

    def items(self) -> Any:
        return list(self._holdings.items())


class FakeTransactions:
    """No open orders in this scenario (the entry/exit fire in one shot per bar)."""

    def get_open_orders(self, symbol: Any = None) -> list[Any]:
        return []


class FakeSymbol:
    """QC Symbol-like: .value (canonical uppercase ticker), hashable by value."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FakeSymbol) and self.value == other.value

    def __repr__(self) -> str:
        return f"FakeSymbol({self.value!r})"


class FakeSecuritiesMap(dict):  # type: ignore[type-arg]
    """qc.securities — dict + .contains_key (vix_percentile reads it; here it's disabled)."""

    def contains_key(self, key: Any) -> bool:
        return key in self


class FakeQC:
    """The realistic FakeQC. One instance per scenario; per-bar state (prices, ranked set,
    regime) is mutated between engine ticks to drive entry → exit → blocked."""

    def __init__(self, cash: float, total_value: float) -> None:
        # universe / signal runtime state
        self._ranked_today: list[str] | None = []
        self._trailing_dv: dict[str, float] = {}
        self._active: set[FakeSymbol] = set()
        self._indicators: dict[FakeSymbol, dict[str, Any]] = {}
        self._position_meta: dict[Any, Any] = {}

        # portfolio / market
        self.portfolio = FakePortfolio(cash=cash, total_value=total_value)
        self.securities = FakeSecuritiesMap()
        self.transactions = FakeTransactions()

        # regime
        self.spy: FakeSymbol | None = None
        self.spy_sma200: _Ind | None = None
        self.vix: FakeSymbol | None = None  # vix_percentile is disabled → never read

        # capture sinks
        self.orders: list[tuple[Any, int]] = []
        self.logged: list[str] = []
        self.plots: list[tuple[str, str, float]] = []

    # ---- order API (engine._fire) ----
    def market_on_open_order(self, symbol: Any, qty: int) -> None:
        self.orders.append((symbol, qty))

    # ---- logging ----
    def Log(self, msg: str) -> None:  # ComponentLogger
        self.logged.append(msg)

    def log(self, msg: str) -> None:  # phases call qc.log
        self.logged.append(msg)

    # ---- charting (chart_emit) ----
    def plot(self, chart: str, series: str, value: float) -> None:
        self.plots.append((chart, series, value))

    # ---- test helpers ----
    def add_security(self, ticker: str, price: float, indicators: dict[str, Any]) -> FakeSymbol:
        sym = FakeSymbol(ticker)
        self._active.add(sym)
        self.securities[sym] = FakeSecurity(price)
        self._indicators[sym] = indicators
        return sym

    def symbol(self, ticker: str) -> FakeSymbol:
        for s in self._active:
            if s.value == ticker:
                return s
        raise KeyError(ticker)
