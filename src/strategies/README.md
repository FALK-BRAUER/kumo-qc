# src/strategies/

Strategy configurations — wiring phases into runnable configs.

- **What's here:** Strategy config modules that instantiate `StrategyConfig` with `Slot(impl=..., params=...)` tuples defining the phase stack. `_example.py` shows the template pattern.
- **What goes in:** New strategy variants (different phase combinations or param overrides), champion-as-is configurations, sweep candidate configs.
- **What does NOT go here:** Phase implementation (use `src/phases/`), engine mechanics (use `src/engine/`), backtest execution (use `scripts/local_backtest.py`).
- **Pattern:** A strategy config = name + version + phases dict keyed by PHASE_ORDER kind strings, with explicit Slot wiring.
