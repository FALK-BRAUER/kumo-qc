# src/strategies/

Named `STRATEGY_CONFIG`s — first-class, type-checked. Each selects phases from the library via **direct class references** (not strings).

- **Holds:** `<name>.py`, each exporting a `StrategyConfig` of `Slot(impl=SomePhase, params=SomePhase.Params(...))`.
- **Active strategy:** ONE at a time (`main.py` selects it); `build/` packages only that strategy's phase closure to `dist/`.
- **Goes here:** a config you want to deploy or sweep over.
- **Does NOT:** phase logic (that's `phases/`), raw param dicts (params are typed `.Params` dataclasses).
