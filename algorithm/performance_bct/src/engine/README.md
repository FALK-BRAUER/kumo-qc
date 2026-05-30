# engine/

Phase-based strategy engine for kumo-qc.

## What this is
Runs a `STRATEGY_CONFIG` dict through a canonical `PHASE_ORDER` each bar. Phases emit intents into `BarState`; the engine fires orders at `FIRE_*` sentinel boundaries. Charter invariants enforced at init (no count caps, no time exits, explicit exposure).

## Key files
- `base.py` — `PhaseInterface` ABC, `PhaseResult`, `CharterViolation`, `UniverseLoadError`
- `context.py` — `PhaseContext` (LEAN refs + fresh `BarState` per bar), `OrderIntent`, `BlockEvent`
- `engine.py` — `StrategyEngine`, `PHASE_ORDER`, `FIRE_*` sentinels, `validate_invariants()`
- `logger.py` — `ComponentLogger` (PHASE/BLOCK/TICK/INIT log lines)

## Block semantics
Block set = `{regime, cash}`. A blocked bar does NOT hard-return — it sets `bar_blocked=True` and continues iterating, skipping non-tail phases. `diagnostics` and `circuit_breaker` always run (always-run tail).

## What goes here
Engine core only. No phase implementations. No LEAN-specific logic beyond the `qc` ref on `PhaseContext`. `_fire()` is a stub — LEAN order submission wires in ARCH-C.

## What doesn't go here
Phase implementations (`phases/<kind>/<impl>/`). Test harness (`tests/harness/`). Cloud packaging (`build/`).

## Tests
```bash
cd algorithm/performance_bct/src
.venv/bin/python -m pytest -v
```
