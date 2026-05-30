# src/engine/

The engine core — always packaged into `dist/`, strategy-agnostic.

- **Holds:** `engine.py` (StrategyEngine, PHASE_ORDER, FIRE sentinels), `base.py` (PhaseInterface Protocol, PhaseResult), `context.py` (PhaseContext, BarState), `logger.py` (ComponentLogger).
- **Goes here:** code that runs every strategy regardless of config.
- **Does NOT:** any specific phase implementation (those live in `phases/`), any strategy config (those in `strategies/`).
