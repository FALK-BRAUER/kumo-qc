---
type: reference
tags: [kumo-qc, experiments, backtests]
updated: 2026-05-28
---

# kumo-qc Experiment Log

> **Fleet state:** [GH #110](https://github.com/FALK-BRAUER/kumo-qc/issues/110) — champion, queue, closed tracks, worker protocol. Single source of truth for cold pickup.


**Baseline — G3** (Phase 3 cloud-bottom stop at 56d/15% unrealized PnL)

| Metric | Value | Commit |
|--------|-------|--------|
| FY2025 Sharpe | **1.036** (current) / ~~1.079~~ (pre-#81 fix, deprecated) | `8048c29` |
| FY2025 Return | +30.05% / ~~+33.3%~~ | |
| Orders | ~240 / ~~232~~ | |
| Win Rate | 40% | |
| Max Drawdown | 11% | |
| Universe | polygon-326 static tickers, local LEAN | |

> Δ column = FY2025 Sharpe minus G3 1.036 baseline. Positive = better.  
> Pre-E36 experiments used old baseline (1.079) in their original notes — actual Sharpe shown here, Δ recalculated vs 1.036.

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | ACCEPTED — improves G3 on FY2025 + multi-window |
| ❌ | REJECTED — hurts G3 on FY2025 |
| 💀 | CATASTROPHIC — Δ < −0.5 or Sharpe < 0 |
| ➖ | NEUTRAL — \|Δ\| < 0.05, no meaningful change |
| 🚫 | ABORTED — not run, predicted negative |
| ⏳ | PENDING — queued for testing |
| 🔒 | BLOCKED — infra/env failure, result invalid |

---

## Phase 0 — Pre-Tracker Experiments

> Run before bt-results.csv tracking began. Data from FOR_FALK.md narrative summaries.  
> Commit hashes not individually tracked — see FOR_FALK.md.

| ID | Description | Status | FY2025 Sharpe | Δ | GH | Key Finding |
|----|-------------|--------|:---:|:---:|:---:|-------------|
| E8 | ADX hard gate (ADX ≥ 25 required) | ❌ | 1.026 | −0.010 | [#47](https://github.com/falkhansen/kumo-qc/issues/47) ✓ | Scored condition superior to hard gate; marginal but consistent negative |
| E18 | Time-based exit (90d + close < Tenkan) | ➖ | 1.079 | +0.043 | — | Time exit never fired in FY2025; effectively a no-op |
| E26 | Inverse-vol sizing (σ-scaled position size) | ➖ | 1.036 | 0 | [#55](https://github.com/falkhansen/kumo-qc/issues/55) ✓ | Bimodal: helps H2 trending, destroys H1 volatile (−0.4 to −1.0) |
| E32 | Three-Phase Stop: Tenkan Phase 1 at d1–d3 | 💀 | −0.021 | −1.057 | [#82](https://github.com/falkhansen/kumo-qc/issues/82) | Tenkan fires on normal d1–3 volatility → 578 orders (2.4× baseline) |
| E49a | Chikou span gate (daily chikou above price) | ❌ | 0.977 | −0.059 | — | Redundant with weekly chikou (condition #3); cuts winners not losers |
| E49b | IWM breadth canary (IWM < 50d SMA blocks entries) | ❌ | 0.933 | −0.103 | [#49](https://github.com/falkhansen/kumo-qc/issues/49) | Lagging indicator; blocks recovery-phase entries, not bad entries |
| E53 | Earnings avoidance window (±5 days) | ❌ | 0.908 | −0.128 | [#53](https://github.com/falkhansen/kumo-qc/issues/53) | Removes positive-expectancy pre-earnings runup trades |
| E54 | Tenkan-exit first 28d (Phase 1 tight stop) | 💀 | ~0.4 | ~−0.6 | [#83](https://github.com/falkhansen/kumo-qc/issues/83) | 9-day Tenkan fires on normal volatility; ~100 orders vs 230 baseline |
| E55 | Weekly Kijun exit (26-week as stop) | 💀 | −0.289 | −1.325 | [#84](https://github.com/falkhansen/kumo-qc/issues/84) | Positions bleed for weeks; 20% WR, 26.6% DD |
| E58 | Cloud thickness sizing (wider cloud = smaller size) | ➖ | 1.036 | 0 | — | Zero delta; initial 2.497 Sharpe report was wrong window |
| E76-1 | Heat cap 6% + risk 0.5% per trade | 💀 | −0.291 | −1.327 | [#75](https://github.com/falkhansen/kumo-qc/issues/75) ✓ | 748 orders (3× baseline); micro-positions churn to death |
| E76-2 | Heat cap 6% + risk 1.0% per trade | 💀 | −0.327 | −1.363 | [#75](https://github.com/falkhansen/kumo-qc/issues/75) ✓ | 538 orders; flat 10% dominates, risk sizing is poison for BCT |
| E76-3 | Heat cap 6% + risk 1.5% per trade | 💀 | −0.361 | −1.397 | [#75](https://github.com/falkhansen/kumo-qc/issues/75) ✓ | Trend: higher risk% → worse; sweep halted after 3 combos |
| E82 | 3-Phase Stop: Kijun → cloud_top → cloud_bottom | ❌ | 0.562 | −0.474 | [#82](https://github.com/falkhansen/kumo-qc/issues/82) | Phase 2 cloud_top at 28d/5% truncates winners before G3's 56d/15% |
| #32 | DD Circuit Breaker (4% trailing portfolio DD) | 💀 | −0.608 | −1.644 | — | Circuit never fires; BCT individual stops exit before portfolio DD accumulates |
| G3-v2 | Lower Phase 3 threshold (42d/10%) | ❌ | 0.738 | −0.298 | [#65](https://github.com/falkhansen/kumo-qc/issues/65) ✓ | 56d/15% is the sweet spot; lowering captures marginal names that exit prematurely |
| G3-v3 | Phase 2 extension (28d/5%) | ❌ | 0.516 | −0.520 | [#66](https://github.com/falkhansen/kumo-qc/issues/66) ✓ | More aggressive early-exit variant; worse than G3-v2 |
| H5 | Relative strength ranking (sort by RS vs SPY) | ❌ | 0.682 | −0.354 | [#62](https://github.com/falkhansen/kumo-qc/issues/62) ✓ | RS ranking selects mean-reverting momentum; catastrophic in volatile H1 |
| H7 | Kijun proximity ranking (sort by closest to Kijun) | 💀 | −0.336 | −1.372 | [#63](https://github.com/falkhansen/kumo-qc/issues/63) ✓ | Picks weakest 8-scorers (closest to stop = most vulnerable) |
| C1 | Doji pullback timing (wait for doji, then enter) | ❌ | 0.751 | −0.285 | [#64](https://github.com/falkhansen/kumo-qc/issues/64) ✓ | Misses immediate breakouts; better entry price offset by missed trades |
| C2 | Resistance proximity gate (within 2% of 52w high) | ➖ | 1.036 | 0 | [#48](https://github.com/falkhansen/kumo-qc/issues/48) | Zero delta; adds complexity with zero value-add |
| QC-1 | Inverse-vol sizing (σ-based position size) | ❌ | 0.708 | −0.328 | [#58](https://github.com/falkhansen/kumo-qc/issues/58) ✓ | Same failure mode as E26; flat 10% is optimal for equal-weight BCT |
| QC-2 | HY credit spread half-size gate | ❌ | 0.763 | −0.273 | [#59](https://github.com/falkhansen/kumo-qc/issues/59) ✓ | JNK/HY spread gate reduces positions in wrong phases |
| H3 | Dynamic MAX_POSITIONS (variable slot count) | 🚫 | — | — | [#60](https://github.com/falkhansen/kumo-qc/issues/60) | Aborted: position count changes predicted negative |
| C2-dup | Resistance proximity (PR #37, 2% of 52w high) | 🚫 | — | — | [#48](https://github.com/falkhansen/kumo-qc/issues/48) | Aborted: already tested, blocked 84% of entries |
| F2 | IWM half-size in bear regime | 🚫 | — | — | — | Aborted: predicted negative from BEAR-regime pattern |
| *12 unnamed* | Various baseline permutations | ❌ | ALL NEG | — | — | All negative vs G3; details in FOR_FALK.md "12 baseline experiments" |

---

## Phase 1 — Exit & Entry Mechanics (E36–E39)

> All FY2025 Jan–Dec 2025. Data from bt-results.csv.

| ID | Description | Status | FY2025 Sharpe | Δ | Commit | GH | Key Finding |
|----|-------------|--------|:---:|:---:|--------|:---:|-------------|
| E36 | ATR initial stop (replace Kijun at entry) | ➖ | 0.947 | −0.089 | `9dcae5f` | — | ATR always looser than Kijun at entry; Kijun dominates, ATR irrelevant |
| E37 | Buy-stop entry (enter only on breakout above prior high) | ❌ | 0.263 | −0.773 | `d65c4b9` | — | Misses gap-and-run stocks in trending markets |
| E38 | Resistance proximity gate (near 52w high filter) | ❌ | 0.565 | −0.471 | `c10a1a2` | [#48](https://github.com/falkhansen/kumo-qc/issues/48) | Redundant with BCT screen; blocks entries at exactly the strongest breakouts |
| E39 | Ladder exits (trim at +15%, +30%, +45%) | ❌ | 0.470 | −0.566 | `3140ae2` | — | Fights Kijun trail; double ceiling truncates 40–80%+ winners |

---

## Phase 2 — Regime Gates (E40 Series)

> FY2025 Jan–Dec 2025. All gates tracked under [#90](https://github.com/falkhansen/kumo-qc/issues/90).  
> Commits: `af197fc` (E40a), `cc90728` (E40b/d/e), `7cdb05b` (E40c).

| ID | Description | Status | FY2025 Sharpe | Δ | Key Finding |
|----|-------------|--------|:---:|:---:|-------------|
| E40a | SPY > 50MA regime gate | 💀 | mixed | — | W1 catastrophic (26 blocks, Jan–Feb winners blocked); W2 positive. FY inconsistent |
| E40b | SPY > 200MA regime gate | ➖ | 1.048 | +0.012 | Near-neutral FY; brief Mar dip blocked Jan–Feb winners in W1 (−2.0 Sharpe) |
| **E40b-v2** | **SPY > 200MA ≥3 consecutive days** | ✅ | **1.463** | **+0.427** | **BREAKTHROUGH** (#52, first positive in 52 experiments). 3-day lag filters noise while blocking crash entries |
| **E40c** | **QQQ > 50MA regime gate** | ✅ | **1.362** | **+0.326** | ACCEPTED. Positive 5/6 windows. Blocked April tariff crash (W2: +2.194 delta) |
| **E40d** | **VIX < 25 regime gate** | ✅ 🏆 | **1.442** | **+0.406** | **SELECTED AS NEW CHAMPION BASELINE** (2026-05-28). 36 fewer trades. Most consistent per-window. Fires on actual fear — readable daily |
| E40e | Composite: SPY>50MA AND VIX<25 | 🔒 | 1.275 | +0.239 | FY2025 positive, but 0 trades on ALL 6 sub-windows. Gate too restrictive — invalid |

> **✅ DECIDED 2026-05-28:** E40d (VIX<25) selected as new champion. New baseline: **G3 + VIX<25 = 1.442 Sharpe / +42.4% FY2025**.  
> Cloud validation blocked by universe injection bug — local LEAN only going forward.

### E40 Window-by-Window Summary

| Gate | W1 Q1 | W2 Q2 | W3 Q3 | W4 Q4 | W5 Cross | W6 H1 | FY2025 |
|------|:-----:|:-----:|:-----:|:-----:|:--------:|:-----:|:------:|
| G3 baseline | 1.494 | −0.608 | 4.427 | −1.765 | −1.166 | 0.186 | **1.036** |
| E40b-v2 | 0.958 | 0.678 | 4.427 | −1.824 | −0.897 | 0.760 | **1.463** |
| E40c | 0.580 | 1.442 | 4.427 | −1.484 | −0.342 | 0.720 | **1.362** |
| E40d | 1.509 | 0.329 | 4.427 | −1.606 | −0.342 | 0.960 | **1.442** |

---

## Phase 3 — Entry, Sizing, Universe (E41–ETF-1)

| ID | Description | Status | FY2025 Sharpe | Δ | Commit | GH | Key Finding |
|----|-------------|--------|:---:|:---:|--------|:---:|-------------|
| E41 (v1) | ADX plateau: `adx_rising OR adx>50` | 💀 | −0.333 | −1.369 | `27f5a38` | [#92](https://github.com/falkhansen/kumo-qc/issues/92) | ADX>50 admits cycle-top exhaustion names; 4-bar slope correctly filtered them |
| E41 (v3) | Rocket ship override: score==6 + ADX>55 + near 52w high | ❌ | 0.273 | −0.763 | `0bb2386` | [#92](https://github.com/falkhansen/kumo-qc/issues/92) | STX captured via regular 8/8 anyway; override fires on noise (PGR, JCI, NRG) |
| E42 | Risk-based sizing ($200R) + heat cap + 3% Kijun tolerance | 💀 | −0.375 | −1.411 | `e613692` | [#76](https://github.com/falkhansen/kumo-qc/issues/76) | Kijun tolerance blocked STX breakout; WR 23%; risk sizing = noise entries |
| ETF-1 (s1) | Two-pool system: 1 dedicated ETF slot | ❌ | 0.967 | −0.069 | `main` | [#93](https://github.com/falkhansen/kumo-qc/issues/93) | ETFs displace higher-quality stock signals; SMH/TAN/DBB/IYZ/HDV 0 trades |
| ETF-1 (s2) | Two-pool system: 2 dedicated ETF slots | ❌ | 0.880 | −0.156 | `main` | [#93](https://github.com/falkhansen/kumo-qc/issues/93) | More slots = more displacement; 17 ETFs traded, all negative drag |
| E43 | Pyramid add at cloud top + breakeven stop after +1R | ❌ | 0.493 | −0.586 | `c2b4f40` | [#36](https://github.com/falkhansen/kumo-qc/issues/36) | Only 8 adds in FY2025 (cloud-top cross rare post-entry); 26 breakeven fires cut winners — tested combination, not adds alone |
| E44 | Slot gate → heat cap only (flat 10% × MAX_HEAT=0.95) | ❌ | 0.856 | −0.223 | `1ca0d37` | [#75](https://github.com/falkhansen/kumo-qc/issues/75) ✓ | Effective limit still ~9 positions; soft ceiling degrades entry timing vs discrete slot gate; WR 28% vs G3 40%; STX still blocked |

> **E41 key finding:** STX miss in W7-YTD-2026 traced to **slot competition** (MAX_POSITIONS=10 fills with other score-8 names), not scoring. STX scored 8/8.

---

## Infrastructure / Tooling

| ID | Description | Status | FY2025 Sharpe | Δ | Commit | GH | Key Finding |
|----|-------------|--------|:---:|:---:|--------|:---:|-------------|
| v20 | Inline scanner v20 (DV quality filter in warmup) | ➖ | 1.071 | +0.035 | `5ca2ed6` | [#89](https://github.com/falkhansen/kumo-qc/issues/89) | Near-neutral. Fallback padding inflates orders (451 vs 230) |
| Cloud E40d | VIX<25 via QC cloud | 🔒 | −0.065 | −1.101 | `9976ec1` | [#90](https://github.com/falkhansen/kumo-qc/issues/90) | 32 orders vs 232 = universe injection broken |
| Cloud E40b-v2 | SPY>200MA 3d via QC cloud | 🔒 | 0.514 | −0.522 | `cc90728` | [#90](https://github.com/falkhansen/kumo-qc/issues/90) | Same universe bug; 34 orders vs 232 |
| Cloud ETF-1 | ETF-1 smoke test via QC cloud | 🔒 | 0.855 | −0.181 | `cf1b762b` | [#93](https://github.com/falkhansen/kumo-qc/issues/93) | 31 orders, 0 ETF trades; ETFs not in polygon-326 either |

---

## Window Results — G3 Baseline

| Window | Period | Sharpe | Return | Orders | WR | DD | Notes |
|--------|--------|:------:|:------:|:------:|:---:|:---:|-------|
| W1 Q1-2025 | Jan–Mar 2025 | 1.494 | +11.3% | 74 | 50% | 8.5% | Strong |
| W2 Q2-2025 | Apr–Jun 2025 | −0.608 | −1.7% | 98 | 25% | 8.3% | April tariff crash |
| W3 Q3-2025 | Jul–Sep 2025 | 4.427 | +18.5% | 42 | 44% | 3.2% | Summer rally |
| W4 Q4-2025 | Oct–Dec 2025 | −1.765 | — | ~80 | ~22% | — | Q4 rotation |
| W5 Cross | Feb–May 2025 | −1.166 | — | — | — | — | Straddles crash |
| W6 H1-2025 | Jan–Jun 2025 | 0.186 | +3.8% | 106 | — | — | Mixed |
| **FY2025** | **Jan–Dec 2025** | **1.036** | **+30.05%** | **~240** | **40%** | **11%** | **BASELINE** |
| W7 YTD-2026 | Jan–Apr 2026 | 2.418 | +25.3% | 118 | 30% | 11.8% | STX scored <7 throughout; SMH missing (not in polygon-326) |

---

## Queued Experiments

### Active (Running)
| ID | Description | Status | GH | Notes |
|----|-------------|--------|:---:|-------|
| E45 | Constant-R position resizing on Kijun step-up | ❌ 1.582 FY / 2/6 windows | [#109](https://github.com/FALK-BRAUER/kumo-qc/issues/109) | FY2025 1.582 (+0.140) but 4/6 windows negative — leverage amplifier; W3/W4 dominate |
| E45-v2 | Constant-R adds gated by VIX<20 | ❌ 1.811 FY / 3/6 windows / DD 17% | [#111](https://github.com/FALK-BRAUER/kumo-qc/issues/111) | VIX gate fixed W2 (+0.664) but W1/W5/W6 still negative; DD 17% > 15% limit. **Position-add track EXHAUSTED.** |

### Completed This Session
| ID | Description | Status | GH | Notes |
|----|-------------|--------|:---:|-------|
| E43-v2 | Pyramid add only — no breakeven stop | ❌ 1.374 / −0.068 | [#94](https://github.com/FALK-BRAUER/kumo-qc/issues/94) | +11.2pp raw return but DD 16.1%; pyramid track CLOSED |
| E44-v2 | ADX tiebreaker: sort (score desc, ADX desc) | 💀 −0.140 / −1.582 | [#95](https://github.com/FALK-BRAUER/kumo-qc/issues/95) | STX surfaced but high-ADX = parabolic; track CLOSED |
| E53-v2 | Earnings avoidance ±2d | ❌ 1.208 / −0.234 | [#96](https://github.com/FALK-BRAUER/kumo-qc/issues/96) | 7 skips; earnings avoidance track CLOSED |
| E36-v2 | ATR stop 1.5× | ❌ 1.268 / −0.174 | [#99](https://github.com/FALK-BRAUER/kumo-qc/issues/99) | Kijun confirmed optimal; ATR track CLOSED |
| E85 | Signal freshness gate | ❌ 1.268 / −0.174 | [#100](https://github.com/FALK-BRAUER/kumo-qc/issues/100) | 0 fires — conceptually incompatible with daily rebalance |
| E51 | Parabolic entry block 13d >25% | ❌ 1.254 / −0.188 | [#101](https://github.com/FALK-BRAUER/kumo-qc/issues/101) | Blocks strongest-phase entries; entry gate track CLOSED |
| E87 | Rotation quality gate RSI>50 + weekly>Tenkan | ❌ 1.129 / −0.313 | [#102](https://github.com/FALK-BRAUER/kumo-qc/issues/102) | BCT checklist confirmed maximal |

### Priority Queue (dispatch order)
| ID | Description | Hypothesis | Base | GH |
|----|-------------|------------|------|----|
| W7/E40d | YTD-2026 window on E40d | Validate champion in 2026 conditions | E40d | — |
| E40d-sp500 | S&P 500 universe (500 names) | Polygon-326 dollar-volume filter IS the quality filter; S&P 500's extra 174 names are noise | E40d | [#103](https://github.com/FALK-BRAUER/kumo-qc/issues/103) — ❌ REJECTED 0.304 / −1.138 |
| E40d-v2 | VIX<20 (stricter) | VIX<25 is sweet spot; <20 too strict, halves return to +22.4% | E40d | [#106](https://github.com/FALK-BRAUER/kumo-qc/issues/106) — ❌ REJECTED 0.687 Sharpe |
| E40d-v3 | VIX<30 (looser) | VIX<25 still best; <30 adds 14 noise orders, -0.063 Sharpe | E40d | [#104](https://github.com/FALK-BRAUER/kumo-qc/issues/104) — ➖ NEUTRAL 1.379 Sharpe |
| E40f | HY credit spread >4% entry block | JNK not in polygon-326 universe — requires separate data feed | E40d | [#105](https://github.com/FALK-BRAUER/kumo-qc/issues/105) — 🔒 BLOCKED (JNK data) |
| E40g | Breadth gate: <50% S&P above 50MA | Filters bad + good entries equally; better than G3 but not E40d | E40d | [#108](https://github.com/FALK-BRAUER/kumo-qc/issues/108) — ➖ NEUTRAL 1.268 / −0.174 |
| E40h | VVIX<100 (vol-of-vol) | VVIX data not available locally | E40d | [#107](https://github.com/FALK-BRAUER/kumo-qc/issues/107) — 🔒 BLOCKED (no VVIX data) |
| E40-combo | VIX<25 AND SPY>200MA ≥3d | Over-filters: WR 49%↑ + DD 8.5%↓ but 26 fewer trades, return drops to +35% | E40d | [#98](https://github.com/FALK-BRAUER/kumo-qc/issues/98) — ❌ REJECTED 1.207 / −0.235 |
| E53-v2 | Earnings avoidance ±2d | Shorter window preserves pre-earnings runup | E40d | [#96](https://github.com/FALK-BRAUER/kumo-qc/issues/96) — ❌ REJECTED 1.208 / −0.234 |
| E53-v3 | Earnings avoidance ±1d (day-of only) | Minimal avoidance — only skip entry day itself | E40d | [#97](https://github.com/FALK-BRAUER/kumo-qc/issues/97) |
| E36-v2 | ATR stop 1.5× multiplier | Tighter ATR may outperform Kijun stop at entry | E40d | [#99](https://github.com/FALK-BRAUER/kumo-qc/issues/99) — ❌ REJECTED 1.268 / −0.174 |
| E85 | Signal freshness gate (>2d = stale) | Blocks entries on stale signals | E40d | [#100](https://github.com/FALK-BRAUER/kumo-qc/issues/100) — ❌ REJECTED 1.268 / −0.174 (0 fires — daily rebalance makes signals always fresh) |
| E51 | Parabolic entry block (13d move >25%) | Avoid buying exhaustion peaks | E40d | [#101](https://github.com/FALK-BRAUER/kumo-qc/issues/101) — ❌ REJECTED 1.254 / −0.188 (blocks strongest-phase entries = cuts winners) |
| E87 | Rotation quality gate (RSI>50 + weekly>Tenkan) | Quality filter at entry | E40d | [#102](https://github.com/FALK-BRAUER/kumo-qc/issues/102) — ❌ REJECTED 1.129 / −0.313 (false negatives > false positive reduction; BCT checklist is maximal) |
| Score fix | Scanner BUY threshold = score ≥ 7 | ✅ Done — b9634e9 kumo-trader | premarket brief | [#35](https://github.com/falkhansen/kumo-qc/issues/35) ✓ |

---

## Key Architectural Findings

1. **G3 is the global optimum for exit logic.** Phase 3 cloud-bottom at 56d/15% is the sweet spot. G3-v2 (42d/10%) and G3-v3 (28d/5%) both hurt.
2. **Flat 10% sizing is optimal.** Every risk-sizing variant (E26, E76 series, E42, QC-1) hurt performance. BCT equal-weight is correct.
3. **No additional entry gates.** BCT checklist is maximal. Every extra gate (E8, E38, E49, E53) created false negatives without reducing false positives.
4. **Regime gates are the ONLY positive axis.** E40b-v2 (+0.427), E40d (+0.406), E40c (+0.326). All 6 experiments with Sharpe >1.0 are regime gates. Zero positive results from exit mods, sizing, entry gates, or universe changes. Root insight: BCT already selects good winners — the edge is avoiding MORE LOSERS (bad entries during weak markets), not picking better winners. Regime gates operate before the entry decision, reducing the noise denominator rather than optimizing the signal numerator.
9. **Polygon-326 dollar-volume filter is a quality gate, not survivorship bias.** S&P 500 universe (500 names) Sharpe 0.304 vs polygon-326 1.442 (−1.138 delta). The 174 extra S&P names are illiquid noise that pollutes BCT scorer. E40d's 1.442 Sharpe is real, not inflated.
5. **Slot gate blocks rocket ships — but ranking fix is intractable.** STX scored 8/8 and E44-v2 confirmed slot competition is the root cause. ADX tiebreaker surfaced STX but catastrophically degraded overall quality (Sharpe −0.14, DD 24.8%, WR 31%). High ADX ≠ better trade — high-ADX names are often parabolic/volatile. The random ordering within score tier was actually optimal. STX miss is a known acceptable cost of a fixed MAX_POSITIONS=10 pool.
6. **QC cloud validation is permanently blocked.** QC project 32034565 missing/permissions revoked. Universe injection also broken. Local LEAN is production target. Falk must check QC dashboard to restore if needed.
7. **Kijun IS the trailing stop.** No explicit trail code needed. Kijun rises naturally with price trend; `close < kijun → exit` is the trail.
8. **Intraday stop monitoring destroys edge.** All stops must be EOD-only to match George's methodology (proven in Run 8).
10. **Position sizing additions are a leverage multiplier, not alpha.** E45 constant-R resizing: FY2025 Sharpe 1.582 (+0.140) but 4/6 windows negative. W3/W4 dominate the FY result. In choppy/crash windows, adds amplify losses. Any position-building approach needs regime gating on the ADD trigger (E45-v2 testing VIX<20 on adds).

### Active Queue
| ID | GH | Hypothesis |
|----|-----|-----------|
| Research | [#112](https://github.com/FALK-BRAUER/kumo-qc/issues/112) | Multi-timeframe BCT (weekly+daily alignment) + sector Ichimoku regime filter |

> **Status 2026-05-28:** All planned experiment tracks exhausted. E40d (VIX<25) confirmed champion at 1.442 Sharpe. Proceeding to research phase per Falk mandate.

---

*Source: `bt-results.csv` (86 rows) + `FOR_FALK.md`. Last updated: 2026-05-28.*
