# storage/

Transient runtime artifacts — not committed.

- **What's here:** Temporary files generated during strategy execution (e.g., BCT signal snapshots, cached indicator state). Contents are ephemeral and gitignored by default.
- **What goes in:** Runtime-generated state that must survive between backtest restarts but is not source code.
- **What does NOT go here:** Backtest results (those go in `results/`), source code, or committed config.
