# #487 Scanner Rank-History Requalification Plan

## Goal

Use repeated daily LambdaMART ranking evidence as an opt-in requalification layer, not a one-day
Top-X gate. Keep the production champion unchanged.

## Architecture

1. Add a pure runtime helper in `src/runtime/scanner_rank_history.py`.
   - Track per-symbol rank/score observations by ranker decision date.
   - Prune to a bounded observed-session window.
   - Emit features: `last_rank`, `last_score`, `best_rank_last_5`, `best_rank_last_20`,
     `days_seen_last_5`, `days_seen_last_20`, `days_since_last_top10`,
     `days_since_last_top20`, `rank_trend`, `rank_persistence_score`.
2. Extend `LambdamartScannerRanker`.
   - Score/rank the full signal-candidate panel first.
   - Update rank-history state from the full ranked panel.
   - Optionally select by rank-history requalification.
   - Preserve existing Top-X/min-score behavior when history mode is disabled.
   - Attach rank-history context to `_scanner_ranker_context` and candidate snapshots.
3. Add focused tests.
   - Pure helper tests for no-lookahead, observed-session windows, pruning, and trends.
   - Ranking-phase tests for existing behavior parity and opt-in rank-history selection.
   - Snapshot handoff test that rank-history context survives into entry snapshots.
4. Add sweep variants in `sweeps/grids/scanner_ranker.py`.
   - Realized strategy controls.
   - Dynamic score-medium control.
   - Rank-history requalification variants with `top_x=0`.
   - Rank-history plus existing rank-aware entry/sizing variants.
5. Run and report.
   - Focused unit tests.
   - Jan smoke for the new pack.
   - FY2025 with `workers=3`.
   - Commit compact reports only; raw LEAN runs stay ignored.

## Verification

- Unit tests prove deterministic rank-history features and no source-label leakage.
- Jan smoke proves packaging/local LEAN execution.
- FY2025 report includes return, DD, Sharpe, orders, realized net, unrealized, closed trades,
  win rate, and funnel runtime stats where available.
- Final #487 comment states whether rank-history improves trade participation and realized quality.
