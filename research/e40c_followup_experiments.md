# e40c Follow-up Experiments — Detailed Specs

**Date:** 2026-05-29  
**Source:** e40c trade analysis + GH idea bank (#118, #76, #75, #50, #32, #71)  
**Status:** Spec-only — no backtests authorized yet  

---

## Context: e40c Edge Profile

From e40c FY2025 honest backtest (raw data + dollar-volume tiebreak):
- **Sharpe:** 0.778 / **Return:** +23.6% / **DD:** 9.1% / **Orders:** 143
- **Winners:** 31 trades, avg +$1,016, held **52.9 days** (HOOD +$6,035, APP +$4,365)
- **Losers:** 36 trades, avg -$464, held **15.6 days** (PLTR -$1,321, VST -$1,227, COIN -$941)
- **Payoff ratio:** 2.2:1 — classic trend-following "cut losers, let winners run"

**Core problem:** Losers are dominated by **fast whipsaw stop-outs** (2-16 days) on **high-volatility names** (PLTR/VST/COIN/NOW/IBM). These generate -$16.7k drag — ~60% of all losses. Winners run 53 days; losers die in 16.

**Target:** Reduce whipsaw losses WITHOUT interfering with multi-month winner runs.

---

## Experiment 1: Entry Whipsaw Filter (Whipsaw-1)

### Hypothesis
Fast whipsaw losses occur because entries happen into high-volatility names where price oscillates around Kijun within days. Require N-day price confirmation above Kijun before entry, OR skip if recent realized volatility > threshold. This filters out names that would reverse immediately while preserving names in sustained trends.

### Exact Code Change

```python
# Add in BCTPerformanceAlgorithm.__init__ or as parameter
WHIPSAW_DAYS: int = 3          # require N days close > Kijun before entry
WHIPSAW_VOL_THRESHOLD: float = 0.03  # skip if 5-day realized vol > 3%

# In _rebalance(), after score_symbol_native() and before candidates.append()
result = score_symbol_native(self, symbol, ind)
if result is None or result["score"] < self.MIN_SCORE:
    continue

# === NEW: Whipsaw filter ===
# Check 1: N-day confirmation above Kijun
try:
    confirm_hist = self.history(symbol, self.WHIPSAW_DAYS + 1, Resolution.DAILY)
    if confirm_hist is not None and len(confirm_hist) >= self.WHIPSAW_DAYS + 1:
        if isinstance(confirm_hist.index, pd.MultiIndex):
            confirm_hist = confirm_hist.droplevel(0)
        close_col = "close" if "close" in confirm_hist.columns else "Close"
        kijun_col = "kijun"  # need to expose from score_symbol or compute
        # Alternative: compute kijun here
        kijun_val = (confirm_hist["high"].rolling(26).max() + confirm_hist["low"].rolling(26).min()).iloc[-1] / 2
        closes = confirm_hist[close_col].iloc[-self.WHIPSAW_DAYS:]
        if not all(closes > kijun_val):
            self.log(f"WHIPSAW_SKIP|{date_str}|{symbol.value}|kijun_confirm_failed|days={self.WHIPSAW_DAYS}")
            continue
except Exception:
    pass

# Check 2: Skip high-vol names
# Compute 5-day realized vol = stdev(daily_returns)
try:
    vol_hist = self.history(symbol, 6, Resolution.DAILY)
    if vol_hist is not None and len(vol_hist) >= 6:
        if isinstance(vol_hist.index, pd.MultiIndex):
            vol_hist = vol_hist.droplevel(0)
        close_col = "close" if "close" in vol_hist.columns else "Close"
        rets = vol_hist[close_col].pct_change().dropna()
        if len(rets) >= 5:
            realized_vol = rets.std()
            if realized_vol > self.WHIPSAW_VOL_THRESHOLD:
                self.log(f"WHIPSAW_SKIP|{date_str}|{symbol.value}|high_vol|vol={realized_vol:.2%}|threshold={self.WHIPSAW_VOL_THRESHOLD:.2%}")
                continue
except Exception:
    pass
# === END Whipsaw filter ===
```

### Parameters (override-able)
| Param | Default | Override |
|---|---|---|
| whipsaw_days | 3 | `--parameter whipsaw_days 5` |
| whipsaw_vol_threshold | 0.03 | `--parameter whipsaw_vol_threshold 0.02` |

### Which Window to Screen First
**W2 (Q2 2025, Apr-Jun)** — This window contains the Apr tariff crash and high-vol regime. PLTR/COIN/VST whipsaw cluster happened in Jan-Mar (W1) but Q2 had elevated volatility across the board. W2 will show if the filter blocks bad entries without missing the recovery.

**Secondary:** W1 (Q1) — direct test on the PLTR/VST/COIN cluster.

### Success Criterion
- **W2 Sharpe improvement ≥ +0.3** vs e40c baseline (0.778 → target 1.08+)
- **W1 loser count reduced by ≥ 30%** (36 → ≤25 losers)
- **Winner count/hold time unchanged** (don't interfere with 53-day winners)
- **DD ≤ 10%** (improve on e40c's 9.1%)
- **Reject if:** W2 Sharpe drops below 0.5 (filter too aggressive, blocks good entries)

### Rationale
PLTR entry Jan 6 → stop Jan 8 (2 days). A 3-day Kijun confirmation would have blocked this entry. HOOD winner Jun→Nov (5mo) would have easily passed 3-day confirmation. The filter targets exactly the observed loss pattern.

---

## Experiment 2: Max-ATR / Volatility Cap on Entry (VolCap-1)

### Hypothesis
High-volatility names (PLTR, COIN, VST) produce outsized losses not because the signal is wrong, but because position sizing is flat 10% regardless of volatility. A 10% position on a 5% daily-vol name has 2× the dollar risk of a 10% position on a 2% daily-vol name. Cap position size by ATR or realized vol to normalize risk per trade.

### Exact Code Change

```python
# Add parameters
VOL_CAP_METHOD: str = "atr20"   # "atr20" | "realized_vol_5d" | "off"
VOL_CAP_PCT: float = 0.02      # max 2% daily vol = position target

# In _rebalance(), after computing target_value, before quantity calculation
# Replace flat POSITION_PCT with vol-adjusted sizing:
atr = 0.0
try:
    if self.VOL_CAP_METHOD == "atr20":
        atr_hist = self.history(symbol, 21, Resolution.DAILY)
        if atr_hist is not None and len(atr_hist) >= 21:
            if isinstance(atr_hist.index, pd.MultiIndex):
                atr_hist = atr_hist.droplevel(0)
            h = atr_hist["high"]
            l = atr_hist["low"]
            c = atr_hist["close"]
            tr1 = h - l
            tr2 = (h - c.shift(1)).abs()
            tr3 = (l - c.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.iloc[-20:].mean()  # 20-day ATR
    elif self.VOL_CAP_METHOD == "realized_vol_5d":
        vol_hist = self.history(symbol, 6, Resolution.DAILY)
        if vol_hist is not None:
            if isinstance(vol_hist.index, pd.MultiIndex):
                vol_hist = vol_hist.droplevel(0)
            rets = vol_hist["close"].pct_change().dropna()
            atr = rets.std() * price  # convert to dollar vol
except Exception:
    pass

if atr > 0 and price > 0:
    # Target: risk = VOL_CAP_PCT * portfolio_value
    # Position size = risk / ATR
    risk_budget = self.portfolio.total_portfolio_value * self.VOL_CAP_PCT
    vol_adjusted_value = risk_budget / (atr / price)  # ATR as % of price
    target_value = min(target_value, vol_adjusted_value)
    self.log(f"VOL_CAP|{date_str}|{symbol.value}|atr={atr:.2f}|flat_value={flat_value:.0f}|adj_value={target_value:.0f}")

quantity = int(target_value / price)
```

### Parameters (override-able)
| Param | Default | Override |
|---|---|---|
| vol_cap_method | "atr20" | `--parameter vol_cap_method realized_vol_5d` |
| vol_cap_pct | 0.02 | `--parameter vol_cap_pct 0.015` |

### Which Window to Screen First
**W1 (Q1 2025, Jan-Mar)** — Direct test on PLTR/VST/COIN cluster. These names had highest vol in Q1. If vol-cap reduces losses here without reducing HOOD/APP winners, it's validated.

**Secondary:** W5 (Feb-May) — Cross-window covering the full whipsaw cluster period.

### Success Criterion
- **W1 total loss reduced by ≥ 40%** (from -$16,693 → ≤ -$10,000)
- **W1 Sharpe ≥ 1.0** (vs e40c's ~0.778)
- **Winner P&L unchanged or improved** (vol cap may increase winner sizes on low-vol names)
- **Reject if:** Total orders drop >30% (cap too aggressive, blocks too many)

### Rationale
COIN 10% position at $300 with 4% daily vol = $1,200 risk. MSFT 10% at $400 with 1.5% vol = $600 risk. Flat sizing over-allocates to high-vol whipsaw names. Normalizing by ATR equalizes risk and should cut the loss drag disproportionately.

---

## Experiment 3: Trend-Aware Trailing Exit (Let-Winners-Run-1)

### Hypothesis
Winners average 53 days but current daily-Kijun stop cuts them at arbitrary technical levels. For positions held >30 days with positive unrealized P&L, switch to a looser exit (weekly Kijun or chandelier trailing stop) to extend the +$1,016 average winner closer to the +$6,035 HOOD outlier. Don't change loser exits (16 days → still fast cut).

### Exact Code Change

```python
# Add parameters
TREND_EXIT_DAYS: int = 30          # switch to looser exit after N days
TREND_EXIT_PNL: float = 0.05       # only if unrealized P&L > 5%
TREND_EXIT_TYPE: str = "weekly_kijun"  # "weekly_kijun" | "chandelier" | "cloud_bottom"

# In _rebalance() exit loop (after Phase 3 check, before daily Kijun stop)
# Current code has:
#   if in_phase3: ... (cloud bottom exit)
#   else: daily Kijun stop / cloud exit / weekly Kijun exit

# === NEW: Trend-aware exit ===
meta = self._position_meta.get(symbol)
if meta is not None:
    days_held = (self.time - meta["entry_date"]).days
    pnl_pct = close / meta["entry_price"] - 1
    
    if days_held >= self.TREND_EXIT_DAYS and pnl_pct >= self.TREND_EXIT_PNL:
        # Switch to looser exit for proven winners
        if self.TREND_EXIT_TYPE == "weekly_kijun":
            # Use weekly Kijun instead of daily Kijun
            w_kijun = ind.get("w_kijun")
            if w_kijun is not None and close < w_kijun:
                self.market_on_open_order(symbol, -holding.quantity)
                self._position_meta.pop(symbol, None)
                self.log(f"TREND_EXIT_WK|{date_str}|{symbol.value}|close={close:.2f}|w_kijun={w_kijun:.2f}|days={days_held}|pnl={pnl_pct:.1%}")
                continue
        elif self.TREND_EXIT_TYPE == "chandelier":
            # Chandelier: highest high since entry - 3×ATR(22)
            try:
                ch_hist = self.history(symbol, 23, Resolution.DAILY)
                if ch_hist is not None:
                    if isinstance(ch_hist.index, pd.MultiIndex):
                        ch_hist = ch_hist.droplevel(0)
                    hh = ch_hist["high"].max()
                    atr = ((ch_hist["high"] - ch_hist["low"]).rolling(22).mean()).iloc[-1]
                    chandelier_stop = hh - 3 * atr
                    if close < chandelier_stop:
                        self.market_on_open_order(symbol, -holding.quantity)
                        self._position_meta.pop(symbol, None)
                        self.log(f"TREND_EXIT_CH|{date_str}|{symbol.value}|close={close:.2f}|ch_stop={chandelier_stop:.2f}|days={days_held}|pnl={pnl_pct:.1%}")
                        continue
            except Exception:
                pass
        elif self.TREND_EXIT_TYPE == "cloud_bottom":
            # Use cloud bottom (same as Phase 3 but earlier trigger)
            cloud_bottom = min(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
            if close < cloud_bottom:
                self.market_on_open_order(symbol, -holding.quantity)
                self._position_meta.pop(symbol, None)
                self.log(f"TREND_EXIT_CB|{date_str}|{symbol.value}|close={close:.2f}|cloud_bottom={cloud_bottom:.2f}|days={days_held}|pnl={pnl_pct:.1%}")
                continue
# === END trend-aware exit ===

# Fall through to existing exits (daily Kijun, cloud exit, etc.)
```

### Parameters (override-able)
| Param | Default | Override |
|---|---|---|
| trend_exit_days | 30 | `--parameter trend_exit_days 21` |
| trend_exit_pnl | 0.05 | `--parameter trend_exit_pnl 0.10` |
| trend_exit_type | "weekly_kijun" | `--parameter trend_exit_type chandelier` |

### Which Window to Screen First
**W3 (Q3 2025, Jul-Sep)** — Strong trending quarter. HOOD winner Jun→Nov spans W3. This window maximizes the chance to catch extended winner runs. If trend-exit helps anywhere, it's here.

**Secondary:** W6 (H1 2025, Jan-Jun) — covers HOOD entry period and tests if earlier trend-exit trigger (days_held) captures the full move.

### Success Criterion
- **Avg winner hold time ≥ 65 days** (vs e40c 53 days = +20% extension)
- **Avg winner P&L ≥ +$1,300** (vs e40c +$1,016 = +28% improvement)
- **Loser hold time unchanged** (≤ 18 days — don't let losers run)
- **W3 Sharpe ≥ 1.2** (e40c W3 was strong; extend the trend)
- **Reject if:** DD increases >2% (looser exits let losers slip)

### Rationale
The +$6,035 HOOD winner was held ~5 months. Current daily-Kijun likely stopped it earlier. Weekly Kijun is ~2× wider than daily, giving proven winners room to breathe while still cutting losers fast (losers never reach 30 days + 5% P&L threshold).

---

## Experiment 4: Risk-Based Sizing (E89-Refined)

### Hypothesis
Current flat 10% sizing + heat cap is a coarse approximation. True risk-based sizing sets position size by stop distance: tight stops (close to Kijun) → larger positions, wide stops → smaller positions. This naturally sizes down high-vol whipsaw names (wide Kijun distance = small position) and sizes up low-vol trend names. E89 (#118) proposed this but used MAX_POSITIONS=99999 which is now default (B0d-honest). This experiment adapts E89 to the current baseline.

### Exact Code Change

```python
# Replace flat POSITION_PCT with risk-based sizing
# In _rebalance(), after candidates.sort(), before quantity calculation

RISK_PER_TRADE: float = 200.0    # $200 fixed risk per position
MAX_POSITION_PCT: float = 0.15  # hard cap: never >15% of portfolio

for symbol, score, _dv in candidates[:slots]:
    price = self.securities[symbol].price
    if price <= 0:
        continue
    
    # Compute Kijun stop distance
    ind = self._indicators.get(symbol)
    if ind is None:
        continue
    d_ichi = ind.get("d_ichi")
    if d_ichi is None or not d_ichi.is_ready:
        continue
    kijun = float(d_ichi.kijun.current.value)
    
    if kijun <= 0 or price <= kijun:
        continue  # invalid stop
    
    kijun_dist = price - kijun  # dollar risk per share
    if kijun_dist <= 0:
        continue
    
    # Risk-based shares
    risk_shares = self.RISK_PER_TRADE / kijun_dist
    risk_value = risk_shares * price
    
    # Cap at MAX_POSITION_PCT of portfolio
    max_value = self.portfolio.total_portfolio_value * self.MAX_POSITION_PCT
    target_value = min(risk_value, max_value)
    
    # Heat check (existing committed_cash logic)
    if available_cash - committed_cash < target_value:
        self.log(f"SKIP|{date_str}|{symbol.value}|heat_exhausted|remaining={available_cash - committed_cash:.2f}")
        break
    
    quantity = int(target_value / price)
    if quantity <= 0:
        continue
    
    # Track heat as dollar risk, not position value
    trade_heat = quantity * kijun_dist
    committed_heat += trade_heat
    
    self.market_on_open_order(symbol, quantity)
    self._position_meta[symbol] = {"entry_date": self.time, "entry_price": float(price)}
    self.log(f"ENTRY_RISK|{date_str}|{symbol.value}|score={score}/8|qty={quantity}|price~{price:.2f}|kijun={kijun:.2f}|risk=${trade_heat:.0f}|target=${target_value:.0f}")
```

### Parameters (override-able)
| Param | Default | Override |
|---|---|---|
| risk_per_trade | 200 | `--parameter risk_per_trade 300` |
| max_position_pct | 0.15 | `--parameter max_position_pct 0.10` |

### Which Window to Screen First
**FY2025 (full year)** — Risk sizing changes capital utilization across the full regime cycle. Single windows are too short to show the compounding effect. Run FY2025 first; if promising, sweep W1-W6.

**Secondary:** W6 (H1) — higher activity period, tests if risk sizing handles concurrent positions correctly.

### Success Criterion
- **FY2025 Sharpe ≥ 1.0** (vs e40c 0.778 = +0.22 improvement)
- **Max concurrent positions ≥ 15** (heat-governed, not slot-governed)
- **Avg position size ≤ 8% NLV** (smaller than flat 10%, more diversified)
- **PLTR/COIN/VST position sizes ≤ 5%** (wide stops = small positions = reduced whipsaw impact)
- **Reject if:** Sharpe < 0.6 (risk sizing adds complexity without edge)

### Rationale
COIN at $300 with Kijun at $285 = $15 stop distance. $200 risk / $15 = 13 shares = $3,900 position = 3.9% of $100k. PLTR at $80 with Kijun at $72 = $8 stop = 25 shares = $2,000 = 2% position. Both are sized DOWN vs flat 10%. MSFT at $400 with Kijun at $390 = $10 stop = 20 shares = $8,000 = 8% position — sized up slightly. Natural vol normalization.

---

## Experiment 5: Portfolio 4% Trailing Drawdown Circuit Breaker (GH #32)

### Hypothesis
During drawdowns, the algo keeps opening new positions as individual stops fire, compounding losses. A portfolio-level circuit breaker halts ALL new entries when equity drops 4% from peak, preventing "catching a falling knife" clusters. Exits still fire (stop losses continue), but no new risk is added until recovery.

### Exact Code Change

```python
# Add parameters
DRAWDOWN_CIRCUIT_PCT: float = 0.04   # 4% trailing drawdown
RECOVERY_HYSTERESIS: float = 0.02    # re-enable at 2% above threshold

# In Initialize()
self._portfolio_peak = self.portfolio.total_portfolio_value
self._circuit_breaker_active = False

# In OnData() or at top of _rebalance()
portfolio_equity = self.portfolio.total_portfolio_value
if portfolio_equity > self._portfolio_peak:
    self._portfolio_peak = portfolio_equity
    if self._circuit_breaker_active:
        self._circuit_breaker_active = False
        self.log(f"CIRCUIT_RECOVER|{date_str}|equity={portfolio_equity:.2f}|peak={self._portfolio_peak:.2f}")

drawdown_pct = (self._portfolio_peak - portfolio_equity) / self._portfolio_peak
if drawdown_pct >= self.DRAWDOWN_CIRCUIT_PCT:
    if not self._circuit_breaker_active:
        self._circuit_breaker_active = True
        self.log(f"CIRCUIT_BREAK|{date_str}|equity={portfolio_equity:.2f}|peak={self._portfolio_peak:.2f}|dd={drawdown_pct:.2%}")

if self._circuit_breaker_active:
    # Check recovery with hysteresis
    recovery_threshold = self._portfolio_peak * (1 - self.DRAWDOWN_CIRCUIT_PCT + self.RECOVERY_HYSTERESIS)
    if portfolio_equity >= recovery_threshold:
        self._circuit_breaker_active = False
        self.log(f"CIRCUIT_RECOVER|{date_str}|equity={portfolio_equity:.2f}|peak={self._portfolio_peak:.2f}|threshold={recovery_threshold:.2f}")
    else:
        self.log(f"CIRCUIT_BLOCK|{date_str}|equity={portfolio_equity:.2f}|peak={self._portfolio_peak:.2f}|dd={drawdown_pct:.2%}")
        return  # HALT — no new entries, but let exits continue (they're before this check)
```

### Parameters (override-able)
| Param | Default | Override |
|---|---|---|
| drawdown_circuit_pct | 0.04 | `--parameter drawdown_circuit_pct 0.03` |
| recovery_hysteresis | 0.02 | `--parameter recovery_hysteresis 0.01` |

### Which Window to Screen First
**W4 (Q4 2025, Oct-Dec)** — This window had the worst e40c/e40b performance (negative Sharpe, high DD). The 4% circuit breaker would have the most opportunity to prove value here by preventing October-November loss compounding.

**Secondary:** W2 (Q2) — Apr tariff crash. Tests if breaker prevents cluster of bad entries during market stress.

### Success Criterion
- **W4 DD reduced by ≥ 3%** (from ~13% → ≤10%)
- **W4 Sharpe improved by ≥ +0.5** (most negative window should show biggest improvement)
- **FY2025 max DD ≤ 8%** (vs e40c 9.1%)
- **Entry days blocked ≤ 15% of trading days** (breaker shouldn't fire constantly in normal markets)
- **Reject if:** FY2025 Sharpe drops >0.2 (breaker blocks too many good entries)

### Rationale
e40c's 9.1% DD likely compounded from sequential bad entries during a down leg. The circuit breaker says "stop adding risk when we're already bleeding." Exits continue (losers still cut), but no new fuel is added to the fire. Recovery hysteresis prevents flickering (on/off/on/off) around the threshold.

---

## Experiment Dependency Graph

```
Whipsaw-1 (Exp 1) ─┬─► can combine with VolCap-1 (Exp 2)
                    │
VolCap-1 (Exp 2) ───┴─► can combine with Risk-Based (Exp 4)

Trend-Exit (Exp 3) ───► orthogonal to all entry/sizing changes

Risk-Based (Exp 4) ───┬─► replaces flat sizing; interacts with VolCap
                      │
Circuit-Breaker (Exp 5) ──► orthogonal to all — portfolio-level gate
```

**Recommended sequence:**
1. Screen Whipsaw-1 on W2 → if positive, combine with VolCap-1
2. Screen VolCap-1 on W1 → if positive, combine with Whipsaw-1
3. If (1+2) positive, run FY2025 with combined filter + Risk-Based sizing
4. Add Trend-Exit-1 if winner extension needed
5. Add Circuit-Breaker-1 last (portfolio-level, independent)

---

## Unified Parameter Table

| Experiment | Key Params | Default | Test Range |
|---|---|---|---|
| Whipsaw-1 | whipsaw_days, whipsaw_vol_threshold | 3, 0.03 | 2-5, 0.02-0.04 |
| VolCap-1 | vol_cap_method, vol_cap_pct | "atr20", 0.02 | "realized_vol", 0.015-0.025 |
| Trend-Exit-1 | trend_exit_days, trend_exit_pnl, trend_exit_type | 30, 0.05, "weekly_kijun" | 21-45, 0.03-0.10, all 3 types |
| Risk-Based | risk_per_trade, max_position_pct | 200, 0.15 | 150-400, 0.10-0.20 |
| Circuit-Breaker | drawdown_circuit_pct, recovery_hysteresis | 0.04, 0.02 | 0.03-0.05, 0.01-0.03 |

---

## Success / Failure Definitions

| Verdict | Definition |
|---|---|
| **ACCEPT** | FY2025 Sharpe ≥ 1.0 AND max DD ≤ 10% AND winner profile preserved |
| **NEUTRAL** | FY2025 Sharpe within ±0.2 of e40c baseline, DD within ±1%, no degradation |
| **REJECT** | Any single window drops >0.5 Sharpe vs e40c, OR DD increases >2%, OR winner count drops >30% |

---

**Document status:** Spec complete — awaiting fintrack authorization for implementation.
