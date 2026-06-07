import pytest

from engine.base import CharterViolation, ConfigError, DegradedConfigError, DependencyError
from engine.config import Slot, StrategyConfig
from engine.engine import StrategyEngine, validate_invariants
from tests.harness.stub_phases import slot


class FakeQC:
    def Log(self, msg: str) -> None: ...
    def log(self, msg: str) -> None: ...


# FORBIDDEN_PARAMS removed (Falk directive): the no-count-caps / no-time-exits rules are
# CONVENTIONS + code-review enforced, NOT a brittle engine param-name blocklist. The former
# test_forbidden_param_field_raises / test_forbidden_time_exit_param_raises /
# test_phase3_days_is_not_forbidden tested that removed scan — deleted with it. validate_invariants
# now only enforces the structural explicit-exposure invariant (adds → portfolio_risk).


def test_allowed_params_pass() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={"sizing": slot("sizing")})
    validate_invariants(cfg)  # must not raise


def test_adds_without_portfolio_risk_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "adds": slot("adds"),
    })
    with pytest.raises(CharterViolation, match="implicit exposure"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_adds_with_portfolio_risk_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"),
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "adds": slot("adds"), "portfolio_risk": slot("portfolio_risk"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_required_phase_missing_raises() -> None:
    # filter/universe/signal present, sizing omitted -> reports the missing 'sizing'.
    cfg = StrategyConfig(name="t", version="1.0.0", phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
    })
    with pytest.raises(ConfigError, match="sizing"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_filter_not_required_under_y() -> None:
    # Y (Falk): "filter" is NO LONGER a required phase — the champion applies its floors at the
    # selection gate (lean_entry._coarse_selection), not a per-bar filter phase. A config with
    # universe/signal/sizing and NO filter must be ACCEPTED. "filter" stays a known kind (in
    # PHASE_ORDER) so a future strategy MAY still add a real per-bar filter phase.
    # (is_fixture: this config has no entry/exit stack — it isolates the filter-not-required
    # check from the #272 fail-loud gate, which is tested separately below.)
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_single_adds_enforced() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"),
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "portfolio_risk": slot("portfolio_risk"),
        "adds": [slot("adds"), slot("adds")],
    })
    with pytest.raises(CharterViolation, match="mutually exclusive"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_unmet_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing", requires=("ranking",)),  # ranking not enabled
    })
    with pytest.raises(DependencyError, match="ranking"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_dependency_satisfied_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"), "universe": slot("universe"),
        "signal": slot("signal", requires=("universe",)),
        "sizing": slot("sizing", requires=("signal",)),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # filter<universe<signal<sizing, must not raise


def test_downstream_contract_dependency_satisfied_passes() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing"), "trail": slot("trail", provides=("position_path",)),
        "exit_hard": slot("exit_hard", requires=("position_path",)),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # trail provides position_path before exit_hard


def test_downstream_contract_dependency_missing_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing"), "exit_hard": slot("exit_hard", requires=("position_path",)),
    })
    with pytest.raises(DependencyError, match="position_path"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_downstream_contract_dependency_misordered_raises() -> None:
    cfg = StrategyConfig(name="t", version="1.0.0", is_fixture=True, phases={
        "filter": slot("filter"), "universe": slot("universe"), "signal": slot("signal"),
        "sizing": slot("sizing"), "exit_hard": slot("exit_hard", provides=("position_path",)),
        "trail": slot("trail", requires=("position_path",)),
    })
    with pytest.raises(DependencyError, match="not earlier"):
        StrategyEngine(config=cfg, qc=FakeQC())


# ── #272 fail-loud phase-stack gate: entry + exit REQUIRED for a champion (no implicit MOO) ──

def _champion_phases(**extra: object) -> dict[str, object]:
    """A base champion stack: universe/signal/sizing + entry-confirm + exit. Each test removes
    one to prove the gate fires, or keeps all to prove the healthy control passes (mutation-bite)."""
    p: dict[str, object] = {
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_timing": slot("entry_timing"), "exit_hard": slot("exit_hard"),
    }
    p.update(extra)
    return p


def test_champion_missing_entry_raises_degraded_config() -> None:
    # No entry_selection/entry_timing wired + NOT a fixture → the phantom blind-MOO model → RAISE.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "exit_hard": slot("exit_hard"),
    })
    with pytest.raises(DegradedConfigError, match="ENTRY-confirm"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_champion_missing_exit_raises_degraded_config() -> None:
    # Entry wired but NO exit phase + NOT a fixture → unprotected positions → RAISE.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_timing": slot("entry_timing"),
    })
    with pytest.raises(DegradedConfigError, match="EXIT phase"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_champion_missing_both_entry_and_exit_raises() -> None:
    # The champion_asis-class blind stack (signal→sizing→implicit-MOO) as a CHAMPION → RAISE.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    with pytest.raises(DegradedConfigError, match="ENTRY-confirm.*and.*EXIT phase"):
        StrategyEngine(config=cfg, qc=FakeQC())


def test_fixture_with_incomplete_stack_is_allowed() -> None:
    # The escape hatch: the SAME incomplete stack passes when explicitly declared a FIXTURE.
    cfg = StrategyConfig(name="fixture", version="1.0.0", is_fixture=True, phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_complete_champion_stack_passes() -> None:
    # MUTATION-BITE control: the full entry+exit champion stack (not a fixture) passes — proving
    # the gate accepts a valid champion, so the raise-tests above fail for the RIGHT reason.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases=_champion_phases())
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_entry_selection_alone_satisfies_entry_requirement() -> None:
    # entry_selection (not entry_timing) also satisfies the ENTRY family — control for the OR.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_selection": slot("entry_selection"), "exit_hard": slot("exit_hard"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise


def test_exit_target_satisfies_exit_requirement() -> None:
    # a non-exit_hard exit kind (exit_target) also satisfies the EXIT family — control for the OR.
    cfg = StrategyConfig(name="champ", version="1.0.0", phases={
        "universe": slot("universe"), "signal": slot("signal"), "sizing": slot("sizing"),
        "entry_timing": slot("entry_timing"), "exit_target": slot("exit_target"),
    })
    StrategyEngine(config=cfg, qc=FakeQC())  # must not raise
