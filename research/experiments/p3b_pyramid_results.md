# Phase 3b — Pyramid Technique Search (#172, 2026-05-30)

**Premise:** F1 proved the breakeven-triggered $200 pyramid add is refuted (Exp$/trade +26 → -10). Falk directive: find a pyramid *mechanic* that works. Swept 5 trigger/size schemes via a shared pure-fn engine.

**Engine:** `algorithm/performance_bct/pyramid_engine.py` — `should_add(variant, lots, ...)` + `add_dollars(variant, lots)`, 7/7 unit tests. Param `pyramid_variant=Pa..Pe` drives one main.py integration (no divergent implementations). Commit 485a925 (`feat/p3b-pyramid-search`).
**Control:** initial lot = risk base (risk_amount=500) for ALL variants; engine governs ADD lots only → clean A/B vs the +$26.02/trade risk base.

## FY2025 results (verified: marker + PYRAMID_ADD fired)

| Var | Mechanic | Sharpe | Ret% | DD% | Ord | WR | avgW$ | avgL$ | pyrF | Exp$/trade |
|-----|----------|-------:|-----:|----:|----:|---:|------:|------:|-----:|-----------:|
| **Pe** | fresh Tenkan>Kijun cross | **0.961** | +23.5% | 7.1% | 196 | 45% | 491 | -233 | 1.51 | **91.64** |
| **Pc** | ATR-spaced (+1/+2 ATR) | 0.736 | +20.3% | **6.5%** | 224 | 43% | 373 | -209 | 1.98 | 43.17 |
| Pb | wide-spaced +10/+20% | 0.389 | +13.9% | 6.8% | 205 | 39% | 525 | -283 | 1.39 | 34.24 |
| Pa | de-pyramid +5/+10% ($250/$125) | 0.368 | +13.3% | 6.4% | 218 | 38% | 378 | -202 | 1.74 | 20.32 |
| Pd | vol-confirmed (TR>1.5×20d) | -0.372 | +1.5% | 8.1% | 227 | 43% | 371 | -267 | 1.49 | 5.42 |
| *risk base* | (no pyramid) | 0.536 | +16.0% | 8.0% | 197 | 37% | 637 | -332 | 1.00 | 26.02 |
| *flat-10% champion* | (no pyramid) | 0.778 | +23.6% | 9.1% | 143 | 46% | — | — | 1.00 | — |

## Findings

1. **Pe (signal-renewed) is the winner — and beats the flat-10% champion (0.961 vs 0.778) with lower DD (7.1% vs 9.1%).** Adding $200 on a *fresh Tenkan>Kijun cross* compounds into validated momentum. Exp$/trade 91.64 = 3.5× the risk base. Composite (Exp$/t × pyrF / DD) ≈ 19.4 vs base 3.25 — ~6×.
2. **Pc (ATR-spaced) is strong** (0.736, best DD 6.5%): volatility-aware spacing avoids over-adding in chop.
3. **Pd (vol-confirmed) fails** (-0.372): adding on raw volatility spikes = adding on noise. Confirms the edge is *signal*, not *movement*.
4. **The F1 lesson refined:** breakeven-trigger and price-distance triggers (Pa/Pb) are weak; the winning adds are gated on a **renewed entry signal (Pe)** or **volatility structure (Pc)**, not arbitrary price levels.

## Status

⚠️ FY2025 single-window only. Per the day's discipline (phantom 0.392), Pe + Pc are NOT declared deployable until **W1–W6 window validation** (running). Pd/Pb/Pa rejected on FY. Window results appended below when complete.

## Verification

All 5: marker `pyramid_engine_v1` confirmed own-code-ran; PYRAMID_ADD counts from runtime logs (Pe 42, Pc 77, Pb 35, Pa 62, Pd 47); metrics from `totalPerformance.tradeStatistics` + `statistics`. Engine unit-tested independently (`pyramid_engine.test.py`).

## Uncapped validation (slot-artifact test, 2026-05-30)

Falk caught that `max_lots=3` is a hardcoded slot cap (E40d-class). Re-ran Pe + Pc with the cap removed (`pyramid_uncapped`, lots bounded by signal frequency + `max_ticker_risk_usd`).

| variant | capped Sharpe | UNCAPPED Sharpe | Ret% | DD% | pyrF cap→uncap | Exp$/t | verdict |
|---------|-------------:|----------------:|-----:|----:|:--------------:|-------:|---------|
| **Pe** | 0.961 | **1.00** | +24.5% | 7.1% | 1.51 → 1.54 | 103.73 | ✅ GENUINE — cap irrelevant |
| Pc | 0.736 | **-0.449** | -2.0% | 12.9% | 1.98 → 2.63 | -23.44 | ❌ slot artifact — rejected |

**Pe is validated.** Unlimited and $1500-ceiling runs are identical — the fresh-Tenkan>Kijun-cross signal naturally self-limits to ~1.5 adds/ticker, so no cap ever binds. Removing it left Pe unchanged (slightly better, 0.961→1.00). Not a slot artifact.

**Pc was a slot artifact.** Uncapped, ATR-multiple adds keep firing through trends (119 adds, pyrF 2.63), DD blows from 6.5%→12.9%, Sharpe → -0.449. The capped 0.736 was manufactured by the 3-lot limit — exactly the E40d 1.442 trap. Rejected.

**Pe deployable-candidate profile:** $500 risk-based initial, +$200 on fresh Tenkan>Kijun cross (no count cap), FY2025 1.00 Sharpe / +24.5% / 7.1% DD / WR 45% / Exp$/trade 103.73. Beats the disqualified flat-10% champion (0.778) with lower drawdown. Window robustness (capped) 5/6 positive; uncapped-window re-check recommended before Phase-2 graduation.
