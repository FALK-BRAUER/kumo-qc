# Diff: performance_bct vs backtest_bct

## Purpose
- **performance_bct (32034565)**: Full trading algorithm with portfolio orders, risk management, Kijun stop exit
- **backtest_bct (32033824)**: Signal audit only, no trades, writes signals to QC Object Store for validation

## Key differences

### File structure
```
performance_bct/
  main.py       191 lines (trading algorithm)
  bct_signal.py (same as backtest_bct)
  universe_filter.py (same as backtest_bct)
  research.ipynb (QC notebook)

backtest_bct/
  main.py       82 lines (signal audit)
  bct_signal.py (shared)
  universe_filter.py (shared)
```

### main.py differences

#### performance_bct
- Entry logic: ≥7/8 BCT signal (`MIN_SCORE = 7`)
- Position sizing: `POSITION_PCT = 0.10` (10% per position)
- Max positions: `MAX_POSITIONS = 10`
- Exit: Kijun stop (sell if price < Kijun)
- Portfolio construction: `enter_position` + `exit_position` methods
- Uses QC native IchimokuKinkoHyo (daily + weekly consolidator)
- Wilder period-9 ADX retained (`score_symbol_native`)

#### backtest_bct
- No orders: `self.log("SIGNAL", ...)` only
- Stores signals in QC Object Store (JSON `bct_signals`)
- Purpose: validate signal accuracy vs scanner (74.2% recall / 100% precision)
- ADX 71% match due to data feed differences (QC vs scanner)

### Algorithm class names
- performance_bct: `BCTPerformanceAlgorithm`
- backtest_bct: `BCTBacktestAlgorithm`

### Parameterized date ranges
performance_bct supports QC parameters:
```python
start_year = self.get_parameter("start_year", 2025)
start_month = self.get_parameter("start_month", 1)
start_day = self.get_parameter("start_day", 1)
```
Defaults to FY2025 (2025‑01‑01 → 2025‑12‑31). Used by `scripts/run_windows.py` for multi‑window backtests.

backtest_bct has fixed dates (2026‑05‑08 → 2026‑05‑22).

### Core logic
**performance_bct**:
- `on_securities_changed`: Adds/removes securities
- `on_data`: Runs BCT scoring, triggers entry/exit decisions
- `enter_position`: Places `SetHoldings` order (10%)
- `exit_position`: Sells at Kijun stop

**backtest_bct**:
- `on_data`: Scores symbols, logs signal lines, writes to Object Store JSON
- No portfolio, no orders, no exit logic

### Shared modules
Both use:
- `bct_signal.py`: 8‑condition BCT scoring
- `universe_filter.py`: Coarse filter (6k → ~200) + BCT fine scoring (→ 5‑10 signals)

### Performance metrics
performance_bct generates Sharpe, CAGR, drawdown, trade stats (see QC/INDEX.md).
backtest_bct produces only signal accuracy metrics (recall/precision).