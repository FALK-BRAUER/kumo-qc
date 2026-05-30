# src/

Development source for the strategy engine. Nested, type-checked (`mypy --strict`), never deployed directly — `build/` flattens this to `dist/`.

- **Holds:** `engine/` (the engine core), `phases/` (the phase library), `strategies/` (named configs), `main.py` (entry), `universe.py`.
- **Goes here:** all hand-written strategy/engine code.
- **Does NOT:** generated artifacts (that's `dist/`), tests (that's `tests/`, mirroring this tree), backtest output (`backtests/`).
