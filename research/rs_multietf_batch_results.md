# R/S + Multi-ETF Batch — FY2025 Results (2026-05-30)

**Base:** champion `3b1c244` (e40c QQQ>50MA, flat-10% sizing, MS7, dollar-vol tiebreak)
**Champion benchmark:** Sharpe **0.778** / 143 orders / +23.61% / 46% WR / 9.1% DD (verified reproducible)
**Method:** 8 experiments, one isolated worktree each, BT-serialized (`LEAN_LOCK=1`), every result marker-verified AND gate-fire-verified in runtime logs (no fabrication).
**Data layer:** `algorithm/resistance_support.py` (#146) — R/S levels from the algorithm's own daily bars.

## Results (FY2025, sorted by Sharpe)

| Exp | Ticket | Gate | Sharpe | Orders | Net | DD | Gate-fires | Verdict |
|-----|--------|------|-------:|-------:|----:|---:|-----------:|---------|
| me154 | #154 | QQQ>50 **OR** IWM>50 | 0.752 | 145 | +23.1% | 9.1% | 83× | REJECT (near-miss) |
| me153 | #153 | QQQ>50 **AND** SPY>50 | 0.682 | 147 | +20.8% | 8.7% | 96× | REJECT |
| rs148 | #148 | enter 2–10% below resistance | 0.574 | 168 | +18.2% | 11.1% | 7379× | REJECT |
| rs149 | #149 | buy-stop above resistance | 0.480 | 176 | +15.9% | 9.5% | 93× | REJECT |
| rs151 | #151 | polarity-flip trail | 0.446 | 266 | +14.4% | **6.4%** | 78× | REJECT (low DD) |
| rs150 | #150 | R/R ≥ 2:1 | 0.409 | 200 | +14.1% | 8.2% | 7405× | REJECT |
| rs147 | #147 | struct stop max(Kijun,supp+0.5ATR) | 0.131 | 393 | +9.2% | 7.2% | 192× | REJECT (churn) |
| me157 | #157 | breadth >50% above 200MA | 0.039 | 169 | +7.5% | 10.2% | 277× | REJECT |

**None beat champion 0.778.** No window validation triggered.

## Findings

- **me154 / me153 (index regime variants):** loosening (OR) → 0.752, tightening (AND) → 0.682. Single-QQQ gate is already near-optimal; multi-index variants move it marginally. me154 is the closest challenger.
- **rs147 struct stop:** tightening the stop produced **2.7× the orders** (393 vs 143) → Sharpe collapse. Independently re-confirms the V7/V12 lesson: the daily Kijun stop is near-optimal; structural tightening churns.
- **rs151 polarity trail:** Sharpe-negative vs champion but **lowest DD in the batch (6.4% vs 9.1%)** — a drawdown-reducer worth keeping as a Phase-3 ingredient.
- **me157 breadth gate:** near-destroys returns (0.039) — blocking entries when <50% of universe is above 200MA removes too many good setups in a year that was mostly risk-on.
- **rs148/rs149/rs150 (R/S entry discipline):** all reduce orders and underperform under flat-10%. The flat-10% ceiling caps upside; these may behave differently under risk-based sizing.

## Phase-3 retest candidates (under risk-based sizing)

Flat-10% is the disqualified-for-live champion. These were tested against it; the real test is combining them with risk-based sizing:

- **HIGH:** me154 (near-miss 0.752) · rs151 (DD-reducer 6.4%)
- **MEDIUM:** rs148 · me153
- **LOW:** rs147 · me157 (rejected on principle)

Tickets kept OPEN, tagged Phase-3 retest candidate.

## Sector-regime batch (#155/#156) — appended 2026-05-30

| Exp | Ticket | Gate | Sharpe | Ret% | DD% | Orders | Gate-fires | Verdict |
|-----|--------|------|-------:|-----:|----:|-------:|-----------:|---------|
| me155 | #155 | per-stock: sector ETF > 50MA | -0.031 | +6.48% | 8.9% | 167 | 5490× | REJECT |
| me156 | #156 | sector ETF >50MA AND sector 20d > SPY 20d | -0.186 | +4.15% | 7.8% | 165 | 5612× | REJECT |

Both turn Sharpe **negative** — sector regime gating over-filters, removing winners faster than losers. Sector RS (#156) is the worst in the entire day's batch.
**Caveat:** `ticker_sector_map.json` covered 246/326; the 80 unmapped (P–Z, FMP free-tier daily cap) bypassed the gate (~25% of universe ungated). Direction is strongly negative — a full-map re-run will not flip positive, but a clean re-run is warranted if ever revisited. Backfill pending FMP daily reset. Phase-3 priority LOW.

## Verification trail

All 8: `VERSION_MARKER|<id>_*` present in executed `code/main.py` snapshot (wrapper-confirmed own code ran) + distinct gate-log token counted in runtime log (proves logic fired). Artifacts in each `kumo-qc-<id>/algorithm/performance_bct/backtests/`. Numbers from `*-summary.json` statistics only.
