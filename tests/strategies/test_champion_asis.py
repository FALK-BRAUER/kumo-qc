"""Tests for the champion-asis strategy config — the selection-gate BCT wire (Y, Falk).

Config-level: the engine accepts it (all init validations pass — required phases are now
universe/signal/sizing; NO per-bar filter phase under Y), the pipeline kinds are present +
correctly typed, and the config hash is stable. Phase LOGIC is tested in each phase's own
mirror; the floor knobs live on the lean_entry class (test_lean_entry); this asserts the WIRING.
"""
from __future__ import annotations

from engine.engine import StrategyEngine
from strategies.champion_asis import CONFIG


class FakeQC:
    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...


def test_engine_accepts_champion() -> None:
    # Instantiating runs every init validation (charter, known-kinds, required, deps,
    # single-adds). Must not raise. NO "filter" kind under Y (floors at the selection gate).
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "universe", "signal", "regime", "sizing", "exit_hard", "diagnostics",
    }


def test_no_filter_phase_floors_at_selection_gate() -> None:
    # Y (Falk): the per-bar filter phase is dropped — the floors are applied at the selection
    # gate (lean_entry._coarse_selection). The config carries no "filter" kind.
    assert "filter" not in CONFIG.phases


def test_pipeline_wires_universe_then_signal() -> None:
    # The decomposition contract: dv rank+cap exposer -> bct selector.
    assert CONFIG.phases["universe"].impl.__name__ == "DvRankCap"            # type: ignore[union-attr]
    assert CONFIG.phases["signal"].impl.__name__ == "BctScoreFull"          # type: ignore[union-attr]


def test_universe_phase_carries_no_cap_param() -> None:
    # The cap (coarse_max scan-breadth) lives at the selection gate (lean_entry.COARSE_MAX,
    # single source); the universe phase exposes the already-capped live order and carries no
    # cap param of its own.
    p = CONFIG.phases["universe"].params  # type: ignore[union-attr]
    assert not hasattr(p, "coarse_max")


def test_signal_selects_at_score_7() -> None:
    p = CONFIG.phases["signal"].params  # type: ignore[union-attr]
    assert p.min_score == 7


def test_diagnostics_is_two_phases_version_marker_then_chart_emit() -> None:
    # #243: diagnostics is a list-kind; chart_emit joins version_marker (engine keys by
    # (kind, module) so two diagnostics sub-phases coexist). The engine still accepts it
    # (test_engine_accepts_champion instantiates without raising).
    diagnostics = CONFIG.phases["diagnostics"]
    assert isinstance(diagnostics, list) and len(diagnostics) == 2
    assert [s.impl.__name__ for s in diagnostics] == ["VersionMarker", "ChartEmit"]


def test_regime_is_two_phases_spy_then_vix() -> None:
    regime = CONFIG.phases["regime"]
    assert isinstance(regime, list) and len(regime) == 2
    assert [s.impl.__name__ for s in regime] == ["SpySma200", "VixPercentile"]


def test_no_adds_phase_no_implicit_exposure() -> None:
    # champion-asis has no pyramid/adds → no gross_exposure_cap requirement triggered.
    assert "adds" not in CONFIG.phases
