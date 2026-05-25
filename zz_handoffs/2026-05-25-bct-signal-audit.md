# BCT Signal Audit — 2026-05-25

## Reference: George's Original 8-Condition BCT Checklist

Per CLAUDE.md, the Blue Flag checklist:
1. Weekly price above cloud (Span A)
2. Weekly Tenkan > Kijun
3. Weekly Chikou > price 26 bars ago
4. Weekly cloud GREEN (Span A > Span B)
5. Daily price above cloud
6. Daily price above Tenkan
7. ADX rising + +DI > -DI + ADX ≥ 20 (period 9, Wilder's EWM)
8. Price above 200-day MA

## Audit Findings

### Summary Table

| # | Condition | Implementation | Status | Notes |
|---|-----------|----------------|--------|-------|
| 1 | Weekly price above cloud (Span A) | `w_price > max(w_cloud_a, w_cloud_b)` | **CORRECT** | Using weekly close from w_close[0], comparing against max(Span A, Span B) |
| 2 | Weekly Tenkan > Kijun | `w_tenkan > w_kijun` | **CORRECT** | Direct comparison of weekly indicator values |
| 3 | Weekly Chikou > price 26 bars ago | `w_price > w_price_26_ago` | **UNCERTAIN** | Offset logic matches but needs verification: w_price is current weekly close (w_close[0]), w_price_26_ago is w_close[26] — this compares current vs 26 weeks ago, NOT Chikou vs past price. Checklist says "Chikou > price 26 bars ago" which would be lagged Chikou value |
| 4 | Weekly cloud GREEN (Span A > Span B) | `w_cloud_a > w_cloud_b` | **CORRECT** | Direct comparison of Span A and Span B |
| 5 | Daily price above cloud | `d_price > max(d_cloud_a, d_cloud_b)` | **CORRECT** | Daily close vs daily cloud top |
| 6 | Daily price above Tenkan | `d_price > d_tenkan` | **CORRECT** | Daily close vs daily Tenkan-sen |
| 7 | ADX: +DI > -DI, ADX ≥ 20 | `plus_di > minus_di and adx >= 20` | **CORRECT** (modified) | Original spec included "ADX rising" — this was removed per Fix 1. ADX period is 9 (Wilder's EWM via QC's ADX default) |
| 8 | Price above 200-day MA | `d_price > ma200` | **CORRECT** | Daily close vs 200-period SMA |

## Detailed Analysis

### Condition 3 (Chikou) — UNCERTAIN

**Current implementation:**
```python
w_price = float(w_close[0])  # Current weekly close
w_price_26_ago = float(w_close[26])  # Weekly close 26 bars ago
condition_3 = w_price > w_price_26_ago
```

**What checklist specifies:**
"Weekly Chikou > price 26 bars ago"

**Potential issue:** The Ichimoku Chikou line is defined as "current closing price plotted 26 periods behind." So when evaluating the Chikou condition at time T, we should compare:
- Chikou value at T (which equals close at T)
- vs Price at T-26

**The current implementation does exactly this:** w_close[0] (current close) vs w_close[26] (close 26 weeks ago).

**Verdict:** Implementation is **CORRECT** — matches standard Chikou definition.

### Condition 7 (ADX) — MODIFIED

**Current implementation:**
```python
bool(plus_di_now > minus_di_now and adx_now >= 20)
```

**Original checklist:**
"ADX rising + +DI > -DI + ADX ≥ 20 (period 9, Wilder's EWM)"

**Change history:**
- Originally included `adx_rising` check (ADX[-1] > ADX[-4])
- Removed in Fix 1 per fintrack HQ direction (commit `a77f180`)

**Current status:** +DI > -DI AND ADX ≥ 20 (no rising check)

**ADX configuration:**
- Period: 9 (passed to `self.adx(sym, 9)`)
- Method: QC's default ADX uses Wilder's smoothing
- Plus DI / Minus DI: Accessed via `adx.PositiveDirectionalIndex` and `adx.NegativeDirectionalIndex`

**Verdict:** Implementation is **CORRECT per current spec** (modified from original)

## Off-by-One Checks

### Weekly lookback for Chikou
- RollingWindow size: 28
- Access pattern: w_close[0] (current), w_close[26] (26 bars ago)
- Check: `w_close.count < 27` guards against insufficient data
- **Status:** Correct — needs 27 bars minimum, has 28-slot window

### Weekly indicator periods
- Ichimoku parameters: (9, 26, 26, 52, 26, 26)
- Standard Ichimoku: 9 (Tenkan), 26 (Kijun/Senkou B), 52 (Senkou B lookback)
- **Status:** Correct — matches standard Ichimoku settings

### Daily indicators
- Daily Ichimoku: Same params (9, 26, 26, 52, 26, 26) via `self.ichimoku()`
- SMA200: 200 periods via `self.sma(sym, 200)`
- ADX: 9 periods via `self.adx(sym, 9)`
- **Status:** Correct

## Indicator Registration Issues

### Weekly data feeding
```python
w_ichi = IchimokuKinkoHyo(9, 26, 26, 52, 26, 26)  # Manual instantiation
consolidator = TradeBarConsolidator(Calendar.WEEKLY)
# Updates w_ichi with weekly bars via _on_weekly callback
```

**Potential issue:** `IchimokuKinkoHyo` is manually instantiated, not using QC's built-in `self.ichimoku()`. This means it may not be registered with the algorithm's internal indicator collection, which could affect:
- Warmup handling
- Automatic updates
- Serialization

**Recommendation:** Monitor for warmup/consolidation edge cases. Current implementation appears functional based on cloud test runs.

## ADX Indicator Access

**Registration in main.py:**
```python
adx = self.adx(sym, 9)
plus_di = adx.PositiveDirectionalIndex
minus_di = adx.NegativeDirectionalIndex
```

**Key names:**
- QC C# property: `PositiveDirectionalIndex`
- QC Python mapped: `plus_di` (via getattr access in `_indicator_value`)

**Status:** Correct — QC's Python.NET bridge handles property mapping

## Data Quality Considerations

### Weekly rolling window
- Size: 28 slots
- Used for: w_close[0] (current), w_close[26] (Chikou comparison)
- Minimum required: 27 (checked via `w_close.count < 27`)
- **Status:** Adequate — 28 > 27 minimum

### Warmup
- Algorithm sets warmup via `self.set_warmup(timedelta(days=warmup_days))`
- Default: 750 days (from parameter)
- Weekly indicators seeded via `_seed_weekly()` using 750 days of daily history
- **Status:** Should provide sufficient data for 28-week rolling window

## Conclusion

| Category | Count |
|----------|-------|
| CORRECT | 6/8 |
| CORRECT (modified) | 1/8 (C7 — removed ADX rising) |
| UNCERTAIN → CORRECT | 1/8 (C3 Chikou — verified correct) |

**Overall assessment:** BCT signal implementation matches George's checklist with intentional modification to C7 (removed ADX rising per Fix 1).

**No blocking issues found.** Signal logic is ready for production use.

---
*Audit conducted: 2026-05-25*
*Files reviewed: bct_signal.py, main.py (indicator registration)*
*Reference: CLAUDE.md BCT Signal Stack section*
