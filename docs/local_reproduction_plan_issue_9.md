# Reproduction Plan for Issue #9: Reproduce bct-perf-2020-2026 Locally

## Configuration
- **QC User ID:** 499707
- **QC API Token:** f587ef18bc5084436eb4f992da00282cd5807991422c3c1485d7b1035fa7b477 (stored in macOS keychain)
- **Project ID:** 32034565 (performance_bct)

## Dates
- **Test Range:** 2020-01-01 to 2026-05-24

## Expected Output
- Backtest results for the specified date range, including performance metrics such as Net%, Sharpe Ratio, Total Trades, Win Rate, etc.
- Results should be consistent with the cloud-based backtest results from QC.

## Steps
1. Ensure LEAN CLI is installed and configured.
2. Ensure QC API credentials are correctly set up in macOS keychain.
3. Run the local backtest using the `lean backtest` command with the specified date range.
4. Verify that the backtest completes successfully.
5. Compare the local backtest results with the cloud-based backtest results.

**Command Example:**
```bash
lean backtest "algorithm/performance_bct" --output results/bct-perf-2020-2026/ --start=2020-01-01 --end=2026-05-24
```

**Expected Output Path:**
- `results/bct-perf-2020-2026/backtests/*/output/results.json`
