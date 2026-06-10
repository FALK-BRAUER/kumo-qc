# Rank-Aware Sizing/Revalidation Plan

## Goal
Turn the LambdaMART scanner rank into an allocation signal after candidate selection, without changing
the production champion by default. This follows #474, where rank-aware entry thresholds helped top50
but did not beat top20 gate-only.

## Implementation
1. Add `RankAwareHeatcap` under `src/phases/sizing/rank_aware_heatcap/`.
   - Preserve the `FlatPctHeatcap` heat-cap behavior.
   - Read frozen `scanner_rank` from the candidate snapshot/context already added in #474.
   - Apply configurable rank buckets to per-name `position_pct`: top, mid, tail.
   - Fail closed only per candidate when scanner context is missing; do not hardcode local paths.
2. Register the phase in `src/phases/sizing/library.py`.
3. Extend `sweeps/grids/scanner_ranker.py` with `rank_aware_sizing_pack`.
   - Include top20/top50 flat controls.
   - Include conservative, balanced, and aggressive rank-weight variants.
   - Keep the existing LambdaMART artifact/objectstore config path.
4. Add tests beside the touched modules.
   - Deterministic bucket sizing.
   - Missing scanner context decline.
   - Cash heat-cap still binds.
   - Catalog registration.
   - Sweep pack shape and config.
5. Run verification.
   - Focused pytest for sizing/grid/runtime parser coverage.
   - Jan smoke with 4 representative cells.
   - FY2025 with workers=3 for the full pack.

## Expected Read
If rank is useful beyond Top-X, top50 rank-aware sizing should improve realized/unrealized balance
or DD versus top50 flat gate. Top20 may not improve because #474 showed the gate is already concentrated.

## Guardrails
- Scanner remains opt-in.
- Production champion defaults do not change.
- No George OCR/watchlist/post/video/transcript labels at runtime.
- Reports stay small; raw LEAN runs and local model artifact remain ignored.
