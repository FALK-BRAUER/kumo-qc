"""Tests for the champion-asis strategy config — the filter->rank+cap BCT wire.

Config-level: the engine accepts it (all init validations pass), the pipeline kinds are
present + correctly typed, and the config hash is stable. Phase LOGIC is tested in each
phase's own mirror; this asserts the WIRING.
"""
from __future__ import annotations

from engine.config import Slot
from engine.engine import StrategyEngine
from strategies.champion_asis import CONFIG


class FakeQC:
    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...


def test_engine_accepts_champion() -> None:
    # Instantiating runs every init validation (charter, known-kinds, required, deps,
    # single-adds). Must not raise.
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "filter", "universe", "signal", "regime", "sizing", "exit_hard", "diagnostics",
    }


def test_pipeline_wires_filter_then_universe_then_signal() -> None:
    # The decomposition contract: tradeability filter -> dv rank+cap -> bct selector.
    assert CONFIG.phases["filter"].impl.__name__ == "TradeabilityFloors"     # type: ignore[union-attr]
    assert CONFIG.phases["universe"].impl.__name__ == "DvRankCap"            # type: ignore[union-attr]
    assert CONFIG.phases["signal"].impl.__name__ == "BctScoreFull"          # type: ignore[union-attr]


def test_filter_floors_are_the_agreed_defaults() -> None:
    p = CONFIG.phases["filter"].params  # type: ignore[union-attr]
    assert p.min_price == 10.0
    assert p.min_avg_dollar_volume == 5_000_000.0
    assert p.adv_window == 20


def test_universe_is_unbounded_breadth_no_topn() -> None:
    p = CONFIG.phases["universe"].params  # type: ignore[union-attr]
    assert p.coarse_max == 9999  # unbounded baseline; no top-N artifact


def test_signal_selects_at_score_7() -> None:
    p = CONFIG.phases["signal"].params  # type: ignore[union-attr]
    assert p.min_score == 7


def test_regime_is_two_phases_spy_then_vix() -> None:
    regime = CONFIG.phases["regime"]
    assert isinstance(regime, list) and len(regime) == 2
    assert [s.impl.__name__ for s in regime] == ["SpySma200", "VixPercentile"]


def test_no_adds_phase_no_implicit_exposure() -> None:
    # champion-asis has no pyramid/adds → no gross_exposure_cap requirement triggered.
    assert "adds" not in CONFIG.phases
