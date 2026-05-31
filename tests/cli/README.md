# tests/cli/

Tests for the `kumo` operator CLI (`cli/`, #221). Mirrors the six subcommand groups.

- **Holds:** `test_app.py` (root wiring) + `test_{data,build,bt,deploy,sweep,lib}.py` (per-group resolution) + `test_runner.py` (the WRAP layer).
- **Goes here:** Typer `CliRunner` resolution/help/option-typing checks; safe read-only smoke (e.g. `sweep` stub).
- **Does NOT:** execute real keepers — nothing that hits the cloud, touches live accounts (gate/deploy), or runs a real backtest. Those are tested for wiring only.
