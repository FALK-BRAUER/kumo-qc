"""Behavioral coverage for strategies._example — EXAMPLE_CONFIG liveness (#246).

The _example module proves the v2 wiring type-checks under mypy --strict. The REAL
behavioral question: does EXAMPLE_CONFIG actually instantiate in the engine? Do the stub
phases survive evaluate() on a minimal PhaseContext? These are the failures that matter
(import passes, engine init crashes, or evaluate() throws).
"""
from __future__ import annotations

from datetime import datetime

from engine.context import PhaseContext
from engine.engine import StrategyEngine
from strategies._example import (
    EXAMPLE_CONFIG,
    _ExampleFilter,
    _ExampleSignal,
    _ExampleSizing,
    _ExampleUniverse,
)


class FakeQC:
    """Minimal QC stand-in — engine init only needs Log/log."""

    def Log(self, _m: str) -> None: ...
    def log(self, _m: str) -> None: ...


def test_example_config_passes_engine_init() -> None:
    """Behavioral: EXAMPLE_CONFIG must survive StrategyEngine __init__ (all charter validations,
    dependency ordering, required-phase checks, single-adds check). This is the failure mode:
    mypy passes but engine rejects the config at runtime."""
    eng = StrategyEngine(config=EXAMPLE_CONFIG, qc=FakeQC())
    assert "filter" in eng.phases
    assert "universe" in eng.phases
    assert "signal" in eng.phases
    assert "sizing" in eng.phases


def test_stub_phases_evaluate_without_crash() -> None:
    """Behavioral: each stub phase's evaluate() must not raise on a minimal PhaseContext.
    This catches ctor/evaluate mismatch (e.g., evaluate() references a field the stub
    doesn't set, or expects qc.securities and gets None)."""
    ctx = PhaseContext(qc=object(), time=datetime(2025, 1, 2), data=None)
    # Unrolled to avoid mypy union-type narrowing in the loop variable.
    filter_inst = _ExampleFilter(_ExampleFilter.Params(), logger=None)
    assert filter_inst.evaluate(ctx).reason == "example"
    universe_inst = _ExampleUniverse(_ExampleUniverse.Params(), logger=None)
    assert universe_inst.evaluate(ctx).reason == "example"
    signal_inst = _ExampleSignal(_ExampleSignal.Params(), logger=None)
    assert signal_inst.evaluate(ctx).reason == "example"
    sizing_inst = _ExampleSizing(_ExampleSizing.Params(), logger=None)
    assert sizing_inst.evaluate(ctx).reason == "example"


def test_example_config_hash_is_stable() -> None:
    """Behavioral: the config hash must be deterministic (used for provenance tracking).
    Two identical configs -> same hash; required for sweep deduplication and bt-results.csv
    provenance matching."""
    from engine.engine import _config_hash
    h1 = _config_hash(EXAMPLE_CONFIG)
    h2 = _config_hash(EXAMPLE_CONFIG)
    assert h1 == h2
    assert len(h1) == 12
    int(h1, 16)  # valid hex


def test_example_stub_phase_kind_matches_catalog_expectation() -> None:
    """Behavioral: a sweep runner or engine init reads PHASE_KIND to schedule the phase.
    Mismatched kind = silent no-op or dependency failure."""
    assert _ExampleFilter.PHASE_KIND == "filter"
    assert _ExampleUniverse.PHASE_KIND == "universe"
    assert _ExampleSignal.PHASE_KIND == "signal"
    assert _ExampleSizing.PHASE_KIND == "sizing"
