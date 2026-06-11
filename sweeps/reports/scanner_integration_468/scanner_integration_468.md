# Scanner Integration #468

## What Is Wired

- Runtime ranker now accepts both `lambdamart_tree_ensemble` and `linear_pairwise_ranker` JSON artifacts.
- The #467 artifact is loaded through `objectstore://scanner_opportunity_ranker_467_v1.json`.
- Local sweeps stage the committed source artifact from `sweeps/reports/scanner_opportunity_ranker_467/model_artifact.json` into repo `storage/` for LEAN ObjectStore access.
- QC Cloud must upload the same JSON under the same ObjectStore key before running the strategy.

## Strategy And Pack

- Strategy module: `strategies.bct_opportunity_ranker_scanner`.
- Sweep pack: `opportunity_ranker` in `sweeps/grids/scanner_ranker.py`.
- Variants compare baseline, top10, top20, top50, top20 rank-aware entry, and top20 with the #466 `giveback35_after8` MFE exit policy.

## Hardwired

- #467 linear artifact feature version: `scanner_opportunity_scan_time_v1`.
- Live adapter maps current signal-candidate order to `kumo_rank_by_score`.
- `is_kumo_scanner` and `is_kumo_top_n` are true for live signal candidates.
- Default opportunity cloud key: `objectstore://scanner_opportunity_ranker_467_v1.json`.

## Configurable

- `scanner_ranker_top_x`: top10/top20/top50 through runtime overrides.
- `scanner_ranker_model_path`: local path, ObjectStore key, or future artifact key.
- Entry policy: current gap/volume confirm or `RankAwareGapConfirm`.
- Exit policy: current cloud exit, or composed cloud exit plus `MfeIntradayExit` for the #466 giveback policy.

## Cache Keys

Runtime scanner cache identity includes:

- artifact hash
- feature hash
- panel date
- candidate tickers
- `top_x`
- `min_score`
- taxonomy hash

Sweep output identity includes the runtime override values, so changing model path, top-X, or fallback produces a different sweep config hash.

## Local Command

```bash
uv run --python 3.12 python scripts/run_scanner_ranker_sweep.py \
  --pack opportunity_ranker \
  --window jan \
  --workers 1 \
  --only opportunity_linear_top20 \
  --data-folder /Users/falk/projects/kumo-qc/data \
  --no-cache-ensure
```

## Cloud Constraint

Cloud is not run in #468. Before cloud, upload:

```text
sweeps/reports/scanner_opportunity_ranker_467/model_artifact.json
-> ObjectStore key scanner_opportunity_ranker_467_v1.json
```

No-model behavior is still explicit: `scanner_ranker_fallback="raise"` for opportunity variants.
