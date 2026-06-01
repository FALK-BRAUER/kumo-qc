# sweeps/objective/

The #323 robust-selection objective — what "positive outcome" MEANS. Computed on the
return/trade series the sweep already produced (ZERO extra backtests, mock-testable).

- **Holds:** `dsr.py` (Deflated Sharpe — multiple-trials correction, primary selector),
  `pbo.py` (Probability of Backtest Overfitting via CSCV — global overfit measure),
  `cpcv.py` (combinatorial purged CV + embargo — OOS path estimator), `gates.py`
  (trade-count gates + window weighting + the W5-concentration robustness guard),
  `selector.py` (the lexicographic FILTER → weighted SCORE → cost-aware-champion-beat).
- **Goes here:** pure scoring/selection science over `RunResult` series.
- **Does NOT:** run LEAN/cloud (that's `adapters/`), enumerate the grid (that's `grids/`),
  or write the ledger (that's `provenance.py`).
