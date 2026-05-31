# research/parity/artifacts/

Pinned provenance artifacts for the #265 residual root-cause (apples-to-apples post-#259).

- **Holds:** `cloud_orders_265.json` (the cloud ground-truth orders from QC bt
  `b40551526c27537834bda25da58521ec`, via `/backtests/orders/read`), `local_traded_symbols.json`
  + `local_active_set_counts.csv` (from the local BT `2026-05-31_21-43-05`),
  `residual-data-2025.json` (the gap-name classification output of `scripts/residual_parity_diff.py`).
- **Goes here:** the raw artifacts a parity finding is computed FROM — so any number in
  `residual-root-cause-2025.md` traces to a real file (data-integrity rule).
- **Does NOT:** local BT output dirs (gitignored `backtests/`), regenerable scratch.
