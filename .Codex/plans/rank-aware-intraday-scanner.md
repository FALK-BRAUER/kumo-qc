# Rank-Aware Intraday Scanner Plan

Goal: move the LambdaMART scanner integration beyond Top-X gating by preserving scanner rank context
into the daily-to-intraday handoff and testing an intraday confirmer that consumes it.

1. Snapshot/tag plumbing
   - Extend `LambdamartScannerRanker` to publish a stable per-ticker scanner context map.
   - Copy `scanner_rank`, `scanner_score`, and selected deployable features into
     `BctEngineAlgorithm._candidate_snapshot`.
   - Extend `runtime.tag_schema` and `_build_entry_tag()` so scanner rank/score are durable in
     order tags without replacing the existing `decision_rank` field.

2. Rank-aware entry phase
   - Add `src/phases/entry_selection/rank_aware_gap_confirm/`.
   - Reuse the existing gap/loud-open primitive, but make thresholds depend on scanner rank bucket:
     top bucket looser, marginal bucket stricter.
   - Use completed intraday bars only: current close versus signal price and current bar volume
     versus rolling volume baseline.

3. Sweep pack
   - Add `rank_aware_intraday_pack()` to `sweeps/grids/scanner_ranker.py`.
   - Compare gate-only top20/top50 controls against rank-aware top20/top50 variants.
   - Start with champion-intraday-gapvol family; expand only if order flow/performance moves.

4. Verification and run
   - Unit-test scanner context publishing, tag round trip, rank-aware confirm decisions, catalog,
     and sweep pack shape.
   - Run a January smoke first, then FY2025 with `workers=3`.
   - Commit only source/tests/docs/small report summaries; keep raw `sweeps/runs` and model artifact
     ignored.
