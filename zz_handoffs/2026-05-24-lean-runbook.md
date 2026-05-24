# LEAN CLI Runbook for Docker‑Blocked Workers
*2026‑05‑24*

Falk must execute these commands manually — workers cannot run Docker containers (DNS failure). Issue #9 reproduction & W1‑W6 local runs blocked.

## SECTION 1 — First Test Run (W1 window)

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

**Expected:** Backtest completes with trades > 0 (similar to QC‑cloud results: Sharpe 0.733, 28 trades).

**If Terms of Service error appears:**  
Visit https://www.quantconnect.com/data → accept data terms.

## SECTION 2 — Full Reproduction (Issue #9: bct‑perf‑2020‑2026)

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

**Expected targets (QC‑cloud results):**
- Sharpe: ~0.393 (±5%)
- CAGR: ~14.253% (±5%)
- Max DD: ~40.900% (±5%)
- Total trades: ~1807 (±5%)

**Note:** Results may differ due to cloud‑breach exit correction (cloud_top → cloud_bottom).

## SECTION 3 — W1‑W6 Parallel Windows

**Via script:**

```bash
python3 scripts/run_local_windows.py
```

**Manual individual windows:**

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

## SECTION 4 — Troubleshooting

### If Docker not found:

1. Ensure Docker Desktop service is running.
2. `docker info` should show client v29.3.0, server OK.
3. If Docker not installed: `brew install docker`

### If data missing:

```bash
lean data download --dataset "US Equities" --resolution daily \
  --start 2020-01-01 --end 2026-05-01
```

### If ToS required:

Navigate to https://www.quantconnect.com/data → accept data terms in browser.

### If DNS fails inside container:

1. Edit `/etc/docker/daemon.json` (or Docker Desktop settings) → add `"dns": ["8.8.8.8"]`
2. Restart Docker Desktop.

### If LEAN CLI fails with “Must agree to terms”:

Run `lean config` to check API credentials (User ID + API token from macOS keychain).

## Verification

**Cloud‑breach exit corrected:** algorithm/performance_bct/main.py `cloud_top = max(...)` → `cloud_bottom = min(...)`; exit condition `close < cloud_bottom`.

**[:200] cap regression:** live_bct/main.py and live_bct.py still have `[:200][:200]` double cap (CoarseFilter returns `[:200][:200]`). This reduces universe size incorrectly — will affect live trading but not performance_bct.

**Exit conditions:** performance_bct uses daily Kijun stop only (no cloud‑breach, no weekly Kijun). Live variants (live_bct, live_bct/main) have cloud‑breach exit but double‑cap regression.

**QC‑cloud results:**  
- FY2025 Sharpe 0.801 (Kijun‑only exit)  
- bct‑perf‑2020‑2026 Sharpe 0.393  
- bct‑perf‑native‑ichi‑2020‑2026 Sharpe 0.278 (native Ichimoku lower performance)