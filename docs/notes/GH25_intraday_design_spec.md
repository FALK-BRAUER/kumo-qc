# GH #25: Intraday QC Design Spec — Minute Bars + Tenkan Confirmation + Stop Market

## Status: APPROVED (Falk, 2026-06-01) — the canonical execution model. Implemented under epic #270.
**Supersedes:** the daily-only, market-on-open engine + the retired #262/#268 MOO-parity effort.
**Scope:** the corrected execution model (daily signal → intraday confirmed execution), NOT an optional enhancement. The daily signal stack is unchanged; the execution layer is rebuilt.

> **v2-engine reconciliation (#270).** This spec was written against the legacy oracle
> (`_rebalance`/`_check_all_entry_gates`). In the v2 phase engine it maps to:
> - §3.1 minute subscriptions → dynamic **candidate-only 5-min subscriptions** (capped) in the
>   selection gate (ARCHITECTURE.md §10; PHASES.md §1/§5).
> - §3.2 intraday-Tenkan confirmation → the **`entry_selection` intraday-confirm phase**
>   (`BctIntradayConfirm`, the LOCKED mechanic) + a **pre-flight staleness gate** as the first
>   intraday phase (PHASES.md §5). The #253 *daily* Gate-2 proxy is RETIRED.
> - §3.3 stop-market exits → the **`exit_hard` intraday stop-market** via the OrderIntent fire
>   seam (PHASES.md §15; ARCHITECTURE.md §4).
> - §3.4 intraday rebalance → the **two-clock scheduler** (`after_close_scan` daily decision +
>   the 5-min execution clock; PHASES.md §20), NOT a fixed 11:00 callback (continuous confirm).
> - The `_tenkan_confirmed` "return True on insufficient data" (§3.2 below) becomes **fail-loud /
>   loud-skip**, never a silent permissive pass (the #261/#270 fail-loud principle).
> Trigger evidence: BCT-6/H8 (≈85% of George's entries fill in the first 2h, volume-confirmed) +
> BCT-9 (validated intraday-confirmed alpha) — see research/bluecloudtrading.

---

## 1. Philosophy: Daily Signal, Intraday Execution

The BCT signal stack (8-condition weekly+daily Ichimoku scoring) remains **daily resolution**. Intraday additions are purely **execution timing and risk management** enhancements:

- **Daily signals** drive entry/exit *decisions* (which symbols, what direction)
- **Minute bars** drive entry/exit *timing* (when during the day to execute)
- **Stop market orders** replace `market_on_open()` for faster, more precise execution

---

## 2. Current Architecture (Baseline)

### Daily-Only Stack
| Component | Resolution | Trigger |
|-----------|-----------|---------|
| Ichimoku scoring | Daily (9,26,26,52,26,26) | EOD close |
| BCT 8-condition score | Daily | 16:05 rebalance |
| Entry orders | `market_on_open_order()` | Next day open |
| Stop exits | `market_on_open_order()` | Next day open |
| Ladder trims | `market_on_open_order()` | Next day open |

### Key Limitations
1. **Slippage**: All orders execute at next open — no intraday entry confirmation
2. **Stop latency**: ATR/Kijun stops checked once daily — intraday moves not caught
3. **No Tenkan confirmation**: Entry on any day that passes gates, no intraday momentum check

---

## 3. Proposed Intraday Additions

### 3.1 New Data Subscriptions

```python
# In Initialize() — add alongside daily subscriptions:
self.add_equity(symbol, Resolution.MINUTE)  # Per-symbol minute data
```

**Constraint**: Only subscribe minute data for **active candidates** (top N by score), not full universe. Prevents memory/data overload.

**Candidate selection**: After daily scoring in `_rebalance()`, subscribe minute data for:
- Current portfolio positions (10 max)
- Top 20 non-held candidates by score
- SPY (for benchmark + SPY gate)

### 3.2 Tenkan Confirmation (Entry Timing)

**Concept**: After daily signal says "enter", wait for intraday price to confirm above Tenkan line before submitting order.

```python
def _tenkan_confirmed(self, symbol: Symbol) -> bool:
    """Intraday confirmation: current price > minute Tenkan-sen (9-period midpoint)."""
    # Fetch 10 minutes of 1-min bars (enough for 9-period Tenkan)
    hist = self.history(symbol, 10, Resolution.MINUTE)
    if hist is None or len(hist) < 9:
        return True  # Permissive if insufficient data
    
    highs = hist['high'].values
    lows = hist['low'].values
    tenkan_1m = (max(highs[-9:]) + min(lows[-9:])) / 2.0
    current_price = float(self.securities[symbol].price)
    
    return current_price > tenkan_1m
```

**Integration in entry flow**:
1. Daily rebalance selects candidates (existing logic)
2. For each candidate, call `_tenkan_confirmed()` before placing order
3. If confirmed: place `stop_market_order()` immediately (not `market_on_open`)
4. If not confirmed: defer to next minute check (via scheduled callback or OnData)

### 3.3 Stop Market Orders (Exit Execution)

Replace `market_on_open_order()` for exits with `stop_market_order()` for immediate execution:

```python
# Current (daily):
self.market_on_open_order(symbol, -holding.quantity)

# Proposed (intraday):
stop_price = self._get_position_stop_price(symbol)  # Existing ATR/Kijun stop
self.stop_market_order(symbol, -holding.quantity, stop_price)
```

**Benefits**:
- Stop exits fire **during the day** when price hits level, not next morning
- Reduces overnight gap risk on stop breaks
- Maintains same stop calculation logic (no changes to ATR/Kijun math)

### 3.4 Intraday Rebalance Schedule

Add a **mid-day rebalance** (e.g., 11:00 AM) for:
- Stop market order placement/updates
- Tenkan confirmation checks for deferred entries
- Emergency exits (earnings surprise, etc.)

```python
# In Initialize():
self.schedule.on(
    self.date_rules.every_day(),
    self.time_rules.at(11, 0),   # Mid-day check
    self._intraday_rebalance,
)
```

`_intraday_rebalance()` scope:
1. Update stop market orders to current ATR/Kijun levels
2. Check Tenkan confirmation for any deferred entries
3. Process earnings exits (if data became available intraday)

---

## 4. Integration with Existing Stack

### What Changes
| Layer | Change | Impact |
|-------|--------|--------|
| Signal generation (score_symbol) | **None** | Daily only |
| Entry gates (_check_all_entry_gates) | **None** | Daily only |
| Position sizing | **None** | Same ATR-based sizing |
| Stop calculation (_get_position_stop_price) | **None** | Same ATR/Kijun math |
| Order type | `market_on_open` → `stop_market` | Execution only |
| Rebalance timing | Add 11:00 AM callback | Scheduling only |
| Data subscriptions | Add MINUTE for active symbols | Memory/data load |

### What Stays Identical
- Daily Ichimoku indicators (weekly + daily)
- BCT scoring (8 conditions)
- All entry gates (SPY, chikou, ADX, etc.)
- Position sizing ($200 risk / 2.5×ATR)
- ATR stop calculation
- Ladder trim logic
- Reversal profit exit logic

---

## 5. Implementation Plan

### Phase 1: Stop Market Exits (Minimal Change)
**Scope**: Replace `market_on_open_order(symbol, -qty)` with `stop_market_order(symbol, -qty, stop_price)` for exits only.

**Changes**:
- Modify `_update_and_check_stop()`: return `stop_price` instead of boolean
- Modify `_rebalance()` exit section: use `stop_market_order()`
- Add `stop_market` order tracking in `_position_meta`

**Risk**: Low — same stop math, just different order type.

### Phase 2: Tenkan Confirmation (Entry Timing)
**Scope**: Add `_tenkan_confirmed()` check before entry orders.

**Changes**:
- Add `Resolution.MINUTE` subscription for candidate symbols (top 20)
- Add `_tenkan_confirmed()` helper
- Modify entry flow: confirm → `stop_market_order()` (buy side) or defer
- Add deferred entry tracking in `_position_meta`

**Risk**: Medium — adds data latency dependency, may delay entries.

### Phase 3: Mid-Day Rebalance (Full Intraday)
**Scope**: Add `_intraday_rebalance()` callback at 11:00 AM.

**Changes**:
- Schedule 11:00 AM callback
- Implement stop market order updates
- Process deferred entries
- Intraday earnings exit check (if data available)

**Risk**: Low — mostly mechanical scheduling.

---

## 6. Data and Performance Considerations

### Memory Impact
- **Current**: ~500-600 symbols × daily data = manageable
- **Proposed**: +20 symbols × minute data = ~20 × 390 bars/day = 7,800 bars
- **Mitigation**: Only subscribe minute data for active symbols, unsubscribe on rotation/exit

### CPU Impact
- **Current**: Indicator updates on daily bars only
- **Proposed**: Minimal — Tenkan confirmation is simple max/min over 9 bars
- **Mitigation**: No new indicator registration, just `self.history()` calls

### Backtesting
- **LEAN minute data**: Available for most liquid symbols
- **Warmup**: 9 minutes for Tenkan confirmation (negligible vs 750-day warmup)
- **Cloud**: B2-8 node should handle 20 symbols × minute resolution

---

## 7. Order Management

### New `_position_meta` Fields
```python
self._position_meta[symbol] = {
    "entry_date": self.time,
    "entry_price": price,
    "original_quantity": quantity,
    "ladder_trims": set(),
    "stop_market_order_id": None,  # NEW: track stop market order
    "deferred_entry": False,         # NEW: waiting for Tenkan confirmation
}
```

### Stop Market Order Lifecycle
1. **Entry**: Place `stop_market_order(symbol, -qty, stop_price)` immediately after entry
2. **Daily update**: In `_rebalance()` (16:05), update stop price if ATR/Kijun moved
3. **Intraday update**: In `_intraday_rebalance()` (11:00), update stop price
4. **Exit**: Stop market order fills automatically when price hits
5. **Cleanup**: On fill, remove from `_position_meta` and cancel any remaining orders

---

## 8. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Minute data unavailable for thin symbols | Fallback to daily execution (Tenkan=True) |
| Stop market order slippage in volatile periods | Use `stop_limit_order()` instead (limit = stop × 0.99) |
| Over-subscription to minute data | Cap at 20 symbols, unsubscribe on exit |
| Mid-day rebalance adds complexity | Phase 3 optional — Phase 1+2 sufficient for most benefit |
| Backtest data size explosion | Only enable for W1-W6 BTs, not full FY2025 initially |

---

## 9. Acceptance Criteria

- [ ] Stop market exits fire during market hours (not next open)
- [ ] Tenkan confirmation defers entry until momentum confirms (or 1 day max)
- [ ] No changes to daily signal scoring or entry gates
- [ ] Backtest runs successfully on W1 (April 2026) with minute data
- [ ] Sharpe/WR within ±10% of daily-only baseline (execution only, no signal changes)

---

## 10. Merge Order

1. **feat/score-threshold-34** (GH #34) — MIN_SCORE 6→7, gate simplification
2. **feat/vix-percentile-28** (GH #28) — VIX percentile gate  
3. **feat/intraday-25** (GH #25) — This spec ← **INSERT HERE**

**Rationale**: #25 is execution-only, merges cleanly after signal stack is stable.

---

*Document written for HQ review. Awaiting approval before implementation.*
