import pytest
from engine.engine import validate_invariants
from engine.base import CharterViolation


def cfg_with_param(kind: str, param: str, value):
    return {
        "name": "t", "version": "1.0.0",
        "phases": {kind: {"module": "stub", "enabled": True, "params": {param: value}}},
        "invariants": {},
    }


@pytest.mark.parametrize("param", [
    # count caps
    "max_positions", "max_lots", "max_entries_per_day",
    "max_adds", "max_pyramid_lots", "max_position_adds",
    "max_concurrent_positions", "position_limit", "max_slots",
    # time-based exits
    "max_hold_days", "exit_if_flat_after_days",
    "max_days_held", "max_bars_held", "time_stop_days",
    "exit_after_days", "holding_period_limit",
])
def test_forbidden_param_raises_charter_violation(param):
    with pytest.raises(CharterViolation, match=param):
        validate_invariants(cfg_with_param("sizing", param, 5))


def test_allowed_params_pass():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "sizing": {"module": "stub", "enabled": True, "params": {"risk_dollars": 500}},
            "adds": {"module": "stub", "enabled": True, "params": {"lot_size_dollars": 200}},
        },
        "invariants": {},
    }
    validate_invariants(config)  # must not raise


def test_forbidden_param_in_list_phase_raises():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "regime": [{"module": "stub", "enabled": True, "params": {"max_positions": 5}}],
        },
        "invariants": {},
    }
    with pytest.raises(CharterViolation, match="max_positions"):
        validate_invariants(config)


# C1: explicit-exposure invariant — adds require portfolio_risk
def test_adds_without_portfolio_risk_raises():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "adds": {"module": "phases.adds.pe", "enabled": True, "params": {}},
        },
        "invariants": {},
    }
    with pytest.raises(CharterViolation, match="implicit exposure"):
        validate_invariants(config)


def test_adds_with_portfolio_risk_passes():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "adds": {"module": "phases.adds.pe", "enabled": True, "params": {}},
            "portfolio_risk": {"module": "phases.portfolio_risk.gross_cap", "enabled": True, "params": {"max_pct": 100}},
        },
        "invariants": {},
    }
    validate_invariants(config)  # must not raise


def test_adds_disabled_no_portfolio_risk_passes():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "adds": {"module": "phases.adds.pe", "enabled": False, "params": {}},
        },
        "invariants": {},
    }
    validate_invariants(config)  # disabled adds → no requirement
