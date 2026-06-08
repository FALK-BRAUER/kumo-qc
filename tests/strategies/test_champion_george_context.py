from __future__ import annotations

from engine.engine import StrategyEngine
from strategies.champion_intraday_gapvol import CONFIG as INTRADAY_GAPVOL
from strategies.champion_george_context import CONFIG, LEAN_ENTRY


class FakeQC:
    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...


def test_engine_accepts_champion_george_context() -> None:
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "rebalance", "universe", "signal", "regime", "ranking",
        "entry_selection", "entry_timing", "sizing", "exit_hard", "protective_stop",
        "diagnostics",
    }


def test_context_phases_are_the_only_added_shared_delta() -> None:
    for kind in (
        "universe", "signal", "regime", "entry_selection", "entry_timing", "sizing",
        "exit_hard", "protective_stop", "diagnostics",
    ):
        actual = CONFIG.phases[kind]
        expected = INTRADAY_GAPVOL.phases[kind]
        if isinstance(actual, list):
            assert isinstance(expected, list)
            assert [(s.impl, s.params) for s in actual] == [(s.impl, s.params) for s in expected]
        else:
            assert not isinstance(expected, list)
            assert actual.impl is expected.impl
            assert actual.params == expected.params
    assert CONFIG.phases["rebalance"].impl.__name__ == "IndustryWarmup"  # type: ignore[union-attr]
    assert CONFIG.phases["ranking"].impl.__name__ == "GeorgeIndustryAttention"  # type: ignore[union-attr]
    assert CONFIG.continuous_weekly is True


def test_lean_deployable() -> None:
    assert LEAN_ENTRY is True
