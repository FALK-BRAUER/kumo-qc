# Risk-Based Sizing Model Analysis (Track D Prep)

## Executive Summary

Three risk-sizing experiments were attempted in the kumo-qc pipeline. The most recent and complete model is **E89** (commit 4ad8288), which implements fixed-dollar-risk sizing with Kijun-based stop distance, position-level caps, and portfolio heat caps. All variants were **REJECTED** compared to flat 10% allocation, but the model is well-specified and could be revisited with parameter tuning.

---

## 1. E34: Heat-Per-Slot Sizing (Commit 436fc31)

### Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `heat_per_slot` | string/float | `"false"` | Risk budget as fraction of equity per slot. Use `"false"` for flat sizing. |

### Formula
```python
# Enable:
heat_per_slot = 0.01  # 1% of equity at risk per position

# Risk budget
equity = self.portfolio.total_portfolio_value
risk_budget = equity * heat_per_slot  # e.g., $1,000 on $100K equity

# Stop distance (Kijun)
vals = self._daily_vals(symbol)
kijun_at_entry = float(vals[1])  # Kijun value from Ichimoku
stop_distance = price - kijun_at_entry

# Shares
if stop_distance > 0:
    quantity = int(risk_budget / stop_distance)
else:
    quantity = int(equity * POSITION_PCT / price)  # fallback to flat 10%
```

### Key Design
- **Risk source**: Equity × heat_per_slot
- **Stop anchor**: Daily Kijun (Ichimoku base line)
- **Fallback**: Flat 10% if Kijun >= entry price (stop_distance <= 0)
- **Position meta**: Caches `entry_kijun` for downstream use

### Result
- FY2025: **0.525 Sharpe** / +22.44%
- Baseline (flat 10%): 1.079 Sharpe / +33.33%
- **Conclusion**: Flat 10% allocation dominates

---

## 2. Risk-Based Sizing + Cash Cap (Commit 5a56c4c)

This is an **extension of E34** that adds a cash availability guard.

### Formula (E34 base + caps)
```python
quantity = int(risk_dollars / stop_distance)

# Cap 1: Max 20% of equity per position
max_qty_pct = int(equity * 0.20 / price)

# Cap 2: Available cash (leave 5% buffer for fills)
available_cash = self.portfolio.cash * 0.95
max_qty_cash = int(available_cash / price)

quantity = min(quantity, max_qty_pct, max_qty_cash)
```

### Problem Solved
Risk-based sizing + heat cap tracks **risk dollars**, not total capital deployed. With a tight stop (small `stop_distance`), a $20K position may have only ~$400 at risk — many such positions fit within the heat cap but **exhaust cash simultaneously**.

### Key Design
- Adds `cash * 0.95 / price` as third constraint
- Prevents "heat OK, cash exhausted" scenarios

---

## 3. E89: Unlimited Slots + Fixed Risk + Heat Cap (Commit 4ad8288)

The most sophisticated model. Removes `MAX_POSITIONS` entirely; governs exposure via heat cap alone.

### Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `RISK_AMOUNT` | float | `200.0` | Fixed dollar risk per trade ($200) |
| `MAX_POSITION_PCT` | float | `0.15` | Max 15% NLV per position |
| `HEAT_CAP` | float | `0.90` | Stop adding positions at 90% NLV deployed |

### Formula
```python
# 1. Calculate current heat (deployed capital)
total_value = self.portfolio.total_portfolio_value
current_heat = sum(
    h.quantity * self.securities[sym].price
    for sym, h in self.portfolio.items()
    if h.invested
) / total_value

# 2. Heat cap check — abort rebalance if at limit
if current_heat >= HEAT_CAP:
    return  # no new entries

# 3. Per-position sizing
kijun_distance = abs(price - kijun)
if kijun_distance > 0:
    # Risk-based: $200 risk / stop distance * price = position value
    risk_based_value = RISK_AMOUNT / kijun_distance * price
else:
    # Fallback: max position percentage
    risk_based_value = total_value * MAX_POSITION_PCT

# 4. Cap at 15% NLV per position
max_position_value = total_value * MAX_POSITION_PCT
target_value = min(risk_based_value, max_position_value)

# 5. Heat cap check per candidate
projected_heat = running_heat + (target_value / total_value)
if projected_heat > HEAT_CAP:
    continue  # skip this candidate

# 6. Execute
quantity = int(target_value / price)
running_heat = projected_heat
```

### Key Design
- **No MAX_POSITIONS**: Unlimited slots, heat governs capacity
- **Fixed dollar risk**: $200 per trade (not equity percentage)
- **Stop anchor**: Daily Kijun
- **Two-level heat cap**: 
  - Pre-rebalance abort (90% NLV)
  - Per-candidate skip (accumulated heat)
- **Metrics tracking**: `_daily_positions`, `_daily_heat` arrays

### Result
- **CATASTROPHIC REJECTION** (commit message)
- Removed MAX_POSITIONS=10, added 90% heat cap — resulted in worse performance than baseline

---

## 4. Cherry-Pick Assessment onto Current Main (fe16d3d)

### Cleanliness: MODERATE

**E89 (4ad8288) conflicts expected with current main:**

1. **Removed features**: E89 strips out E40d SPY regime gate, E51 parabolic block, E28 VIX percentile, E121 VIX Ichimoku 2-tier — all of which are ON in current main. A cherry-pick would need manual conflict resolution.

2. **Position meta**: E89 extends `_position_meta` with `entry_kijun`. Current main does not have this field — safe to add.

3. **Sizing block**: The entry-sizing code block (lines ~520-580) is heavily modified in E89 vs. current main's committed_cash + flat 10% + dollar-volume tiebreak. Would need careful merge.

4. **Rebalance logging**: E89 changes `REBALANCE` log format to include heat metrics. Current main has different log format.

**Recommended approach**: Do NOT cherry-pick. Instead, re-implement E89's three constants (`RISK_AMOUNT`, `MAX_POSITION_PCT`, `HEAT_CAP`) and the `target_value` formula as a **parameterized opt-in** in current main, similar to how E34's `heat_per_slot` works.

---

## 5. Parameter Reference

| Config | `heat_per_slot` (E34) | `RISK_AMOUNT` (E89) |
|--------|----------------------|---------------------|
| Conservative | 0.005 (0.5% equity) | $100 |
| Moderate | 0.01 (1% equity) | $200 |
| Aggressive | 0.02 (2% equity) | $500 |

**No ATR usage**: All three models use **Kijun** as stop distance, not ATR. No ATR-based sizing was attempted in the committed experiments (though `feat/e26-inverse-vol-sizing` exists as a separate branch).

---

## 6. Track D Recommendation

If re-evaluating risk-based sizing for Track D:

1. **Start with E34's `heat_per_slot`**: It is already parameterized and opt-in — safest to test
2. **Parameter sweep**: Try `heat_per_slot = 0.005, 0.01, 0.02` (conservative → aggressive)
3. **Cash cap**: Always include the `min(qty, cash_cap)` guard from commit 5a56c4c
4. **E89's fixed-dollar model**: Requires more invasive surgery; only if E34 shows promise
5. **ATR alternative**: Consider `feat/e26-inverse-vol-sizing` if Kijun-based stops prove too tight

---

*Generated: 2026-05-29*
*Worker: mwabfyxz*
*Sources: commits 436fc31 (E34), 5a56c4c (cash cap), 4ad8288 (E89)*
