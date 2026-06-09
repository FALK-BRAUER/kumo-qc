"""GeorgeStyleRanking: QC-safe chart-curation ordering for qualified BCT candidates."""
from __future__ import annotations

from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.ranking.george_style_ranking.george_style_ranking import GeorgeStyleRanking


class _Current:
    def __init__(self, value: float) -> None:
        self.value = value


class _Line:
    def __init__(self, value: float) -> None:
        self.current = _Current(value)


class _Ichi:
    def __init__(
        self,
        tenkan: float,
        kijun: float,
        senkou_a: float,
        senkou_b: float,
        *,
        ready: bool = True,
    ) -> None:
        self.tenkan = _Line(tenkan)
        self.kijun = _Line(kijun)
        self.senkou_a = _Line(senkou_a)
        self.senkou_b = _Line(senkou_b)
        self.is_ready = ready


class _Adx:
    def __init__(self, value: float, *, ready: bool = True) -> None:
        self.current = _Current(value)
        self.is_ready = ready


class _Roc:
    def __init__(self, value: float, *, ready: bool = True) -> None:
        self.current = _Current(value)
        self.is_ready = ready


class _TBounce:
    def __init__(
        self,
        *,
        open_: float = 101.0,
        high: float = 106.0,
        low: float = 99.5,
        close: float = 104.0,
        rel_volume20: float | None = 1.3,
        prior_high20: float | None = 100.0,
        prior_high50: float | None = None,
        prior_high252: float | None = None,
    ) -> None:
        self.last_open = open_
        self.last_high = high
        self.last_low = low
        self.last_close = close
        self.rel_volume20 = rel_volume20
        self.prior_high20 = prior_high20
        self.prior_high50 = prior_high50
        self.prior_high252 = prior_high252


class _Security:
    def __init__(self, price: float) -> None:
        self.price = price


class _QC:
    def __init__(self) -> None:
        self._active: set[str] = set()
        self._signal_features: dict[str, dict[str, int]] = {}
        self._trailing_dv: dict[str, float] = {}
        self._indicators: dict[str, dict[str, object]] = {}
        self.securities: dict[str, _Security] = {}
        self._george_style_score: dict[str, float] = {}


def _intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="signal", risk_dollars=0.0)


def _run(qc: _QC, tickers: list[str]) -> list[str]:
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    ctx.bar_state.sized_orders = [_intent(t) for t in tickers]
    GeorgeStyleRanking(GeorgeStyleRanking.Params(), logger=None).evaluate(ctx)
    return [o.ticker for o in ctx.bar_state.sized_orders]


def _add_candidate(
    qc: _QC,
    ticker: str,
    *,
    price: float = 104.0,
    score: int = 7,
    dv: float = 100_000_000.0,
    tenkan: float | None = 101.0,
    kijun: float | None = 96.0,
    cloud_top: float | None = 95.0,
    tbounce: _TBounce | None = None,
    adx: float | None = 28.0,
    roc13: float | None = 0.05,
) -> None:
    qc._active.add(ticker)
    qc._signal_features[ticker] = {"score": score}
    qc._trailing_dv[ticker] = dv
    qc.securities[ticker] = _Security(price)
    indicators: dict[str, object] = {}
    if tenkan is not None and kijun is not None and cloud_top is not None:
        indicators["d_ichi"] = _Ichi(tenkan, kijun, cloud_top, cloud_top - 2.0)
    if tbounce is not None:
        indicators["tbounce"] = tbounce
    if adx is not None:
        indicators["adx"] = _Adx(adx)
    if roc13 is not None:
        indicators["roc13"] = _Roc(roc13)
    qc._indicators[ticker] = indicators


def test_phase_prefers_constructive_retest_over_extended_chase() -> None:
    qc = _QC()
    _add_candidate(
        qc,
        "CALM",
        tbounce=_TBounce(open_=101.0, high=106.0, low=99.5, close=104.0, prior_high20=100.0),
        tenkan=101.0,
        kijun=96.0,
        cloud_top=95.0,
        roc13=0.05,
    )
    _add_candidate(
        qc,
        "CHASE",
        tbounce=_TBounce(open_=112.0, high=118.0, low=111.0, close=116.0, prior_high20=100.0),
        tenkan=100.0,
        kijun=92.0,
        cloud_top=91.0,
        roc13=0.30,
    )

    assert _run(qc, ["CHASE", "CALM"]) == ["CALM", "CHASE"]


def test_research_override_map_is_ignored() -> None:
    qc = _QC()
    qc._george_style_score = {"BAD": 1000.0, "GOOD": 0.0}
    _add_candidate(
        qc,
        "GOOD",
        tbounce=_TBounce(open_=101.0, high=106.0, low=99.5, close=104.0, prior_high20=100.0),
    )
    _add_candidate(
        qc,
        "BAD",
        tbounce=_TBounce(open_=100.0, high=112.0, low=98.0, close=99.0, prior_high20=110.0),
        tenkan=96.0,
        kijun=94.0,
        cloud_top=93.0,
    )

    assert _run(qc, ["BAD", "GOOD"]) == ["GOOD", "BAD"]


def test_tie_breaks_by_dollar_volume_then_ticker() -> None:
    qc = _QC()
    _add_candidate(qc, "AAA", dv=20_000_000.0, tbounce=None)
    _add_candidate(qc, "BBB", dv=50_000_000.0, tbounce=None)
    _add_candidate(qc, "CCC", dv=50_000_000.0, tbounce=None)

    assert _run(qc, ["CCC", "AAA", "BBB"]) == ["BBB", "CCC", "AAA"]


def test_missing_indicator_context_does_not_crash_and_is_penalized() -> None:
    qc = _QC()
    _add_candidate(
        qc,
        "FULL",
        tbounce=_TBounce(open_=101.0, high=106.0, low=99.5, close=104.0, prior_high20=100.0),
    )
    _add_candidate(qc, "COLD", tenkan=None, kijun=None, cloud_top=None, tbounce=None, adx=None, roc13=None)

    assert _run(qc, ["COLD", "FULL"]) == ["FULL", "COLD"]


def test_version_marker_names_qc_safe_phase() -> None:
    phase = GeorgeStyleRanking(GeorgeStyleRanking.Params(), logger=None)
    assert phase.version_marker == "george_style_ranking_v1"
