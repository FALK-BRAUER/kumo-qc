# src/phases/

BCT strategy phases — one directory per PHASE_KIND.

- **What's here:** `signal/`, `universe/`, `sizing/`, `exit/`, `regime/`, `diagnostics/` — each containing protocol-conforming phase implementations with `.Params` + `space()` + `COMPLEXITY` + `version_marker`.
- **What goes in:** New phase kinds (add subdir), new phase implementations (add dir under existing kind), shared helpers (use `shared/`).
- **What does NOT go here:** Engine orchestration (use `src/engine/`), strategy configs (use `src/strategies/`), backtest result parsing (use `scripts/` or `research/`).
- **Pattern:** Each phase dir = `{phase_name}/{phase_name}.py` + `__init__.py` + optional `README.md`. Follow the `bct_score_full/` template for headers, `.Params.space()`, `COMPLEXITY`, and behavioral tests.
