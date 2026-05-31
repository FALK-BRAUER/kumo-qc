"""Behavioral coverage for strategies._build_sample — disabled-slot config validity (#246).

_build_sample.py carries a disabled regime slot (SampleOff, enabled=False). The REAL
behavioral question: does a config with an explicitly disabled slot still pass engine init
when the remaining required phases are present? Does the disabled slot's params exist
(for config-hash provenance) without being instantiated at runtime?
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from engine.engine import StrategyEngine
from strategies._build_sample import CONFIG as BUILD_SAMPLE_CONFIG
from strategies._example import EXAMPLE_CONFIG


class FakeQC:
    """Minimal QC stand-in."""

    def Log(self, _m: str) -> None: ...
    def log(self, _m: str) -> None: ...


def test_disabled_slot_params_exist_for_provenance() -> None:
    """Behavioral: the disabled slot's params dataclass must be accessible for config-hash
    computation (provenance tracking in bt-results.csv). If params were None, the hash
    would change non-deterministically."""
    regime_slot = BUILD_SAMPLE_CONFIG.phases["regime"]
    assert isinstance(regime_slot, Slot)
    assert regime_slot.enabled is False
    assert regime_slot.params is not None


def test_disabled_slot_not_in_runtime_phases() -> None:
    """Behavioral: a complete config (EXAMPLE_CONFIG) with an added disabled slot must pass
    engine init, and the disabled phase must NOT appear in the runtime phase list."""
    # Merge _build_sample's disabled regime into the complete _example config.
    merged_phases = dict(EXAMPLE_CONFIG.phases)
    merged_phases["regime"] = BUILD_SAMPLE_CONFIG.phases["regime"]
    merged = StrategyConfig(
        name="_test_disabled",
        version="0.0.0",
        phases=merged_phases,
    )
    eng = StrategyEngine(config=merged, qc=FakeQC())
    assert "regime" not in eng.phases, "disabled slot must not be instantiated"


def test_enabled_slot_in_build_sample_is_instantiable() -> None:
    """Behavioral: the enabled slot (SampleBct) must be constructible and conform to
    PhaseInterface. The engine's _instantiate() must succeed for enabled slots."""
    from engine.base import PhaseInterface
    signal_value = BUILD_SAMPLE_CONFIG.phases["signal"]
    assert isinstance(signal_value, Slot), "signal must be a single Slot, not a list"
    inst = signal_value.impl(signal_value.params, logger=None)
    assert isinstance(inst, PhaseInterface)
    assert inst.enabled is True
