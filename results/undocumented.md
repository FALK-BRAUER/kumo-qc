# Undocumented Backtest Results

**Recovered 2026-05-31 during anti-drift hygiene pass.**

These backtest result directories exist in `results/` but have **no corresponding provenance row in `bt-results.csv`**. They were run on various dates (mostly 2026-05-25 through 2026-05-29) during active experimentation but were never formally recorded in the ledger.

## Recovery Policy

- **Do NOT delete** these directories. They contain raw LEAN artifacts (config, log, summary JSON, order-events) that may be needed for future root-cause analysis.
- **Provenance is partial**: config files contain `lean_cli` container IDs but no git commit hash, branch name, or config-hash fingerprint. The metrics below were extracted post-hoc from summary JSONs.
- **Action**: When a result is referenced in analysis, add a proper row to `bt-results.csv` with reconstructed provenance. Until then, this file serves as the canonical index.

## Recovered Metrics

| Directory | BT ID | Sharpe | Net Profit | DD% | Orders | Win Rate | Date Found | Inferred Window |
|---|---|---|---|---|---|---|---|---|
| buy-stop-20260525 | 1489444499 | -1.186 | -0.831% | 7.400% | 466 | 39% | 2026-05-25 | ad-hoc |
| e28-fy2025 | 1374474354 | 0.878 | 26.730% | 14.000% | 178 | 40% | 2026-05-28 | FY2025 |
| e36-fy2025 | 1305307595 | 0.947 | 30.082% | 11.000% | 232 | 40% | 2026-05-27 | FY2025 |
| e36-test | 1189105124 | 0.947 | 30.082% | 11.000% | 232 | 40% | 2026-05-27 | FY2025 (test) |
| e37-fy2025 | 1240361178 | 0.263 | 12.336% | 20.000% | 251 | 32% | 2026-05-27 | FY2025 |
| e38-fy2025 | 1938933895 | 0.565 | 19.898% | 15.500% | 233 | 32% | 2026-05-27 | FY2025 |
| e40b-phase2 | 1741651769 | -0.19 | 2.771% | 13.300% | 209 | 35% | 2026-05-29 | FY2025 |
| e40e-fy2025 | 1101401814 | 1.275 | 32.124% | 6.600% | 168 | 43% | 2026-05-27 | FY2025 |
| e40e-w1 | 1629947897 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W1 |
| e40e-w2 | 1499885255 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W2 |
| e40e-w3 | 1849189422 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W3 |
| e40e-w4 | 1863878785 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W4 |
| e40e-w5 | 1493192258 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W5 |
| e40e-w6 | 1144378507 | 0 | 0% | 0% | 0 | 0% | 2026-05-27 | W6 |
| e49-fy2025 | NO_SUMMARY | N/A | N/A | N/A | N/A | N/A | 2026-05-27 | FY2025 (missing summary) |
| e51-fy2025 | 1314379420 | 1.025 | 31.001% | 11.300% | 212 | 42% | 2026-05-28 | FY2025 |
| e78-baseline-fy2025 | 1554150553 | 1.079 | 33.326% | 11.000% | 232 | 41% | 2026-05-28 | FY2025 |
| e78-baseline-W1 | 1405736172 | 1.494 | 11.304% | 8.500% | 74 | 50% | 2026-05-28 | W1 |
| e78-baseline-W2 | 1580277611 | -0.608 | -1.733% | 8.300% | 98 | 25% | 2026-05-28 | W2 |
| e78-baseline-W3 | 1456940542 | 4.427 | 18.479% | 3.200% | 42 | 44% | 2026-05-28 | W3 |
| e78-baseline-W4 | 1422825289 | -1.765 | -6.242% | 7.800% | 74 | 22% | 2026-05-28 | W4 |
| e78-baseline-W5 | 1210112792 | -1.171 | -5.818% | 11.500% | 110 | 24% | 2026-05-28 | W5 |
| e78-baseline-W6 | 1828268022 | 0.478 | 8.826% | 11.000% | 160 | 37% | 2026-05-28 | W6 |
| e78-fy2025 | 1216357736 | 0.831 | 25.763% | 12.100% | 228 | 39% | 2026-05-28 | FY2025 |
| e78-W1 | 1153349633 | 1.015 | 7.467% | 8.100% | 76 | 48% | 2026-05-28 | W1 |
| e78-W2 | 1306039979 | -0.51 | -1.173% | 8.000% | 92 | 27% | 2026-05-28 | W2 |
| e78-W3 | 1683252924 | 3.711 | 16.092% | 3.700% | 50 | 40% | 2026-05-28 | W3 |
| e78-W4 | 1927330037 | -1.638 | -5.554% | 7.100% | 70 | 23% | 2026-05-28 | W4 |
| e78-W5 | 1133437830 | -1.05 | -5.065% | 11.600% | 108 | 24% | 2026-05-28 | W5 |
| e78-W6 | 1624942705 | 0.195 | 5.114% | 12.100% | 158 | 38% | 2026-05-28 | W6 |
| gh119-local | 1426048827 | -1.623 | -0.305% | 1.000% | 10 | 0% | 2026-05-28 | ad-hoc |
| gh42-quick-test | 1862820917 | 0.201 | 0.152% | 0% | 6 | 0% | 2026-05-28 | ad-hoc |
| gh79-equity200-baseline | 1347864679 | 1.268 | 37.867% | 10.700% | 196 | 44% | 2026-05-28 | FY2025 |
| gh79-sp500 | 1915516493 | 0.254 | 11.727% | 14.800% | 222 | 37% | 2026-05-28 | FY2025 |
| spy-gate-20260525 | 1293702011 | -1.058 | 2.600% | 3.600% | 325 | 42% | 2026-05-25 | ad-hoc |
| spy-weekly-20260525 | 1491230414 | 0 | 0% | 0% | 0 | 0% | 2026-05-25 | ad-hoc |
| throughput-audit | 1141490348 | N/A | N/A | N/A | N/A | N/A | 2026-05-25 | audit (no trades) |
| throughput-audit-2020 | 1887473040 | 0 | 0% | 0% | 0 | 0% | 2026-05-25 | audit (no trades) |
| throughput-audit-2020-v2 | 1687479397 | -2.042 | -8.675% | 13.400% | 10 | 0% | 2026-05-25 | audit |
| throughput-audit-warm0 | 1465027359 | 0 | 0% | 0% | 0 | 0% | 2026-05-25 | audit (no trades) |
| w1-4gates-20260525 | 1719830586 | -0.57 | 4.120% | 4.900% | 517 | 44% | 2026-05-25 | W1 |
| w1-local-20260525 | 1780600434 | -6.051 | -0.413% | 1.200% | 39 | 43% | 2026-05-25 | W1 |
| w1-local-20260525-fix | 1753751456 | -6.051 | -0.413% | 1.200% | 39 | 43% | 2026-05-25 | W1 |
| w1-local-20260525-v3 | 1526493840 | -0.404 | 4.350% | 6.000% | 575 | 41% | 2026-05-25 | W1 |

## Notes by Directory

- **buy-stop-20260525**: E37 buy-stop entry variant (ad-hoc run, not catalogued).
- **e28-fy2025**: E28 VIX-percentile regime gate. Metrics align with bt-results.csv E28 entries but this specific run lacks a ledger row.
- **e36-fy2025 / e36-test**: E36 ATR stop variant. e36-test duplicates e36-fy2025 metrics (likely same config).
- **e37-fy2025**: E37 buy-stop entry FY2025. 20% DD, 32% WR — rejected per methodology.
- **e38-fy2025**: E38 resistance gate FY2025. 15.5% DD, 32% WR.
- **e40b-phase2**: E40b SPY>200MA regime gate Phase 2 validation run. Post-hoc recovery, commit unknown.
- **e40e-w1..w6**: E40e regime-gate weekly windows. All show 0 trades (regime gate blocked all entries in those windows).
- **e49-fy2025**: E49 IWM breadth canary. **Summary JSON missing** — only config and log files exist.
- **e51-fy2025**: E51 parabolic block FY2025. 1.025 Sharpe, 212 orders, 42% WR. Post-hoc recovery from results dir.
- **e78-* (baseline + W1..W6)**: E78 active-return-gate window suite. Baseline and weekly windows all recovered from results/.
- **gh119-local**: GH#119 local/cloud divergence diagnostic run.
- **gh42-quick-test**: GH#42 quick validation run (6 orders, minimal).
- **gh79-equity200-baseline / gh79-sp500**: GH#79 universe composition tests (equity-200 vs S&P500).
- **spy-gate-20260525 / spy-weekly-20260525**: SPY regime gate and weekly-kijun diagnostic runs.
- **throughput-audit***: Data throughput / warm-up audit runs. Most show 0 trades (audit mode).
- **w1-local-20260525***: W1 local validation runs with varying gate configurations (4gates, local, fix, v3).
