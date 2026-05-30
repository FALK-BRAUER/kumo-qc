# cli/

The operator CLI — one typed entry point (Typer) replacing the 106-script sprawl. **Dev tooling; NOT shipped to `dist/`.**

- **Holds:** `app.py` (Typer app), `commands/{data,build,bt,deploy,sweep,lib}.py`, `lib/` (shared helpers).
- **Subcommands by aspect:** `kumo data build|fingerprint|verify` · `kumo build` (src/→dist/) · `kumo bt run|parity` · `kumo deploy` (QC API) · `kumo sweep run|report` · `kumo lib list-phases|new-phase`.
- **Why Python (not TS/Go):** the real work IS Python — it imports `build/cloud_package`, the typed `StrategyConfig`, the data tooling, `parity_diff`. A non-Python CLI would only subprocess these + duplicate types across a boundary. One language, one `mypy --strict`, no drift.
- **Does NOT:** contain strategy logic (that's `src/`), ship to cloud (dev-only). Tests mirror under `tests/cli/`.
- **Replaces:** the ad-hoc `scripts/` — most fold into subcommands; genuine one-offs stay thin or archive.
