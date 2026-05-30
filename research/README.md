# research/

The analysis / knowledge layer — the *narrative* behind the numbers. Distinct from `results/` (the numeric ledger) and `sweeps/` (the optimization runs). Reference docs, no runnable code.

## Structure (categorized)
```
research/
  catalog/          experiment_catalog.csv — master enumeration of every experiment + verdict
  experiments/      per-experiment writeups: hypothesis · setup · result · verdict,
                    each pinned to (commit + data-fingerprint + bt-id) so it's traceable
  trade-analysis/   trade-behavior studies (winners/losers, hold times, payoff) — the #174 mandate
  parity/           cloud-local + engine-oracle parity diagnostics (first-divergence walks)
  methodology/      DSR/PBO, validation-gate methodology, audit plans, sizing/model studies
  ideas/            idea banks, candidate strategies, external-source analyses
  sources/          private-source logs (energy/commodity/geopolitical edges)
```

## Rules
- **Pin to provenance.** An experiment writeup references the `results/` row + commit + **data-fingerprint** (so pre- vs post-raw-rebuild analyses are comparable). Un-pinned analysis is suspect (the 1.079 lesson).
- **No runnable code here** — tooling (e.g. download/fetch scripts) lives in `cli/` or `scripts/`, not `research/`.
- Each subdir self-documents with its own README.

## Does NOT hold
- The numeric ledger (`results/bt-results.csv`), sweep leaderboards (`sweeps/reports/`), raw BT output (`backtests/`), or scripts.
