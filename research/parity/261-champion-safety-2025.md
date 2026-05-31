# #261 Champion-Safety Verification — fail-loud guards are dormant on valid data

**Question (the gate-blocker):** do the 8 #261 `DegradedDataError` guards change the champion's
measured behavior? They must fire ONLY on degraded/missing/not-ready data; the happy path must be
byte-unchanged.

**Method:** built `strategies.champion_asis` (the #261-guarded src) into the throwaway
`algorithm/v2_champion_asis` lean project (`scripts/measure_base_baseline.sh local`) and ran the
DIST-ENGINE full-FY2025 backtest locally (the `BctEngineAlgorithm` phase engine — DvRankCap +
SpySma200 + KijunG3Exits — NOT the legacy `performance_bct` harness). 560-day warmup from
2023-06-21 + FY2025. Verified the phase engine ran via the `STRATEGY_TICK` chain in the log
(`universe→signal→regime→exit_hard→diagnostics`).

**Result — CLEAN MATCH, zero guards fired:**

| Metric | #261-guarded dist engine | #265 warmed baseline | Match |
|---|---|---|---|
| Sharpe | **−0.139** | −0.139 | ✓ |
| Net Profit | **+3.620%** | +3.62% | ✓ |
| Total Orders | **244** | 244 | ✓ |
| Drawdown | **14.800%** | 14.8% | ✓ |

- **`DegradedDataError` occurrences across the full run: 0.** The guards are dormant safety nets on
  the valid path — no silent degradation was hiding in the champion feed.
- Selections stayed non-empty all year (active_set ~640–938/day); regime + exits evaluated normally.
- `CONFIG_HASH = e573e84b1ce1` UNCHANGED (the guards are not STRATEGY_CONFIG params).

**Artifact (gitignored backtests/, recorded here for provenance):**
`algorithm/v2_champion_asis/backtests/2026-05-31_23-10-23/` — stats `1382000492.json`
(Sharpe −0.139 / Net Profit 3.620% / Total Orders 244 / Drawdown 14.800%). Run log captured the
0-`DegradedDataError` count over the full warmup+FY span.

**Conclusion:** #261 adds fail-loud guards WITHOUT changing the champion's measured behavior — the
happy path is byte-identical to the #265 warmed baseline. The guards protect the broken-data
scenarios (Inf/NaN/negative values, missing/empty/broken-0 feeds, cold regime/stop) that #263/#264
surfaced, and raise `DegradedDataError` with context when those occur — never a silent mirage.
