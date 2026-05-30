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
    "max_positions",
    "max_lots",
    "max_entries_per_day",
    "max_hold_days",
    "exit_if_flat_after_days",
    "max_adds",
    "max_pyramid_lots",
    "max_position_adds",
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
