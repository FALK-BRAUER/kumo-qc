"""Tests for the opt-in BCT George-alignment strategy config."""
from __future__ import annotations

from engine.config import Slot
from engine.engine import StrategyEngine, _config_hash
from phases.ranking.george_style_ranking.george_style_ranking import GeorgeStyleRanking
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from strategies import CHAMPION
from strategies.bct_george_alignment import CONFIG, LEAN_ENTRY
from strategies.bct_george_alignment_score6 import CONFIG as SCORE6_CONFIG
from strategies.bct_george_alignment_score6 import LEAN_ENTRY as SCORE6_LEAN_ENTRY
from strategies.champion_intraday_gapvol import CONFIG as CHAMPION_CONFIG


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


def _slots(value: Slot[object] | list[Slot[object]]) -> list[Slot[object]]:
    return value if isinstance(value, list) else [value]


def test_engine_accepts_bct_george_alignment_config() -> None:
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "universe", "signal", "regime", "ranking", "entry_selection", "entry_timing",
        "sizing", "protective_stop", "exit_hard", "diagnostics",
    }


def test_engine_accepts_score6_alignment_config() -> None:
    eng = StrategyEngine(config=SCORE6_CONFIG, qc=FakeQC())
    assert "ranking" in eng.phases
    assert "signal" in eng.phases


def test_only_strategy_stack_delta_from_champion_is_ranking() -> None:
    for kind, champion_value in CHAMPION_CONFIG.phases.items():
        if kind == "ranking":
            continue
        alignment_value = CONFIG.phases[kind]
        champion_slots = _slots(champion_value)
        alignment_slots = _slots(alignment_value)
        assert [slot.impl for slot in alignment_slots] == [slot.impl for slot in champion_slots]
        assert [slot.params for slot in alignment_slots] == [slot.params for slot in champion_slots]

    ranking = CONFIG.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl is GeorgeStyleRanking


def test_score6_alignment_only_changes_signal_threshold_from_score7_config() -> None:
    for kind, score7_value in CONFIG.phases.items():
        if kind == "signal":
            continue
        score6_value = SCORE6_CONFIG.phases[kind]
        score7_slots = _slots(score7_value)
        score6_slots = _slots(score6_value)
        assert [slot.impl for slot in score6_slots] == [slot.impl for slot in score7_slots]
        assert [slot.params for slot in score6_slots] == [slot.params for slot in score7_slots]

    signal = SCORE6_CONFIG.phases["signal"]
    assert not isinstance(signal, list)
    assert signal.impl is BctScoreFull
    assert signal.params == BctScoreFull.Params(min_score=6, parabolic_threshold=0.25)


def test_active_champion_is_unchanged() -> None:
    assert CHAMPION == "strategies.champion_intraday_gapvol"


def test_config_hash_differs_from_champion() -> None:
    assert _config_hash(CONFIG) != _config_hash(CHAMPION_CONFIG)
    assert _config_hash(SCORE6_CONFIG) != _config_hash(CHAMPION_CONFIG)
    assert _config_hash(SCORE6_CONFIG) != _config_hash(CONFIG)


def test_lean_entry_enabled() -> None:
    assert LEAN_ENTRY is True
    assert SCORE6_LEAN_ENTRY is True
