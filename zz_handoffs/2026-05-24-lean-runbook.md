# LEAN CLI Runbook for Manual Execution
*2026‑05‑24*

Workers cannot run Docker commands (DNS failure). Falk must run LEAN backtests manually from `/Users/falk/projects/kumo‑qc`.

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

**If “Must agree to terms” error occurs:**  
Visit https://www.quantconnect.com/terms/data/?organization=8167a04384265855060312cc22fdbdc6 and accept data terms in browser.

## Section 2 — Full Reproduction (Issue #9: bct‑perf‑2020‑2026)

**Current code includes cloud‑breach + weekly Kijun exits.** QC‑cloud reference result (Sharpe 0.393, 1807 trades) used **only daily Kijun stop exit**.

**Option A — run current code (cloud‑breach + weekly Kijun exits):**

```bash
lean backtest algorithm/performance_bct \
  --parameter start_year 2020 \
  --parameter start_month 1 \
  --parameter start_day 1 \
  --parameter end_year 2026 \
  --parameter end_month 5 \
  --parameter end_day 22
```

**Expected:** Different Sharpe (unknown). Accept deviation.

**Option B — revert to Kijun‑only exit for reproduction:**

1. Edit algorithm/performance_bct/main.py:

   ```python
   # Remove cloud‑breach exit lines (lines 162–165)
   # Remove weekly Kijun exit (if present)
   ```

2. Run same command as above.

**QC‑cloud reference targets (Kijun‑only exit):**
- Sharpe: 0.393 (±5%)
- CAGR: 14.253% (±5%)
- Max DD: 40.900% (±5%)
- Total trades: 1807 (±5%)

**Tolerance:** ±5% Win Rate, ±5% Max DD per x8kdlg6f.

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

## Configuration Notes

**Working directory:** `/Users/falk/projects/kumo‑qc`

**lean.json data‑provider:** Must be `ApiDataProvider` for QC cloud data access (default).

**If Docker not installed:** `brew install docker`

**If Docker Desktop not running:** Start Docker Desktop service.

**If data missing:**  
```bash
lean data download --dataset "US Equities" --resolution daily \
  --start 2020‑01‑01 --end 2026‑05‑22
```

**If DNS fails inside container:**  
Edit Docker Desktop settings → add DNS `8.8.8.8` → restart.

**API credentials:** QC User ID + API Token stored in macOS keychain. LEAN CLI uses them automatically.