# results/

The master results ledger — curated, tracked, single source of truth for "what scored what."

- **Holds:** `bt-results.csv` (one schema), `schema.md` (canonical column definition).
- **Schema (mandatory provenance):** `config_hash · data_fingerprint · commit · bt_id · marker · sharpe · ret_pct · dd_pct · orders · window · verdict`. A row without (code + data + config) pinning is NOT valid (the 1.079-not-pinned-to-its-data lesson).
- **Goes here:** accepted/promoted results only.
- **Does NOT:** raw per-run output (`backtests/`, gitignored), per-sweep leaderboards (`sweeps/reports/`).
