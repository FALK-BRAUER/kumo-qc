# Phase-3a F1 — Risk Base + Polarity Trail + Pyramid (2026-05-30)

**Base:** risk-based 2f5e14c (risk_amount=500, max_entries_per_day=10, e40c QQQ50, MIN_SCORE7, dollar-vol tiebreak). Verified risk base = **0.536 / +16.0% / 8.0% DD / 197 orders**.
**F1 spec:** base + rs151 polarity-flip trail stop + pyramid (max 3 lots, $200 adds on Kijun-breakeven).
**Commit:** ca2f7fa (`feat/f1-risk-trail-pyramid`). Build verified: base-equivalence exact (features off → 0.536/197), both gate tokens fire.

## Isolation (full new-metrics framework)

| Config | Sharpe | Ret% | DD% | Ord | WR | avgW$ | avgL$ | pyrFactor | adds | trail | Exp$/trade |
|--------|-------:|-----:|----:|----:|---:|------:|------:|----------:|-----:|------:|-----------:|
| **risk base** | **0.536** | +16.0% | 8.0% | 197 | 37% | 637 | -332 | 1.00 | 0 | 0 | **+26.02** |
| trail-only | -0.043 | +6.8% | **6.7%** | 337 | 41% | 452 | -292 | 1.00 | 0 | 102 | +11.06 |
| pyramid-only | -0.193 | +4.1% | 9.8% | 220 | 40% | 356 | -255 | 1.56 | 51 | 0 | **-10.38** |
| full F1 | -0.149 | +5.1% | 7.0% | 335 | 38% | 371 | -227 | 1.45 | 63 | 78 | -1.88 |

## Findings

1. **Pyramid is the killer.** The $200 Kijun-breakeven add collapses per-trade economics: Exp$/trade +26.02 → -10.38. Adds enter at higher prices, drag avg-win from $637 → $356, and get stopped on pullbacks. `pyrFactor` 1.56 confirms it fired heavily — it simply destroys value for this entry/stop structure. The Kelly-style "add to winners" thesis is **refuted** here.
2. **Trail is DD-protective but dilutive.** Polarity-flip trail gives the best drawdown in the set (6.7% vs base 8.0%) but cuts Exp$/trade +26 → +11 by exiting winners early. Keep ONLY as a DD-reduction tool, not for return.
3. **The risk base alone dominates** every metric that matters (Sharpe 0.536, Exp$/trade +26.02). Neither ingredient earns its place in a deployable config.

## Implication for F2–F5

F2/F3/F5 were specified as "F1 + X" (regime / circuit-breaker / ADX gate). Since F1's pyramid poisons the base, those layers cannot recover it — running them as-spec yields uninformative rejects. **Recommend redefining the F-track base to the risk base (optionally + trail as a DD tool), dropping pyramid, then layering F2/F3/F5 on a base that works.** Decision pending fintrack/Falk.

Verification: all four runs marker `f1_risk_trail_pyramid_v1` confirmed; PYRAMID_ADD / POLARITY_TRAIL counts from runtime logs; metrics from `totalPerformance.tradeStatistics` + `statistics` in each backtest's result json.
