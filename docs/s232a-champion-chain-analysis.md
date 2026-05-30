# s232a Champion Chain — Full Analysis

*Source: kumo-trader sim sprint May 2026. Pop Sharpe = mean(W1..W6) / stdev(W1..W6).*
*JSON configs are ground truth. Sprint narrative in sprint-may2026-top10-analysis.md diverges in places — see notes.*

---

## Quick Reference: The Chain

| Rank | Sim | Pop Sharpe | FY Return | Trades | Win Rate | Delta from prev |
|------|-----|-----------|-----------|--------|----------|-----------------|
| 10 | s171a | 0.9934 | +47.58% | 520T | 50.6% | `rotation.score_ratio_threshold: 2.0` |
| 9 | s169a | 1.3147 | +36.93% | 412T | 53.4% | `resistance_proximity_pct: 3.0 → 5.0` |
| 8 | s186a | 1.5629 | +44.73% | 413T | 53.3% | `ladder_rungs: [10,20] → [15,30]` |
| 7 | s189a | 1.7650 | +50.46% | 413T | 53.3% | `ladder_rungs: [15,30] → [20,40]` |
| 6 | s194a | 1.7825 | +45.75% | 413T | 53.3% | `ladder_trim_fraction: 0.33 → 0.50` |
| 5 | s210a | 2.0092 | +45.75% | 413T | 53.3% | `reversal_profit_min_gain: 0.10 → 0.08` |
| 4 | s213a | 3.3199 | +47.31% | 416T | 53.6% | `reversal_profit_extension: 0.15 → 0.10` |
| 3 | s215a | 3.7643 | +47.22% | 418T | 53.6% | `reversal_profit_min_gain: 0.08 → 0.06` |
| 2 | s226a | 3.9791 | +46.31% | 418T | 53.6% | `vix_size_tier_multiplier: 0.75 → 0.50` |
| 1 | **s232a** | **4.8207** | **+45.09%** | 412T | 52.9% | `earnings_exit_days_before: 5 → 3` |

**Pattern:** FY return barely moves across the chain (+47% to +45%). Pop Sharpe multiplied 4.8×. The sprint optimized *consistency*, not mean return.

---

## Base Configuration (present in all sims)

Before any sprint changes, the base already contained:

```
entry:
  min_scanner_rating: "++"
  fill_method: t1_open          # next-day open fill
  min_adx: 20
  weekly_cloud_veto: true
  require_di_positive: true
  kijun_extension_block: true   # max ratio 0.20
  kijun_extension_max_ratio: 0.2
  require_chikou: true
  resistance_proximity_block: true
  resistance_proximity_pct: 3.0
  skip_if_earnings_within_days: 5
  min_volume_ratio: 1.0
  min_price: 3.0
  min_dollar_volume: 500000

sizing:
  method: fixed_risk
  max_risk_dollars: 200
  max_position_pct_of_account: 10%

stop:
  initial: 2.5× ATR
  trail: kijun − 3.0× ATR (22-period)
  trail_to_tenkan_first: true
  never_lower_stop: true
  close_only: true

adds:
  enabled: true
  trigger: cloud_top_break (+0.1% clearance, ≤3% extension)
  size: 50% of original
  max_adds: 1
  require_profitable: true

exit:
  ladder: [10%, 20%] rungs, 33% trim per rung
  earnings_exit_days_before: 5
  adaptive_earnings_exit: 9 days / ≥12% gain
  reversal_profit_exit: gain ≥ 10%, extension ≥ 15% (spinning top OR bearish engulfing)

pyramid:
  enabled: true
  size: 50% of original, 20-period ATR

rotation:
  profit_veto_pct: 5%
  score_ratio_threshold: (not yet set)
  max_correlation: 1.0

regime:
  spy_gate_confirm_days: 4
  vix_size_tier: VIX > 30 → 0.75× size
```

> **Sprint narrative discrepancy:** The sprint analysis says s171a "introduced spy_gate_confirm_days:4" and s169a "added kijun_extension_block + require_chikou". The JSONs show all three were already present before s171a. The narrative describes cumulative effects, not single-change attribution. JSON deltas below are the real diffs.

---

## s171a — Pop Sharpe 0.9934 (+47.58% / 520T / 50.6% WR)

**JSON delta from base (s155a):**
```diff
+ rotation.score_ratio_threshold: 2.0
```

**What it does:** Rotation now requires a challenger to score ≥ 2× the held position's signal score before displacing it. Without this, any marginally better signal triggers a rotation, causing churn.

**Observation:** Highest trade count (520T) of the chain. Score ratio alone doesn't reduce trades enough — entries are still plentiful. Win rate (50.6%) lowest of the chain — rotation is still pulling out positions prematurely.

---

## s169a — Pop Sharpe 1.3147 (+36.93% / 412T / 53.4% WR)

**JSON delta from s171a:**
```diff
entry.resistance_proximity_pct: 3.0 → 5.0
```

**What it does:** Widens the resistance exclusion zone from 3% to 5%. If price is within 5% of a known resistance level, entry is blocked. More setups are rejected at the gate.

**Observation:** Biggest trade count drop in the chain: 520T → 412T (−21%). Win rate jumps from 50.6% to 53.4% — the extra exclusion is removing genuinely marginal entries. But FY return also drops sharply (+47.58% → +36.93%) — the filter is cutting some winners along with the losers. Net effect: better quality, lower raw return, better consistency.

> **Sprint narrative says:** "s169a added kijun_extension_block + require_chikou". Both were already in the base. The actual change was resistance proximity.

---

## s186a — Pop Sharpe 1.5629 (+44.73% / 413T / 53.3% WR)

**JSON delta from s169a:**
```diff
exit.ladder_rungs_pct: [10, 20] → [15, 30]
```

**What it does:** Ladder trim triggers move from +10%/+20% to +15%/+30%. Positions are held longer before partial profit-taking fires. 33% trim per rung unchanged.

**Observation:** FY return recovers from +36.93% to +44.73% — holding longer before trimming captures more of winners. Trade count essentially unchanged (412→413). Win rate stable. The earlier [10,20] rungs were trimming too early, cutting into the large-winner distribution.

> **Sprint narrative says:** "s186a enabled adds + pyramid". Both were already in the base. The actual change was ladder rungs.

---

## s189a — Pop Sharpe 1.7650 (+50.46% / 413T / 53.3% WR)

**JSON delta from s186a:**
```diff
exit.ladder_rungs_pct: [15, 30] → [20, 40]
```

**What it does:** Ladder rungs widen further to +20%/+40%. Positions must run further before any trim fires.

**Observation:** Highest FY return in the entire chain at +50.46%. Holding to +20% and +40% before trimming keeps the maximum in winners. The downside is higher variance — if a position at +18% reverses, you give more back than at the [15,30] setting. This is where the reversal exit becomes load-bearing.

> **Sprint narrative says:** "s189a confirmed trail_atr_multiplier:3.0". Trail was already 3.0 in the base. The actual change was ladder rungs.

---

## s194a — Pop Sharpe 1.7825 (+45.75% / 413T / 53.3% WR)

**JSON delta from s189a:**
```diff
exit.ladder_trim_fraction: 0.33 → 0.50
```

**What it does:** Each ladder rung now trims 50% of remaining position (up from 33%). At +20%, half the position closes. At +40%, half of what remains closes. Net: smaller residual position at higher prices.

**Observation:** FY return drops from +50.46% to +45.75% — trimming more at each rung converts more unrealized gain to realized, reducing the tail of the distribution. Pop Sharpe improves only marginally (+0.02). The trim fraction is a variance-mean tradeoff; this setting reduces variance at the cost of upside.

> **Sprint narrative says:** "s194a added resistance_proximity_block at 5%". That was already in s169a. The actual change was trim fraction.

---

## s210a — Pop Sharpe 2.0092 (+45.75% / 413T / 53.3% WR)

**JSON delta from s194a:**
```diff
exit.reversal_profit_min_gain_pct: 0.10 → 0.08
```

**What it does:** The reversal exit (spinning top or bearish engulfing when extended) now triggers when the position is +8% profitable, down from +10%. Eligible positions become eligible 2pp earlier.

**Observation:** FY return unchanged. Pop Sharpe jumps from 1.7825 → 2.0092. The reversal exit is firing on more positions that would otherwise give back gains before the kijun trail triggers. No raw return change — the exit captures the same dollars, just more reliably. First major Pop Sharpe step.

---

## s213a — Pop Sharpe 3.3199 (+47.31% / 416T / 53.6% WR)

**JSON delta from s210a:**
```diff
exit.reversal_profit_extension_pct: 0.15 → 0.10
```

**What it does:** The reversal exit extension condition drops from 15% above kijun/tenkan to 10%. A position at +8% gain that is 10% extended is now eligible (previously required 15% extension).

**Observation:** **Largest single Pop Sharpe jump in the sprint: +1.31 (2.0092 → 3.3199)**. FY return ticks up (+0.44pp). Trade count creeps up (413→416) — the tighter extension threshold causes more positions to exit on reversal signals before the kijun trail fires. W4 (bear quarter) flips positive. This is the single most impactful parameter in the chain.

---

## s215a — Pop Sharpe 3.7643 (+47.22% / 418T / 53.6% WR)

**JSON delta from s213a:**
```diff
exit.reversal_profit_min_gain_pct: 0.08 → 0.06
```

**What it does:** The gain threshold for reversal exit eligibility drops to 6%. Positions profitable at +6% (rather than +8%) can exit on a reversal candle if also sufficiently extended.

**Observation:** Pop Sharpe +0.44 (3.3199 → 3.7643). FY return essentially flat (−0.09pp). Meaningful improvement — the 8%→6% change catches positions that were reversing at modest gains before the kijun trail triggered. Line confirmed closed: 6% is the optimum gain floor.

---

## s226a — Pop Sharpe 3.9791 (+46.31% / 418T / 53.6% WR)

**JSON delta from s215a:**
```diff
regime.vix_size_tier_multiplier: 0.75 → 0.50
```

**What it does:** When VIX > 30, position size is halved (50% of normal risk dollars) rather than reduced to 75%. High-volatility entries take less capital.

**Observation:** Pop Sharpe +0.21 (3.7643 → 3.9791). FY return drops −0.91pp — smaller positions in volatile periods mean smaller wins in recoveries too. Stdev drops: variance compressed. W2 (high-VIX tariff quarter): mean slightly lower, variance lower. The ATR-based sizing underestimates regime risk during VIX spikes; this is a regime-level override.

Sweep confirmed: VIX=30 threshold optimal (25 over-triggers, 35 under-triggers). Multiplier=0.50 optimal (0.25 too aggressive, 0.75 too mild).

---

## s232a — Pop Sharpe 4.8207 (+45.09% / 412T / 52.9% WR) ← CHAMPION

**JSON delta from s226a:**
```diff
exit.earnings_exit_days_before: 5 → 3
```

**What it does:** Hard earnings exit window narrows from 5 days to 3 days. Positions are held 2 additional days into the pre-earnings drift before mandatory close. The adaptive earnings exit (9 days / ≥12% gain) is unchanged.

**Observation:** **Pop Sharpe +0.84 (3.9791 → 4.8207) — the second largest jump in the chain.** FY return barely changes (−1.22pp). Stdev drops to 0.898% — tightest in the sprint. W4 (bear): +2.69% (vs +1.88% in s226a). The 5-day window was cutting positions during the "drift into earnings" phase — the last 2 days of a pre-earnings move are often the strongest. Holding those 2 extra days reduces forced exits in momentum windows, compressing variance.

Dimension closed:
| Days | Pop Sharpe |
|------|-----------|
| 7 | 2.2712 |
| 5 | 3.9791 |
| **3** | **4.8207** |
| 2 | 4.1968 |

---

## Full s232a Config (final champion)

```json
entry:
  min_scanner_rating: "++"
  fill_method: t1_open
  min_adx: 20
  weekly_cloud_veto: true
  require_di_positive: true
  kijun_extension_block: true (max_ratio: 0.20)
  require_chikou: true
  resistance_proximity_block: true, 5%
  skip_if_earnings_within_days: 5      ← entry skip KEPT at 5d
  min_volume_ratio: 1.0
  min_price: 3.0, min_dollar_volume: 500k

sizing:
  fixed_risk: $200 max, 10% account cap

stop:
  initial: 2.5× ATR
  trail: kijun − 3.0× ATR (22-period)
  trail_to_tenkan_first: true
  never_lower_stop: true, close_only: true

adds:
  cloud_top_break, 50% of original, max 1 add, require profitable

exit:
  ladder: [20%, 40%] rungs, 50% trim each
  reversal_profit: gain ≥ 6% AND extension ≥ 10% → exit on spinning top / bearish engulfing
  earnings_exit_days_before: 3          ← hard exit 3d before
  adaptive_earnings_exit: ≥12% gain AND ≤9d before → exit
  (no weekly_cloud_breach_exit in these JSONs — added later in sT10e)

pyramid:
  50% of original, 20-period ATR

rotation:
  score_ratio_threshold: 2.0
  profit_veto_pct: 5%

regime:
  spy_gate_confirm_days: 4
  vix_size_tier: VIX > 30 → 0.50× size
```

---

## Code vs Config: What Actually Runs (decision_engine.py)

> These notes are from reading the implementation, not just the JSON.

### `skip_if_earnings_within_days: 5` — entry skip
**NOT a hard block in decision_engine.py.** The parameter appears in one place:
```python
# decision_engine.py:680 — inside earnings_proximity_size_reduction_enabled block only
_skip_d = int(entry_cfg.get('skip_if_earnings_within_days', 5))
if _d2e is not None and _d2e > _skip_d:
    shares = max(1, int(shares * _ep_mult))  # size reduction only when > skip_d
```
The actual hard entry block lives in **loop.py:854** — a pre-filter on the candidates list before `evaluate_entry` is called:
```python
skip_days = int(cfg.get('entry', {}).get('skip_if_earnings_within_days', 0))
if skip_days > 0:
    # SQL: exclude tickers with earnings in next skip_days days
```
So `skip_if_earnings_within_days` IS a hard entry block — but it's enforced in the paper/live loop, not in decision_engine. The sim (simulate_strategy.py) does not call this path — it calls `_candidates()` and `run_backtest()` directly. **This means the entry skip may not have been active during the sprint sims.** The sprint results may reflect NO entry skip even though the config says 5 days.

### Reversal exit — `_is_reversal_candle()` (decision_engine.py:1657)
```python
body = abs(c - o)
rng  = h - l
if rng > 0 and body < body_ratio * rng:   # spinning top (default: body < 35% of range)
    return True
if prev is not None:
    if c < o and o >= prev_c and c <= prev_o:  # bearish engulfing
        return True
```
Condition to fire: `gain >= min_gain_pct` AND `(price / tenkan - 1 >= ext_pct OR price / kijun - 1 >= ext_pct)` AND reversal candle present.

### Earnings exits — order of evaluation (decision_engine.py:122–143)
1. **Adaptive** fires first: `gain >= 12%` AND `earnings_within(9d)` → EXIT
2. **Hard** fires second: `earnings_within(3d)` → EXIT (always, regardless of gain)

### VIX sizing — real-time close of `^VIX` ticker (decision_engine.py:722–730)
Uses `_get_latest_close('^VIX', signal_db, today)` — needs VIX OHLCV in the signal DB. If `^VIX` data is absent, multiplier never fires (silent fail).

### Kijun trail — `never_lower_stop: true` enforcement
Stop ratchets up but never down. `close_only: true` means stop checked against daily close, not intraday low. ATR trail = `kijun - 3.0 × ATR(22)`.

### Resistance proximity — 52-week high only (decision_engine.py:619–627)
```python
prior_high = candidate.get('prior_high_52w')
distance_pct = (prior_high - current_price) / prior_high * 100
if distance_pct < prox_pct:  # price within 5% of 52wH → skip
```
Only checks 52-week high. No intraday resistance levels or prior breakout levels despite the JSON description saying "52-week high, prior breakout level, key chart level."

---

## Key Observations for kumo-qc Port

1. **Sprint optimized consistency, not return.** FY return range: +45–50%. Pop Sharpe range: 1.0–4.8. The features that mattered most were exit precision (reversal exit parameters) and variance suppression (VIX sizing, earnings window).

2. **Reversal exit is the pivotal mechanism.** The two parameter tunes (extension 0.15→0.10, gain 0.10→0.06) together account for +2.77 Pop Sharpe (+1.31 + +0.44 + +0.44). Nothing else comes close. Without it, Pop Sharpe peaks at ~2.0.

3. **Ladder rungs [20,40] + 50% trim are non-obvious.** [10,20] was correct direction but too early. [15,30] was better. [20,40] maximizes winners. The trim fraction of 50% converts enough to realized that variance compresses.

4. **Entry skip at 5 days may not have fired during sprint sims.** The `skip_if_earnings_within_days` hard block lives in `loop.py` (paper/live path), not in `simulate_strategy.py` (sim path). Sprint results may show no entry skipping even though the config says 5d. Separate legs: if the sim DID skip entries, the 3d exit window captures the drift without risking the event.

5. **performance_bct G3 baseline is missing:** reversal exit, ladder, ATR initial stop, VIX halving. These explain the Sharpe gap (G3: 1.079 vs s232a: Pop 4.8). The reversal exit alone is likely worth +2 Pop Sharpe if ported correctly.

6. **sT10e (the sT10e+R-B-v3 champion) differs from s232a** in `fill_method` (t1_open → buy_stop close+0.75%), `resistance_proximity_pct` (5% → 3%), and rotation params. sT10e is a later iteration; s232a is the sprint endpoint.
