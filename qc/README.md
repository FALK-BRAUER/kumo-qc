# qc/

QuantConnect community backtest exports and parity artifacts.

- **What's here:** `INDEX.md` (community backtest index), `parity_table.md` (local/cloud parity tracking), and numbered subdirectories (`01_*` through `20_*`) containing exported QC backtest results (signal audits, performance windows, parity checks).
- **What goes in:** New QC backtest export downloads, parity verification artifacts, community-shared result snapshots.
- **What does NOT go here:** Local backtest results (use `results/`), source code (use `src/` or `algorithm/`), live trading configs.
- **Note:** Subdirectories follow a naming convention: `{number}_{description}` (e.g., `01_BCT FY2025 Signal Audit`). Each contains QC-exported JSON artifacts.
