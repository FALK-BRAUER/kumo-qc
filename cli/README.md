# cli/

The operator CLI — one typed entry point (Typer) replacing the 106-script sprawl. **Dev tooling; NOT shipped to `dist/`.**

- **Holds:** `app.py` (root Typer app), `commands/{data,build,bt,deploy,sweep,lib}.py`, `lib/runner.py` (the subprocess WRAP layer).
- **Subcommands (each WRAPS a production-tested keeper — internals unchanged):**
  - `kumo data` build-daily · manifest · conform-coarse · etf-universe · extend
  - `kumo build [STRATEGY_MODULE]` — package the active phase closure src/→dist/ (imports `build/cloud_package.build`)
  - `kumo bt` run (lean-bt.sh) · record · parity · collect
  - `kumo deploy` cloud (qc_v2_cloud) · gate · live — the live-account path; CLI is a transparent pass-through
  - `kumo sweep` — STUB until #214
  - `kumo lib` install-hooks · pre-commit · check-defaults · clean-containers · preflight (shells out to scripts/*.sh)
- **Run:** `python -m cli <group> <cmd>` (or wire a `kumo` console script). All keepers run verbatim — `kumo` resolves the path, forwards args, propagates the exit code.
- **Why Python (not TS/Go):** the real work IS Python — it imports `build/cloud_package`, the typed `StrategyConfig`, the data tooling, `parity_diff`. A non-Python CLI would only subprocess these + duplicate types across a boundary. One language, one `mypy --strict`, no drift.
- **Does NOT:** contain strategy logic (that's `src/`), ship to cloud (dev-only). Tests mirror under `tests/cli/`.
- **Replaces:** the ad-hoc `scripts/` — most fold into subcommands; genuine one-offs stay thin or archive.
