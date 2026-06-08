# build/

The config-aware packager: turns nested `src/` into the flat `dist/` LEAN deploys (QC cloud has no subdirectories).

- **Holds:** `cloud_package.py` — AST-parses the ACTIVE strategy config, walks its import closure, flattens ONLY the enabled phases to `dist/` (`phase_<kind>_<impl>.py`, rewriting imports), emits `_manifest.json` + `_metadata.py`. `sweep_build.py` maps a `SweepConfig` onto a full champion `StrategyConfig` before using the same packager.
- **Goes here:** build/packaging tooling only.
- **Does NOT:** strategy logic. NOTE: this script is the single point of failure for cloud/local parity — it MUST stay unit-tested (`tests/` covers it).
