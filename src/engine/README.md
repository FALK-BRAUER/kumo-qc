# src/engine/

Phase engine core — orchestration, context, and contracts.

- **What's here:** `base.py` (PhaseInterface Protocol + BasePhase + result types), `engine.py` (StrategyEngine with PHASE_ORDER scheduling), `context.py` (BarState, PhaseContext, OrderIntent dataclasses), `config.py` (StrategyConfig + Slot wiring), `logger.py` (ComponentLogger for JSON-lines telemetry).
- **What goes in:** Engine-level behavioral changes (scheduling order, init validation, fire sentinels), context dataclass evolution, config wiring patterns.
- **What does NOT go here:** Phase implementation logic (use `src/phases/<kind>/<impl>/`), strategy-specific configuration (use `src/strategies/`), backtest result analysis (use `research/`).
