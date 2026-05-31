"""Tests for the champion-entry strategy config (#253 Phase-1 entry-trigger measurement config).

champion-entry = champion-asis stack VERBATIM + entry_selection(BctEntryConfirm) +
entry_timing(MarketOnOpenEntry). Asserts the engine accepts it (all init validations pass),
the two new phases are wired in the right kinds, the champion-asis phases are unchanged, and
the config is distinct from champion-asis (its own config_hash).
"""
from __future__ import annotations

from engine.engine import StrategyEngine
from strategies.champion_asis import CONFIG as ASIS
from strategies.champion_entry import CONFIG, LEAN_ENTRY


class FakeQC:
    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...


def test_engine_accepts_champion_entry() -> None:
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "universe", "signal", "regime", "entry_selection", "entry_timing",
        "sizing", "exit_hard", "diagnostics",
    }


def test_entry_phases_wired() -> None:
    assert CONFIG.phases["entry_selection"].impl.__name__ == "BctEntryConfirm"   # type: ignore[union-attr]
    assert CONFIG.phases["entry_timing"].impl.__name__ == "MarketOnOpenEntry"    # type: ignore[union-attr]


def test_champion_asis_stack_unchanged() -> None:
    # Every shared kind matches champion-asis verbatim (the controlled-measurement invariant).
    for kind in ("universe", "signal", "sizing"):
        assert CONFIG.phases[kind].impl is ASIS.phases[kind].impl          # type: ignore[union-attr]
        assert CONFIG.phases[kind].params == ASIS.phases[kind].params      # type: ignore[union-attr]
    assert CONFIG.phases["signal"].params.min_score == 7                   # type: ignore[union-attr]


def test_lean_deployable() -> None:
    assert LEAN_ENTRY is True


def test_distinct_config_hash_from_asis() -> None:
    from engine.engine import _config_hash
    assert _config_hash(CONFIG) != _config_hash(ASIS)


def test_entry_selection_defaults_are_methodology_canonical() -> None:
    p = CONFIG.phases["entry_selection"].params  # type: ignore[union-attr]
    assert p.min_confirm == 2          # gate at >=2/4
    assert p.volume_gate_mult == 1.0   # the GATE (not the 1.5x full-size tier)
    assert (p.macd_fast, p.macd_slow, p.macd_signal) == (12, 26, 9)  # canonical MACD
