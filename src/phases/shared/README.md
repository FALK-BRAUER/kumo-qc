# phases/shared/

Cross-phase shared helpers — primitives more than one phase kind depends on. NOT a phase kind
(nothing here is wired into a `StrategyConfig` directly).

- **Holds:**
  - `oracle_helpers.py` — the BCT scorers (`score_symbol` / `score_symbol_native`). **DO NOT
    modify** — changes break champion-asis parity (ARCH-C ±0.01 gate).
  - `chart_features.py` — pure QC-safe chart-curation formulas for scanner/ranking experiments.
  - `param_space.py` — `ParamSpace` (the `space()` return shape, ADR D2) + `ComplexityDecl`
    (the overfitting-defense declaration, ADR D5). The #228 template every phase kind uses.
  - `sample_helper.py` — teaching-fixture support.
- **Goes here:** logic shared by ≥2 phase kinds, with no per-bar state of its own.
- **Does NOT:** hold a phase impl, read files via relative paths, or carry strategy config.
