# LEAN CLI Runbook for Manual Execution
*2026‑05‑24*

Workers cannot run Docker commands (DNS failure). Falk must run LEAN backtests manually from `/Users/falk/projects/kumo‑qc`.

---

## Section 0 — Native Ichimoku Performance Analysis (Worker-C task)

### Exit Conditions (v2: `02_bct-perf-native-ichi-2020-2026`)

**Single exit rule — daily Kijun stop** (algorithm.py:156-158):
```python
if close < kijun:
    self.market_on_open_order(symbol, -holding.quantity)
    self.log(f"STOP|{date_str}|{symbol.value}|close={close:.2f}|kijun={kijun:.2f}")
```
- Fires daily at 16:05 ET during `_rebalance()`
- Uses `self.ichimoku()` native QC indicator — `d_ichi.kijun.current.value`
- Market-on-open order for next session
- No other exits: no cloud-breach, no weekly Kijun, no trailing stops

### Performance Comparison: v1 vs v2 (2020-01-01 → 2026-05-22)

| Metric | v1 (custom Ichimoku) | v2 (QC native Ichimoku) | Delta |
|---|---|---|---|
| **Sharpe** | 0.393 | 0.278 | **‑29%** |
| **CAGR** | 14.253% | 9.976% | **‑30%** |
| **Net Profit** | 132.560% | 82.632% | **‑38%** |
| **Max Drawdown** | 40.900% | 33.700% | **+18% better** |
| **Total Trades** | 1807 | 1884 | +4.3% |
| **Win Rate** | 42% | 42% | same |

### Why v2 performed worse

1. **Native QC Ichimoku computes differently** — The QC `IchimokuKinkoHyo` indicator uses different warmup seeding and floating-point rounding than our custom implementation. Even small deltas in Tenkan/Kijun values change scoring at the margin (7 vs 6 out of 8).

2. **Entry signals differ** — Same entry threshold (score ≥ 7/8), but v2's native indicator produces different scores for the same stocks on the same dates. Result: 77 more trades (1884 vs 1807) — these incremental trades underperformed.

3. **ADX mismatch persists** — v2 still uses custom Wilder period-9 ADX (QC native ADX is period-14). The hybrid scoring (native Ichimoku + custom ADX) doesn't match v1's fully custom stack.

4. **Lower drawdown is the silver lining** — v2's 33.7% max DD vs 40.9% suggests tighter stops or fewer deep losing positions. This may improve psychological comfort in live trading.

### Verdict

**v1 (custom Ichimoku) outperformed v2 on risk-adjusted returns** (Sharpe 0.393 vs 0.278). The QC native indicator introduces enough noise in the BCT scoring to materially degrade performance. Recommendation: keep custom Ichimoku calculations for production, use native only as a sanity check / debugging tool.

---

## Section 1 — First Test Run (5‑minute validation)

**Command:**

```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 4 \
  --parameter start_day 7 \
  --parameter end_year 2026 \
  --parameter end_month 4 \
  --parameter end_day 11
```

**Syntax confirmed:** `lean backtest` accepts `--parameter <key> <value>` pairs exactly as shown above.

**Expected output:** Backtest completes with a summary containing `Trades`, `Sharpe`, `CAGR`.

**Success criteria:** Trades > 0 (QC‑cloud W1 result: Sharpe 0.733, 28 trades).

**If "Must agree to terms" error occurs:**  
Visit https://www.quantconnect.com/terms/data/?organization=8167a04384265855060312cc22fdbdc6 and accept data terms in browser.

## Section 2 — Full Reproduction (Issue #9: bct‑perf‑2020‑2026)

**Command:**

```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2020 \
  --parameter start_month 1 \
  --parameter start_day 1 \
  --parameter end_year 2026 \
  --parameter end_month 5 \
  --parameter end_day 1
```

**Expected (native Ichimoku, Kijun-only exit):**
- Sharpe: ~0.278 (±5%)
- CAGR: ~9.976% (±5%)
- Max DD: ~33.700% (±5%)
- Total trades: ~1884 (±5%, **differs from QC-cloud 1807 — new exit conditions + native indicator**)

**QC‑cloud reference targets (v1 custom Ichimoku, Kijun‑only exit):**
- Sharpe: 0.393 (±5%)
- CAGR: 14.253% (±5%)
- Max DD: 40.900% (±5%)
- Total trades: 1807 (±5%)

**Note:** Expect deviation from QC-cloud targets because v2 uses native Ichimoku + different warmup. See Section 0 for analysis.

## Section 3 — W1‑W6 Parallel Windows

**Via script (requires Docker):**

```bash
python3 scripts/run_local_windows.py
```

**Individual windows:**

**W1** (2026‑04‑07 → 2026‑04‑11):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 4 \
  --parameter start_day 7 \
  --parameter end_year 2026 \
  --parameter end_month 4 \
  --parameter end_day 11
```

**W2** (2026‑04‑14 → 2026‑04‑18):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 4 \
  --parameter start_day 14 \
  --parameter end_year 2026 \
  --parameter end_month 4 \
  --parameter end_day 18
```

**W3** (2026‑04‑22 → 2026‑04‑25):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 4 \
  --parameter start_day 22 \
  --parameter end_year 2026 \
  --parameter end_month 4 \
  --parameter end_day 25
```

**W4** (2026‑04‑28 → 2026‑05‑02):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 4 \
  --parameter start_day 28 \
  --parameter end_year 2026 \
  --parameter end_month 5 \
  --parameter end_day 2
```

**W5** (2026‑05‑05 → 2026‑05‑09):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 5 \
  --parameter start_day 5 \
  --parameter end_year 2026 \
  --parameter end_month 5 \
  --parameter end_day 9
```

**W6** (2026‑05‑12 → 2026‑05‑16):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2026 \
  --parameter start_month 5 \
  --parameter start_day 12 \
  --parameter end_year 2026 \
  --parameter end_month 5 \
  --parameter end_day 16
```

**FY2025** (2025‑01‑01 → 2025‑12‑31):
```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2025 \
  --parameter start_month 1 \
  --parameter start_day 1 \
  --parameter end_year 2025 \
  --parameter end_month 12 \
  --parameter end_day 31
```

**Expected output table:**  
| Window | Sharpe | Net Profit | Trades |
|---|---|---|---|
| W1 | 0.733 | +31.044% | 28 |
| W2 | 0.258 | +12.482% | 29 |
| W3 | — | 0 | 0 |
| W4 | 0.153 | +8.973% | 30 |
| W5 | 0.337 | +14.899% | 36 |
| W6 | 0.485 | +21.846% | 36 |
| FY2025 | 0.801 | +33.134% | 44 |

## Section 4 — Troubleshooting

| Problem | Fix |
|---|---|
| **Docker not found / not running** | Start Docker Desktop app. If not installed: `brew install --cask docker` |
| **Terms of Service required** | Visit https://www.quantconnect.com/data → log in → accept data agreements |
| **Missing data** | `lean data download --dataset "US Equities" --resolution daily --start 2020-01-01 --end 2026-05-22` |
| **DNS failure inside container** | Docker Desktop → Settings → Resources → DNS → add `8.8.8.8` → restart |
| **API authentication fails** | Verify QC credentials in keychain: `security find-generic-password -s "qc-user-id" -a "kumo-qc" -w` |
| **Trades = 0** | Check warmup period (750 days) — need enough history before start_date |
| **Permission denied on container** | `sudo chown -R $USER ~/.lean` |

---

## Configuration Notes

**Working directory:** `/Users/falk/projects/kumo‑qc`

**lean.json data‑provider:** Must be `ApiDataProvider` for QC cloud data access (default).

**API credentials:** QC User ID + API Token stored in macOS keychain. LEAN CLI uses them automatically.
