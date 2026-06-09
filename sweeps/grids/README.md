# sweeps/grids/

Permutation specifications — TRACKED. Each defines a parameter/phase grid the driver expands into N strategy variants.

- **Holds:** declarative sweep definitions. `intraday_selectivity.py` — the #323 grid
  enumerator (PRIMARY axis = signal `min_score` {6,7,8}; algorithm {gap_loud, hold_above_n,
  gap_loud_wick}; de-emphasised gap, vol, entries_cap hook, minimal off-biased regime;
  coarse 64 / full 2016 configs; `enumerate_grid` + `dry_run`). `windows_fy2025.py` — the
  6 FY2025 bi-monthly panel + FY2024 OOS holdout the sweep runs every config across.
  `george_context.py` — the #416/#427 named George-context protocol: first a 6-pack validation,
  then a 30-pack in five six-variant waves, plus a second MFE combo 30-pack.
  `scanner_ranker.py` — the #446 opt-in LambdaMART scanner first pack: champion baseline,
  ranker-off/fallback controls, and top10/top20/top50 learned scanner gates.
- **Goes here:** declarative sweep definitions (the axes + window panels).
- **Does NOT:** results (that's `reports/`), generated runs (`runs/`), the objective math
  (that's `../objective/`), or the run-a-config adapter (that's `../adapters/`).
