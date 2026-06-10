"""Tests for the #451 realized giveback strategy candidate."""
from __future__ import annotations

from engine.engine import StrategyEngine, _config_hash
from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit
from strategies.champion_intraday_gapvol import CONFIG as CHAMPION_CONFIG
from strategies.realized_giveback_no_bull import CONFIG, LEAN_ENTRY
from strategies.realized_target_04_fast_take import CONFIG as TARGET_04_CONFIG
from strategies.realized_target_04_fast_take import LEAN_ENTRY as TARGET_04_LEAN_ENTRY
from strategies.realized_target_08_let_run import CONFIG as TARGET_08_CONFIG
from strategies.realized_target_08_let_run import LEAN_ENTRY as TARGET_08_LEAN_ENTRY


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


def test_engine_accepts_realized_giveback_no_bull() -> None:
    engine = StrategyEngine(config=CONFIG, qc=FakeQC())

    assert set(engine.phases) == {
        "universe",
        "signal",
        "regime",
        "ranking",
        "entry_selection",
        "arm",
        "entry_trigger",
        "intraday_sizing",
        "stops_initial",
        "trail",
        "exit_hard",
        "diagnostics",
    }
    assert CONFIG.is_fixture is False


def test_exit_params_match_giveback_tight_no_bull_sweep_variant() -> None:
    exit_slot = CONFIG.phases["exit_hard"][0]  # type: ignore[index]

    assert exit_slot.impl is ProactiveStrengthExit
    assert exit_slot.params == ProactiveStrengthExit.Params(
        target_pct=0.06,
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.015,
        require_still_bullish=False,
    )


def test_candidate_is_not_current_champion_or_fixture() -> None:
    assert _config_hash(CONFIG) != _config_hash(CHAMPION_CONFIG)
    assert CHAMPION_CONFIG.name == "champion-intraday-gapvol"
    assert CONFIG.name == "realized-giveback-no-bull"


def test_lean_entry_enabled() -> None:
    assert LEAN_ENTRY is True


def test_realized_target_candidates_are_non_fixture_strategy_modules() -> None:
    assert TARGET_04_CONFIG.is_fixture is False
    assert TARGET_08_CONFIG.is_fixture is False
    assert TARGET_04_CONFIG.name == "realized-target-04-fast-take"
    assert TARGET_08_CONFIG.name == "realized-target-08-let-run"
    assert TARGET_04_LEAN_ENTRY is True
    assert TARGET_08_LEAN_ENTRY is True
    assert len(
        {
            _config_hash(CHAMPION_CONFIG),
            _config_hash(CONFIG),
            _config_hash(TARGET_04_CONFIG),
            _config_hash(TARGET_08_CONFIG),
        }
    ) == 4


def test_realized_target_candidates_match_archived_exit_axis() -> None:
    target_04_exit = TARGET_04_CONFIG.phases["exit_hard"][0]  # type: ignore[index]
    target_08_exit = TARGET_08_CONFIG.phases["exit_hard"][0]  # type: ignore[index]

    assert target_04_exit.impl is ProactiveStrengthExit
    assert target_04_exit.params == ProactiveStrengthExit.Params(target_pct=0.04)
    assert target_08_exit.impl is ProactiveStrengthExit
    assert target_08_exit.params == ProactiveStrengthExit.Params(target_pct=0.08)
