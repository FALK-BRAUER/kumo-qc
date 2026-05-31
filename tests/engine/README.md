# tests/engine/

Engine-level behavioral and invariant tests.

- **What's here:** Tests for the phase engine (orchestration, init validation, per-bar scheduling, fire sentinels), context dataclasses (BarState, PhaseContext, OrderIntent), and base protocol contracts (PhaseInterface, BasePhase).
- **What goes in:** New tests when engine scheduling rules, dependency ordering, or fire-sentinel behavior changes.
- **What does NOT go here:** Phase-specific logic tests (those live in `tests/phases/<kind>/<impl>/`).
