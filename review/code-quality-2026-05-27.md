# Code Quality Review — performance_bct/main.py

## Date: 2026-05-27
## Reviewer: Code-primary worker

## Complexity Analysis

| Function | Cyclomatic Complexity | Risk |
|----------|----------------------|------|
| `_rebalance` | 30 | **HIGH** — should be refactored |
| `score_symbol` | 7 | Medium |
| `initialize` | 7 | Medium |
| `_seed_weekly` | 6 | Low |

## Key Finding: _rebalance() Complexity = 30

The `_rebalance()` function has very high complexity (30) due to:
1. Multiple nested if/elif/else chains for exit logic (Phase 1/2/3, cloud exit, weekly kijun exit)
2. Entry logic with pre-filters, score validation, position sizing
3. Funnel tracking and logging

**Recommendation:** Refactor into smaller helper functions:
- `_process_exits(symbol, holding, date_str)` — handle all exit logic
- `_find_entry_candidates(slots, date_str)` — scan and score candidates
- `_submit_entry(symbol, score, date_str)` — place entry order

## Other Findings

1. **E82 Phase2 bug fixed:** `meta.pop(symbol, {})` → `meta.pop(symbol, None)` with null check
2. **Parameter naming consistent:** `ENABLE_THREE_PHASE_STOP` class var ↔ `three_phase_stop` parameter
3. **Backwards compatibility verified:** When `three_phase_stop_enabled=False`, behavior identical to G3

## No Critical Issues Found
- No hardcoded `default='true'` violations
- No secret leakage
- Proper type hints throughout

## Recommendations
1. Refactor `_rebalance()` to reduce complexity below 15
2. Consider extracting exit logic into a strategy pattern
3. Add unit tests for edge cases (double exit, missing position_meta)
