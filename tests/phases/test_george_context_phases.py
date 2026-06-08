from __future__ import annotations

from datetime import datetime

from engine.context import BarState, OrderIntent, PhaseContext
from phases.ranking.george_industry_attention.george_industry_attention import GeorgeIndustryAttention
from phases.rebalance.industry_warmup.industry_warmup import IndustryWarmup


class Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Sym) and other.value == self.value


class Security:
    def __init__(self, price: float = 100.0, close: float | None = None) -> None:
        self.price = price
        self.close = price if close is None else close


class FakeQC:
    def __init__(self) -> None:
        self._active: set[Sym] = set()
        self.securities: dict[Sym, Security] = {}
        self._ranked_today: list[str] = []
        self._indicators: dict[Sym, dict[str, object]] = {}
        self._industry_by_ticker: dict[str, str] = {}
        self._ticker_context_features: dict[str, dict[str, object]] = {}
        self._industry_proxy_scores: dict[str, float] = {}
        self._george_attention_industry: dict[str, float] = {}
        self._george_attention_ticker: dict[str, float] = {}
        self._george_watchlist: dict[str, dict[str, object]] = {}


def ctx(qc: FakeQC, bar_state: BarState | None = None) -> PhaseContext:
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None, bar_state=bar_state or BarState())


def add_symbol(qc: FakeQC, ticker: str) -> None:
    sym = Sym(ticker)
    qc._active.add(sym)
    qc.securities[sym] = Security()


def intent(ticker: str) -> OrderIntent:
    return OrderIntent(ticker=ticker, qty=0, price=100.0, stop=0.0, module="signal", risk_dollars=0.0)


def test_industry_warmup_scores_synthetic_industries_and_proxies() -> None:
    qc = FakeQC()
    for ticker in ("ATI", "CRS", "CRM"):
        add_symbol(qc, ticker)
    qc._ranked_today = ["CRM", "ATI", "CRS"]
    qc._industry_by_ticker = {
        "ATI": "specialty_metals",
        "CRS": "specialty_metals",
        "CRM": "software",
    }
    qc._ticker_context_features = {
        "ATI": {"bct_score": 8, "above_cloud": True, "tk_bull": True, "dmi_bull": True, "roc13": 0.12},
        "CRS": {"bct_score": 7, "above_cloud": True, "tk_bull": True, "dmi_bull": True, "roc13": 0.08},
        "CRM": {"bct_score": 5, "above_cloud": False, "tk_bull": False, "dmi_bull": False, "roc13": -0.03},
    }
    qc._industry_proxy_scores = {"specialty_metals": 0.5}
    qc._george_attention_industry = {"specialty_metals": 1.0}

    phase = IndustryWarmup(IndustryWarmup.Params(top_n=2), logger=None)
    result = phase.evaluate(ctx(qc))

    assert result.facts["top_industries"][0] == "specialty_metals"
    assert qc._industry_context["specialty_metals"]["n_symbols"] == 2
    assert qc._industry_context["specialty_metals"]["bct_share"] == 1.0
    assert qc._industry_context["specialty_metals"]["score"] > qc._industry_context["software"]["score"]


def test_george_ranker_reorders_by_industry_attention_and_watchlist() -> None:
    qc = FakeQC()
    qc._industry_by_ticker = {
        "CRM": "software",
        "ATI": "specialty_metals",
        "CRS": "specialty_metals",
    }
    qc._industry_context = {
        "software": {"score": 0.2},
        "specialty_metals": {"score": 3.0},
    }
    qc._george_attention_ticker = {"CRS": 0.5}
    qc._george_watchlist = {"ATI": {"industry": "specialty_metals", "score": 1.5, "age_days": 2, "last_industry_score": 3.0}}
    bar = BarState(sized_orders=[intent("CRM"), intent("CRS"), intent("ATI")])

    phase = GeorgeIndustryAttention(GeorgeIndustryAttention.Params(), logger=None)
    result = phase.evaluate(ctx(qc, bar))

    assert [i.ticker for i in bar.sized_orders] == ["ATI", "CRS", "CRM"]
    assert result.facts["top"][:2] == ["ATI", "CRS"]
    assert qc._george_rank_features["ATI"]["watch_score"] == 1.5
    assert "CRS" in qc._george_watchlist


def test_george_ranker_removes_stale_watchlist_names() -> None:
    qc = FakeQC()
    qc._george_watchlist = {
        "OLD": {"industry": "software", "score": 1.0, "age_days": 20, "last_industry_score": 2.0},
        "WEAK": {"industry": "software", "score": 1.0, "age_days": 0, "last_industry_score": 0.1},
    }
    phase = GeorgeIndustryAttention(GeorgeIndustryAttention.Params(watchlist_ttl_days=10), logger=None)
    result = phase.evaluate(ctx(qc))

    assert result.facts["watchlist_size"] == 0
    assert qc._george_watchlist == {}
