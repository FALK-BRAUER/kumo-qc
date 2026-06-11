# FOR_FALK - BCT/George scanner-alignment implementation pass, 2026-06-09

## #468 opportunity-ranker LEAN/QC integration bridge, 2026-06-11

Goal: turn the #467 scanner-opportunity ranker into a deployable, opt-in scanner gate without
changing the production champion.

What changed:
- `runtime.scanner_ranker` can now load the #467 `linear_pairwise_ranker` artifact in addition to
  the older LambdaMART/tree artifact.
- Live candidate rows now expose the #467 feature contract (`kumo_score`, `kumo_gap_pct`, panel
  ranks/percentiles, volume/price logs) from scan-time runtime data only.
- Added `strategies.bct_opportunity_ranker_scanner`, defaulting to
  `objectstore://scanner_opportunity_ranker_467_v1.json` and Top-20.
- Added `opportunity_ranker` to `sweeps/grids/scanner_ranker.py`: baseline, top10/top20/top50,
  top20 rank-aware entry, and top20 + #466 `giveback35_after8` exit-policy candidate.
- `scripts/run_scanner_ranker_sweep.py` now validates/stages per-variant artifacts, so local LEAN
  runs copy the committed #467 JSON into `storage/scanner_opportunity_ranker_467_v1.json`.
- Tracked integration note: `sweeps/reports/scanner_integration_468/`.

Run locally:
`uv run --python 3.12 python scripts/run_scanner_ranker_sweep.py --pack opportunity_ranker --window jan --workers 1 --only opportunity_linear_top20 --data-folder /Users/falk/projects/kumo-qc/data --no-cache-ensure`

Cloud constraint:
- Upload `sweeps/reports/scanner_opportunity_ranker_467/model_artifact.json` to QC ObjectStore key
  `scanner_opportunity_ranker_467_v1.json` before running cloud.
- Cloud was not run in this PR; this is the local/cloud wiring bridge and smoke-ready pack.

## #469 rank-aware intraday scanner, 2026-06-11

Goal: use LambdaMART scanner rank as live intraday context beyond a Top-X cutoff, without changing
the production champion. Worktree: `kumo-qc-469-rank-aware-intraday-scanner`, branch
`codex/469-rank-aware-intraday-scanner`.

What changed:
- `LambdamartScannerRanker` now publishes a canonical per-ticker scanner context map.
- `BctEngineAlgorithm._capture_candidate_snapshot()` freezes scanner rank/score/features into the
  daily-to-intraday candidate snapshot.
- Entry tags now include `scanner_rank` and `scanner_score` while preserving the old
  `decision_rank` field.
- Results archive trade schema is bumped to v3 so scanner rank/score are durable in trade rows.
- Added `RankAwareGapConfirm`, an intraday entry-selection phase with rank-bucketed gap/loud-open
  thresholds.
- Added the `rank_aware_intraday` sweep pack: top20/top50 gate controls plus rank-aware variants.

FY2025 sweep result:
- All 8 cells completed with `workers=3`.
- Best row remains `rankaware_top20_gate_control`: return `29.133%`, DD `18.800%`, orders `78`,
  realized `-17328.77`, unrealized `$46,510.78`.
- Best rank-aware row is `rankaware_top50_bucket_default`: return `27.473%`, DD `19.700%`,
  orders `74`, realized `-16324.99`, unrealized `$43,840.40`.
- Versus top50 gate-only, rank-aware default improved return by `+1.797` points, DD by `-0.100`,
  realized net by `$320.33`, and unrealized by `$1,476.81`.
- Top20 rank-aware variants did not beat the top20 gate-only control.

Read:
- This is not a champion switch. The top20 gate-only control still wins total return, and this
  champion-intraday family still carries negative realized net with positive unrealized marks.
- The useful signal is narrower: rank-aware intraday confirmation can improve the wider top50 gate.
- `top50_tail_strict` matched default exactly, so stricter tail settings did not bind on actual
  entrants in this run.
- `top50_mid30_tail` is rejected: worse return, DD, realized, unrealized, and more orders.
- Do not blindly apply `RankAwareGapConfirm` to the realized George-range strategies; those use a
  different `entry_selection -> arm -> entry_trigger -> intraday_sizing` architecture. The next
  clean set is rank-aware sizing/revalidation or a scanner-aware arm/trigger consumer.

Reports:
- `sweeps/reports/rank_aware_intraday_jan_smoke_469/`
- `sweeps/reports/rank_aware_intraday_fy2025_469/`

## #455 top20 realization diagnostics, 2026-06-10

Goal: convert the LambdaMART top20 scanner edge into better realized PnL without changing the
production champion. Worktree: `kumo-qc-455-top20-realized-pnl`, branch
`codex/455-top20-realized-pnl-diagnostics`.

What changed:
- Added a diagnostics builder: `scripts/analyze_455_top20_realized_pnl.py`.
- Added the modular `stale_mfe_exit` phase under `src/phases/exit/stale_mfe_exit/`.
- Added the `top20_realized_exit` sweep pack: 3 real strategy bases x 6 top20-only exit variants.
- Added focused tests for the diagnostics script, sweep pack, runner selection, and new exit phase.
- Generated reports:
  - `sweeps/reports/top20_realized_pnl_diagnostics_455/`
  - `sweeps/reports/top20_realized_exit_jan_smoke_455_cache/`
  - `sweeps/reports/top20_realized_exit_fy2025_455/`

FY2025 sweep result:
- All 18 cells completed with `workers=3`.
- Best total/DD rows were all `age60`:
  - `target08_let_run_top20_age60`: return `15.969%`, DD `13.300%`, orders `487`,
    realized `20361.48`, unrealized `$-3,924.68`.
  - `target04_fast_take_top20_age60`: return `13.087%`, DD `13.100%`, orders `548`,
    realized `17498.75`, unrealized `$-3,883.65`.
  - `giveback_no_bull_top20_age60`: return `13.062%`, DD `14.600%`, orders `675`,
    realized `21680.59`, unrealized `$-7,964.47`.

Read:
- `age60` improves total return and drawdown by reducing negative unrealized marks, but realized
  net falls versus each family base and order count jumps. Useful risk-control clue, not a clean
  realized-PnL edge.
- Stale-MFE exits are rejected: lower win rate, more churn, weaker return/DD.
- MFE giveback variants do not generalize. `mfe_gb06` helps some realized PnL in giveback/target04
  but worsens DD/open drag and fails target08.
- Current top20 ranker use is still too shallow: it gates/sorts candidates, but downstream intraday
  confirmation, sizing, and exits do not consume `_scanner_ranker_scores` or
  `_scanner_ranker_features`.

Next architecture step:
- Persist scanner rank/score/features into the intraday candidate snapshot.
- Add rank-aware intraday confirmation: high-rank names can enter on simpler gap/hold behavior;
  marginal names need stronger first-hour/hourly confirmation.
- Add first-hour/hourly path context: opening range, gap fill, VWAP/close location, hold above
  intraday Tenkan/VWAP, first-hour MFE/MAE.
- Use scanner score/rank and sector/industry breadth for sizing and revalidation/rotation exits.
- Tracking ticket: #469.

## #453 real-strategy x LambdaMART scanner sweep setup, 2026-06-10

Added the first proper scanner test matrix against real realized strategy candidates, instead of the
old champion/baseline path whose headline FY result was too unrealized-heavy.

Tickets:
- #453 tracks the 12-cell strategy x scanner matrix.
- #454 tracks the ignored local LambdaMART artifact used for actual scanner cells.
- #451 remains the realized strategy promotion thread.

What changed:
- `src/strategies/realized_george_factory.py` centralizes the George-range phase stack as a
  non-fixture strategy builder.
- `src/strategies/realized_giveback_no_bull.py` now uses that builder.
- Added two more real, non-fixture strategy candidates:
  `strategies.realized_target_04_fast_take` and `strategies.realized_target_08_let_run`.
- Added `real_strategy_scanner` to `sweeps/grids/scanner_ranker.py`:
  three strategies crossed with scanner off, LambdaMART top15, top20, and top25.
- Updated `scripts/run_scanner_ranker_sweep.py` so each variant can carry its own base strategy
  module, multi-base packs get isolated run roots, and summaries include closed PnL/unrealized
  diagnostics.

Local artifact regenerated, not committed:
- Path: `storage/bct_lambdamart_qc_safe_v1.json`
- SHA256: `8efd413bb3d05a98bc7fbd6fecd04489e1137d6c15bd845cb3bed7b29f58d4ed`
- Runtime load preflight passed with 82 features and 140 trees.

Smoke command:
`PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_scanner_ranker_sweep.py --pack real_strategy_scanner --window jan --workers 1 --only giveback_no_bull_scanner_off,giveback_no_bull_scanner_top20 --sweep-id scanner_ranker_real_strategy_jan_smoke_451 --data-folder /Users/falk/projects/kumo-qc/data --no-cache-ensure`

January smoke result:
- `giveback_no_bull_scanner_off`: return `3.697%`, DD `1.900%`, orders `87`,
  closed PnL `5549.30`, unrealized `$-1,787.89`, closed win rate `90.6%`, closed trades `32`.
- `giveback_no_bull_scanner_top20`: return `3.477%`, DD `2.300%`, orders `73`,
  closed PnL `5040.13`, unrealized `$-1,515.09`, closed win rate `95.8%`, closed trades `24`.

Read:
- Top20 did what a scanner gate should do mechanically: fewer orders, fewer closed trades, higher
  closed win rate, and less negative unrealized mark.
- In this tiny January window it gave up closed PnL and worsened DD slightly, so this is not a
  promotion result.
- A previous same smoke run before the diagnostics parser fix produced different order counts, so
  repeatability/staleness should be watched during the FY matrix. Do not over-read the January pair.

Full matrix command:
`PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_scanner_ranker_sweep.py --pack real_strategy_scanner --window fy --workers 6 --sweep-id scanner_ranker_real_strategy_fy2025_453 --data-folder /Users/falk/projects/kumo-qc/data --no-cache-ensure`

Full matrix result:
- The six-worker run overcommitted Docker memory on this machine. It produced 3 valid rows and
  9 invalid non-zero LEAN exits, so invalid rows are excluded from interpretation.
- Retried the 9 failed cells with `--workers 3`; all 9 completed cleanly.
- Combined report:
  `sweeps/reports/scanner_ranker_real_strategy_fy2025_453_combined/summary.md`

Combined FY2025 leaderboard read:
- Best overall: `giveback_no_bull_scanner_top20`, return `12.890%`, DD `17.300%`,
  Sharpe `0.707`, orders `304`, closed PnL `23404.53`, unrealized `$-10,230.71`.
- `target04_fast_take_scanner_top20`: return `12.872%`, DD `17.100%`, Sharpe `0.702`,
  orders `262`, closed PnL `23466.43`, unrealized `$-10,354.65`.
- `target08_let_run_scanner_top20`: return `12.352%`, DD `17.000%`, Sharpe `0.682`,
  orders `229`, closed PnL `22095.78`, unrealized `$-9,536.02`.
- Top20 won inside all three real strategy families versus scanner-off controls.
- The edge is not higher closed PnL. Top20 usually has slightly lower closed PnL than scanner-off,
  but meaningfully less negative unrealized mark, which lifts total return and slightly improves DD.
- Top15 is usually too restrictive. Top25 is not selective enough to beat top20.
- Practical run protocol for this pack: use `--workers 3` unless Docker memory is increased.

Verification:
- `uv run --python 3.12 pytest tests/strategies/test_realized_giveback_no_bull.py tests/sweeps/test_scanner_ranker_grid.py tests/scripts/test_run_scanner_ranker_sweep.py`
  -> 31 passed.
- `uv run --python 3.12 ruff ...` could not run locally because `ruff` is not installed in the
  active environment.

## Post-#448 artifact export and scanner-ranker sweep

After #448 merged, added the missing reproducible runtime-artifact/export step and local LEAN
sweep runner around the merged scanner-ranker grid.

What changed:
- `sweeps/archive/george_lambdamart_ranker.py` can now train one final LightGBM LambdaMART model
  over all covered labels and export the runtime JSON schema validated by `src/runtime/scanner_ranker.py`.
- The export path forces the deployable runtime feature contract: no George/OCR/watchlist/video/source
  fields, no label/rank leakage, and only `DEPLOYABLE_SCANNER_FEATURES`.
- Added `--skip-oof` so artifact export can avoid the expensive OOF benchmark when we only need the
  train-all JSON.
- Added `scripts/run_scanner_ranker_sweep.py` to run baseline/top-X scanner-ranker cells through the
  local LEAN Docker adapter, with repo `storage/` linked as local ObjectStore.

Local artifact generated, not committed:
- Path: `storage/bct_lambdamart_qc_safe_v1.json`
- ObjectStore key expected by runtime: `objectstore://bct_lambdamart_qc_safe_v1.json`
- SHA256: `d8908f0ac221025a2415274c1a22bd79ae4e0d3aa68aed24016cb2093b9387e0`
- Runtime metadata: 82 deployable features, 140 trees, 47,493 rows, 281 positives, 46 dates
  from 2026-02-12 through 2026-04-30.

Commands run:
- Export:
  `PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m sweeps.archive.george_lambdamart_ranker --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026 --skip-oof --export-artifact storage/bct_lambdamart_qc_safe_v1.json`
- January smoke:
  `PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_scanner_ranker_sweep.py --window jan --workers 1 --only scanner_champion_baseline,scanner_lambdamart_top10 --sweep-id scanner_ranker_jan_smoke_448 --data-folder /Users/falk/projects/kumo-qc/data`
- FY2025 top-X pack:
  `PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_scanner_ranker_sweep.py --window fy --workers 1 --only scanner_champion_baseline,scanner_lambdamart_top10,scanner_lambdamart_top20,scanner_lambdamart_top50 --sweep-id scanner_ranker_topx_fy2025_448 --data-folder /Users/falk/projects/kumo-qc/data`

FY2025 local LEAN result:
- Baseline: Sharpe 1.025, return 27.695%, drawdown 19.400%, orders 72.
- LambdaMART top10: Sharpe 0.074, return 0.981%, drawdown 22.000%, orders 68.
- LambdaMART top20: Sharpe 1.065, return 29.133%, drawdown 18.800%, orders 78.
- LambdaMART top50: Sharpe 0.995, return 25.676%, drawdown 19.800%, orders 72.

Read: top20 is the first promising local integration setting. Top10 is too restrictive for the
current trader, and top50 is not selective enough. This is still a rerank/trim of the existing
live signal candidate panel; it is not the broader score-6 scanner lane yet.

Verification:
- `PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/sweeps/test_george_lambdamart_ranker.py tests/runtime/test_scanner_ranker.py tests/sweeps/test_scanner_ranker_grid.py tests/scripts/test_run_scanner_ranker_sweep.py`
  -> 21 passed.

## #446 opt-in LambdaMART scanner runtime integration

Implemented an opt-in deployable scanner ranker path. The production champion remains unchanged:
`strategies.champion_intraday_gapvol` is still the default/current champion. The new path is
`strategies.bct_lambdamart_scanner` and the sweep pack in `sweeps/grids/scanner_ranker.py`.

What landed:
- `src/runtime/scanner_ranker.py`: dependency-free runtime scorer for exported JSON LambdaMART tree
  artifacts. It loads from local paths or QC ObjectStore, validates a deployable feature allowlist,
  rejects George/OCR/watchlist/future-label features, scores candidate panels, and emits deterministic
  cache keys.
- `src/phases/ranking/lambdamart_scanner_ranker/`: ranking phase that ranks/Top-X trims signal
  candidates. It is controlled by `RuntimeConfig`/`BCTAlgorithm` flags:
  `scanner_ranker_enabled`, `scanner_ranker_model_path`, `scanner_ranker_top_x`,
  `scanner_ranker_min_score`, and `scanner_ranker_fallback`.
- Live feature substrate: raw daily OHLC/volume, signed gap and day return from prior close,
  relative volume, BCT condition flags, chart-curation features, daily/weekly Ichimoku facts,
  live denominator ranks/percentiles, and sector/industry breadth from runtime profile maps.
- `TBounceTracker` now keeps signed `gap_pct` and `last_prior_close` while preserving existing
  `gap_up_frac` behavior for entry-confirm logic.
- `sweeps/grids/scanner_ranker.py`: six-cell first pack: champion baseline, phase-off control,
  missing-model fallback control, and LambdaMART top10/top20/top50.

How to build/run:
- Build the opt-in strategy locally/cloud-style:
  `PYTHONPATH=src:. <python> -m build.cloud_package strategies.bct_lambdamart_scanner`
- Local sweep path uses the existing adapter; pass a real model artifact via
  `scanner_ranker_model_path` as either a relative/local path in the generated run dir or an
  ObjectStore key available through local storage.
- QC cloud path: upload the exported JSON model to ObjectStore key
  `bct_lambdamart_qc_safe_v1.json` or override `scanner_ranker_model_path`, then deploy the built
  dist. No local absolute path is hardcoded into runtime code.

Still experimental / not promoted:
- No trained LambdaMART booster artifact is committed in this branch. The runtime path is ready for
  the exported model, but backtest performance still depends on dropping in the trained artifact from
  the research pipeline.
- Sector/industry breadth works with runtime profile maps; if `security_profile_source` is absent or
  incomplete, those features safely degrade to zero/unknown.
- The first integration ranks the live signal candidate panel. It does not yet create a broader
  pre-score denominator in QC cloud; that remains the larger scanner/universe expansion work.

Verification:
- `/Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/runtime/test_scanner_ranker.py tests/phases/ranking/test_lambdamart_scanner_ranker.py tests/runtime/test_indicators.py tests/build/test_cloud_package.py tests/sweeps/test_scanner_ranker_grid.py tests/phases/test_catalog_sweep_guard.py`
  -> 76 passed.

## #442 sector/industry breadth substrate follow-up

Added a deployable sector/industry breadth substrate for scanner ranking:
- `src/phases/shared/sector_breadth.py` computes same-day breadth from the live pre-score candidate
  denominator without George/OCR/watchlist evidence.
- `sweeps/archive/george_learned_ranker.py` and `george_lambdamart_ranker.py` now compute breadth before
  the BCT>=6 score gate, then carry the fields into the ranking panel.
- Missing taxonomy receives zero breadth; it is not grouped into a fake `unknown` sector.
- `src/runtime/security_profiles.py` now accepts multiple ETF proxies via `proxy_etfs`, matching the IBKR
  ETF-watchlist idea better than one proxy per sector.
- Rerun result: raw QC-safe clean_top2000 LambdaMART stays `88/306` recall@10; raw + deployable sector
  breadth reaches `101/306` recall@10. Useful, but still below the promotion target of about `117/306`.

Implemented the first QC-safe scanner-alignment slice from the kumo-lab #23 handoff.

What changed:
- Added `src/phases/shared/chart_features.py`: pure chart-curation formulas for close-location,
  wick ratios, prior-high breakout/retest, constructive resistance, failed rejection, bad resistance,
  reclaim-after-touch, and no-chase penalties.
- Refactored `GeorgeStyleRanking` into a QC-safe ranking phase. It now ranks already-qualified
  `BctScoreFull` candidates by fixed chart-curation score, trailing dollar volume, then ticker.
- Removed the old research-score behavior from the George-style ranking concept: no `_george_style_score`,
  learned George score, OCR label, transcript attention, generated CSV, or external BCT evidence is read.
- Extended `TBounceTracker` with prior-high 20/50/252 windows and prior-20 relative volume from
  completed daily bars. Existing `update()` callers remain backward-compatible; live/seed paths now
  pass volume.
- Kept the strategy opt-in only via `src/strategies/bct_george_alignment.py`; active `CHAMPION` and
  `dist/` are unchanged.

Verification:
- `.venv/bin/python -m pytest tests/phases/shared tests/phases/ranking tests/runtime/test_indicators.py tests/runtime/test_register_warmup_gating.py tests/strategies/test_bct_george_alignment.py tests/sweeps/test_candidates.py`
  -> 123 passed, 9 skipped.
- `.venv/bin/python -m mypy src/phases/shared/chart_features.py src/phases/ranking/george_style_ranking/george_style_ranking.py src/runtime/indicators.py sweeps/archive/candidates.py`
  -> clean.

Interpretation: this is an implementation hook and local validation substrate, not a proven George
clone. The corrected research benchmark remains high-30s recall@10 for QC-safe features and mid-40s
for research-only OOF features.

Follow-up bridge pass:
- Extended `sweeps/archive/candidates.py` schema v2 with `bct_signal_rank`, `george_style_rank`,
  `george_style_score`, and key George-style curation flags.
- The exporter reuses the same `chart_features.py` scorer as the live opt-in ranking phase, so local
  candidate rows and runtime ranking do not drift into separate formulas.
- One read-only 2026 covered-subset smoke against the kumo-lab `george_oof_stage1_scores.csv` label:
  46 covered dates through 2026-04-30, 5,086 QC local candidate rows, 306 George rows covered by
  local data. QC score>=7 candidate coverage was only 73/306 (23.86%). Within that limited seen set,
  George-style rank improved recall@10 from 2.29% to 3.92% and median seen rank from 44 to 38.
- Read: current live QC qualification/universe coverage is the immediate blocker; the rerank helps
  mildly on seen candidates but cannot recover George names that never pass `BctScoreFull` score>=7.

Coverage-stage audit:
- Added `sweeps/archive/george_coverage_audit.py` to classify George labels against the local QC
  live scanner funnel: coarse feed, DV/price floors, daily frame, BCT prefilter, BCT score,
  parabolic block, then candidate/rank.
- Added `build_local_universe_with_metrics()` beside the existing local-daily universe builder so
  offline audits can classify local-daily source rows by prefilter/floor failures instead of only
  testing final ranked membership. Existing `build_local_universe()` behavior is unchanged.
- Exact-date audit on the same 306 covered George positives:
  `qc_candidate=58` (18.95%), `not_in_coarse_feed=176` (57.52%),
  `bct_score_below_min=52` (16.99%), `parabolic_block=15` (4.90%),
  `fails_trailing_dv_floor=5` (1.63%).
- All 176 `not_in_coarse_feed` rows have local LEAN daily zip files, but none appears in the 2026
  QC coarse CSVs. Follow-up exact-bar checks showed the broad non-equity-200 zip files usually stop
  at 2025-12-31, so zip existence alone was a weak test.
- BCT prefilter (`close >= sma200` and `close >= daily_cloud_top`) lost zero labels in this slice.
  The practical next step is not more top-10 tuning yet: first test a broader locally computable
  universe substrate, then rerank within that broader set.
- After testing the broader local-daily helper, the local-daily broad audit is identical to the QC
  coarse audit on 2026 George dates. The 176-row bucket is better described as "not in the available
  2026 QC local substrate" until the broad Massive data is converted or overlaid.
- Massive-backed lab denominator (`george_ranking_denominator.csv`) covers all 306 of these same
  date-symbol George positives. On that substrate: top3000 ADV20 price>=10 captures 304/306
  (99.35%), top2000 captures 286/306 (93.46%), current liquidity-style gate captures 239/306
  (78.10%), BCT>=7 captures 182/306 (59.48%), and BCT>=6 captures 283/306 (92.48%).
- Combined read: broad Massive universe + BCT>=7 captures 181/306 (59.15%); broad Massive universe
  + BCT>=6 captures 281/306 (91.83%). George appears to select many "almost BCT" score-6 names with
  constructive structure, so the next research/implementation fork is a score-6 candidate lane plus
  stricter ranking/confirmation, not a blind top-3000 live scanner.

Score-6 lane implementation/check:
- Added `bct_candidate_lane` to the offline candidate export schema (`schema_version=3`):
  `bct_score_ge7`, `almost_bct_score6`, or `below_bct_score6`.
- Added opt-in `src/strategies/bct_george_alignment_score6.py`, identical to the score-7 George
  alignment config except `BctScoreFull.Params(min_score=6, parabolic_threshold=0.25)`. `CHAMPION`
  remains unchanged.
- Massive denominator check on the same 306 labels:
  top3000+BCT>=7 => 25,080 rows, median 484.5/day, 181/306 George recall.
  top3000+BCT>=6 => 47,493 rows, median 1,094/day, 281/306 George recall
  (+22,411 rows, +100 George positives versus top3000+BCT>=7).
  top2000+BCT>=6 => 32,198 rows, median 735.5/day, 263/306 recall.
  current-liquidity-gate+BCT>=6 => 21,467 rows, median 491.5/day, 223/306 recall.
- A lightweight proxy of the fixed QC-safe ranker on top3000+BCT>=6 is not sharp enough:
  recall@10 2/306, recall@50 36/306, recall@100 63/306, recall@200 109/306, median George rank 277.
- Read: score 6 is a real George coverage lane, but not ready as a live top-list without a sharper
  selector/confirmation layer. Do not promote the score-6 config beyond opt-in experiment yet.

Score-6 selector audit:
- Reran the score-6 pool audit directly against
  `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv`
  using the populated main QC coarse cache at `/Users/falk/projects/kumo-qc/data`, not the skeletal
  worktree `data/`.
- Base panel reproduced the prior denominator check: top3000 ADV20 price>=10 + BCT>=6 has 47,493
  rows, 46 covered dates, median 1,094 rows/day, and 281/306 George labels.
- The best clean pool reducer found was `clean_top2000`: daily cloud/Tenkan/Kijun clean, no chase,
  ADV top2000. It keeps 216/306 labels (70.59%) while cutting to 15,517 rows, median 286.5/day.
- Other useful-but-still-large gates: `clean_daily_base` keeps 231/306 at median 437/day,
  `pullback_top2000` keeps 185/306 at median 263/day, and `score6_clean_all` keeps only 58/306
  at median 89.5/day.
- Simple hand-ranked QC-safe formulas did not solve top10. The reusable harness' best simple top10
  variant was `clean_top2000__daily_structure_rank`: 26/306 recall@10 (8.50%), recall@50 84/306,
  recall@100 138/306.
- Interpretation: hard filters can create a review lane, but the George top-list problem is still
  ranking/selection. No runtime ranker tweak is justified from these hand rules. The next serious
  path is a date-grouped learned ranker/selector plus sector/industry context, with strict separation
  between clean deployable features and research-only George/OCR/transcript features.

Score-6 top-K harness:
- Added offline-only `sweeps/archive/george_topk_audit.py` and
  `tests/sweeps/test_george_topk_audit.py` for #422.
- The harness takes explicit label, denominator, and QC coarse-cache paths; it fails loudly if the
  coarse cache has zero covered dates, which protects against accidentally using the empty worktree
  `data/` folder.
- Real-data reproduction command confirmed the expected base panel:
  `PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_topk_audit --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026`
  -> 47,493 rows, 46 dates, median 1,094/day, 281/306 labels.

Learned ranker v1:
- Added offline-only `sweeps/archive/george_learned_ranker.py` and
  `tests/sweeps/test_george_learned_ranker.py` for #423.
- This is a dependency-free NumPy logistic/ridge ranker with chronological date-group folds. It uses
  QC-safe denominator features only; no George/OCR/transcript/generated research score enters runtime.
- Real-data OOF command:
  `PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026`
  reproduced the same 47,493-row base panel.
- Best learned OOF variant: `learned_oof_clean_top2000` at 60/306 recall@10 (19.61%),
  recall@20 104/306, recall@50 147/306, recall@100 181/306. That beats the simple hand-rank
  baseline (`clean_top2000__daily_structure_rank` = 26/306 recall@10) but is still below the
  lab-reported clean GBM benchmark (~38% recall@10).
- Top stable coefficients in this first pass: daily Tenkan>Kijun, intraday/day return, price above
  Kijun/cloud, daily structure score, and liquidity rank. Negative weights include worse DV rank,
  ADX flag interactions, overextension, and lower-wick-heavy shape.
- Read: the learned harness is now useful for #423 experiments, but this v1 model is not a promotion
  candidate. The next #423 work is richer feature parity with the lab `qc_cloud_deployable` set and
  stronger date-grouped model classes, not runtime integration.
- Added an opt-in sector-context feature path to `george_learned_ranker.py` using the profiled
  Massive denominator. Default no-context behavior remains unchanged.
- Controlled profiled-denominator comparison:
  no-context `learned_oof_clean_top2000` = 59/306 recall@10, 104/306 recall@20, 147/306 recall@50;
  `--use-sector-context` `learned_oof_sector_context_clean_top2000` = 65/306 recall@10,
  107/306 recall@20, 154/306 recall@50, 182/306 recall@100.
- Read: sector/industry context gives a small but real OOF lift (+6 labels at top10 versus the
  profiled no-context run, +5 versus the earlier unprofiled run). It belongs in the selector
  feature set, but still does not get near the 60-70% top10 target.
- Added a dependency-free pairwise linear ranker (`--model-type pairwise`) that trains on same-date
  George-positive vs non-George candidate pairs. This is still offline-only and labels remain
  scoring/training input only for the research harness.
- Small deterministic pairwise sweep over sector-context runs found the best current setting at
  `--pairwise-negatives-per-positive 80 --learning-rate 0.08`.
  `learned_oof_pairwise_sector_context_clean_top2000` reaches 46/306 recall@5, 72/306 recall@10
  (23.53%), 109/306 recall@20, 160/306 recall@50, and 187/306 recall@100.
- Read: pairwise+sector context is the best QC-side offline harness result so far, improving top10
  over logistic+sector context by +7 labels and over the original logistic baseline by +12 labels.
  It is still not a live promotion candidate; it strengthens the case for a richer selector model
  and exact feature parity with the lab GBM.
- Added opt-in first-hour feature enrichment to the learned ranker (`--use-first-hour --minute-dir`),
  reusing `first_hour_confirmation.py` instead of duplicating minute-zip parsing.
- Controlled pairwise runs at the best current pairwise setting (`lr=0.08`, 80 negatives/positive):
  pairwise+sector = 72/306 recall@10; pairwise+first-hour = 70/306 recall@10; pairwise+sector+
  first-hour = 66/306 recall@10. The first-hour feature family did not improve top10 selection in
  this model, likely because local minute coverage is partial and the strongest intraday facts are
  confirmation/reducer signals rather than pre-rank discriminators.
- Read: keep first-hour as a separate post-rank confirmation/audit layer for now. Do not merge it
  into the selector feature set unless minute coverage and validation improve.

Massive/QC substrate bridge:
- Added offline-only `sweeps/archive/massive_qc_bridge.py` and
  `tests/sweeps/test_massive_qc_bridge.py` for #424.
- The bridge turns the Massive-backed denominator into a QC-style local candidate panel with date,
  symbol, price/ADV ranks, BCT score/lane, gap/return/liquidity, and chart/Ichimoku flags. Optional
  George label coverage is reported separately; labels are not embedded into the exported panel.
- Broad top3000 reproduction:
  `PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.massive_qc_bridge --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026 --top-n 3000 --no-min-score`
  -> 138,000 rows, 46 dates, median 3,000/day, 304/306 label coverage.
- Score-6 lane reproduction:
  `PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.massive_qc_bridge --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026 --top-n 3000 --min-score 6`
  -> 47,493 rows, 46 dates, median 1,094/day, 281/306 label coverage.
- Important caveat: this is the local/offline substrate bridge from the Massive denominator into
  audit artifacts. It does not implement QC cloud broad-universe selection.

Score-6 first-hour confirmation:
- Added offline-only `sweeps/archive/first_hour_confirmation.py` and
  `tests/sweeps/test_first_hour_confirmation.py` for #425.
- The harness reads local LEAN 5-minute trade zips (`minute/<symbol>/<YYYYMMDD>_trade.zip`) and
  computes first-hour facts: first-hour return/range/drawdown/volume, hold above prior close,
  no open flush, first-bar-high reclaim, volume threshold, and combined confirmation flags.
- Real-data label-only smoke:
  `PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.first_hour_confirmation --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --minute-dir /Users/falk/projects/kumo-qc/data/equity/usa/minute --year 2026 --top-n 3000 --min-score 6 --labels-only`
  -> 281 George rows in top3000+BCT>=6, 122 with local intraday files, 91/306 pass
  `fh_confirm_basic`, 75/306 pass `fh_confirm_breakout`, 77/306 pass `fh_confirm_volume`,
  and 62/306 pass `fh_confirm_breakout_volume`.
- Full-pool run on the same top3000+BCT>=6 panel:
  47,493 rows, 46 dates, 9,422 rows with local intraday files, 281/306 George rows in panel, and
  122 George rows with intraday files. Base panel label precision is only 0.592%.
  `fh_confirm_basic` keeps 4,313 rows at 91/306 recall and 2.110% label precision (3.57x lift);
  `fh_confirm_breakout` keeps 3,028 rows at 75/306 recall and 2.477% precision (4.19x lift);
  `fh_confirm_volume` keeps 3,591 rows at 77/306 recall and 2.144% precision (3.62x lift);
  `fh_confirm_breakout_volume` keeps 2,529 rows at 62/306 recall and 2.452% precision (4.14x lift).
- Read: first-hour confirmation is a useful enrichment/false-positive reducer, not a standalone
  top10 solver. Current local minute coverage remains a separate blocker, and the selector still
  needs stronger pre-open/sector/ranking features before runtime promotion.

Sector/industry hierarchy context:
- Added offline-only `sweeps/archive/george_sector_context_audit.py` and
  `tests/sweeps/test_george_sector_context_audit.py` for #409 follow-up.
- The harness reads the profiled Massive denominator
  (`george_ranking_denominator_profiled.csv`), derives dynamic sector and industry strength from
  same-day stock-level weekly/daily chart features, and measures stage recall plus top-K rank
  variants. George labels are used only for scoring, not for group scores.
- Real-data run on the same top3000+BCT>=6 panel reproduced 47,493 rows, 46 dates, median
  1,094/day, and 281/306 George labels in-panel.
- Profile coverage is still the first constraint: 187/281 in-panel George labels have sector and
  industry profiles (66.55%).
- Within profiled in-panel labels, hierarchy stage recall is strong:
  sector top7 = 159/187 (85.03%), sector top10 = 182/187 (97.33%);
  industry-in-sector top5 = 142/187 (75.94%), top10 = 176/187 (94.12%);
  stock-in-industry top10 = 176/187 (94.12%).
- But simple context ranking is not enough: `sector_context_score` improved base stock-score
  recall@10 from 4/306 to 13/306, still far below the learned-ranker 60/306 benchmark.
- Read: sector/industry mapping is clearly worth implementing as a feature substrate and diagnostic
  layer. It is not a standalone top-list selector; the next model needs to consume hierarchy
  features together with OOF stage-1 scores, richer chart curation, and first-hour/pre-open signals.

GitHub backlog created:
- #422 `[SCANNER] BCT/George top-K validation harness for score-6 lane`
- #423 `[SCANNER] QC-safe learned George top-list ranker v1`
- #424 `[DATA] Broad Massive/QC scanner substrate bridge for local BCT alignment`
- #425 `[STRATEGY] Score-6 BCT candidate lane with first-hour confirmation`
- Added scanner-specific TC2000/industry hierarchy acceptance criteria to existing #409.

# George Context Sweep Protocol

This branch makes the George-context architecture runnable as a proper sweep protocol.
`SweepConfig` can now carry runtime overrides (`WATCHLIST_CARRY_MAX`, profile/attention sources, etc.) and disabled phase choices, and `build/sweep_build.py` maps those into `StrategyConfig.runtime` plus real phase slots before building a dist.

The named protocol lives in `sweeps/grids/george_context.py`:
- `six_pack()` = baseline, industry-only, attention-only, watchlist-carry-only, industry+watchlist, full George context.
- `thirty_pack()` = five waves of six: industry warm-up, watchlist carry, George attention, entry confirmation, and exit management.

All George variants default to corrected weekly (`continuous_weekly=True`) and trimmed warmup (`warmup_days=320`) so local sweeps can use the weekly cache path instead of re-deriving the whole weekly stack.

# George Profile And Attention Loaders

This branch adds optional runtime loaders for George-context profile and attention data.
`security_profiles.py` reads ticker -> sector/industry/subindustry/proxy/source/confidence maps; `george_attention.py` reads confidence-weighted ticker and industry attention priors while preserving source-role counts.

`BctEngineAlgorithm` now initializes the phase-facing maps (`_industry_by_ticker`, `_george_attention_ticker`, `_george_attention_industry`, etc.) and fail-soft logs missing/bad optional source files.
Default behavior is unchanged when `SECURITY_PROFILE_SOURCE` and `GEORGE_ATTENTION_SOURCE` are unset.

# George Watchlist Carry

This branch adds default-off George watchlist carry at the LEAN selection gate.
When `WATCHLIST_CARRY_MAX > 0`, `_coarse_selection` can append bounded watchlist tickers that appear in today's coarse-derived raw metrics, pass carry price/liquidity floors, and are not already normally ranked.

The helper is pure (`runtime.watchlist_carry`) and deterministic; the LEAN hook publishes `_selection_sources`, `_watchlist_carry_today`, `_watchlist_carry_rejected`, and logs `WATCHLIST_CARRY|...` rows.
Default behavior stays unchanged because `WATCHLIST_CARRY_MAX` is `0`.

Verified with focused runtime/build tests plus the broader runtime/data selection subset.

# George RuntimeConfig Foundation

This branch adds the typed runtime contract needed before selection-gate watchlist carry.
`RuntimeConfig` now owns LEAN runtime knobs, build codegen emits non-default values as `BCTAlgorithm` class attributes, and manifest/metadata record runtime overrides for provenance.

Existing configs remain compatible: default runtime settings do not move legacy hashes, and the old top-level `continuous_weekly=True` flag still round-trips as the same identity dimension.
This PR intentionally does not implement watchlist carry behavior yet; it only makes the runtime knobs typed, hashable, and deployable.

# George Context Baseline

This branch adds the first George-context architecture slice without changing existing champion behavior.
It introduces a daily `rebalance` phase for industry warm-up context and a `ranking` phase that reorders current candidates using industry heat, ticker attention, and lightweight watchlist memory.

What is intentionally not here yet: selection-gate watchlist carry, profile/attention file loaders, runtime config/codegen knobs, and the FY2025 6-pack/30-pack backtest sweep. Those are tracked in GitHub issue #416 and the Codex plan.

Verified:
- `pytest -q tests/phases/test_george_context_phases.py tests/phases/test_catalog_sweep_guard.py tests/strategies/test_champion_george_context.py`
- `PYTHONPATH=build:src /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3` build smoke for `strategies.champion_george_context`

# FOR_FALK - #412/#414 exit diagnostics + combo sweep, 2026-06-08

Implemented #412 per-symbol exit diagnostics and created the second 30-pack combo sweep runner.

What changed:
- `ProactiveStrengthExit` and `ScratchFlatExit` now emit one `EXIT_EVENT|date|symbol|...` row per
  symbol exit through `qc.log`, including module, reason, days held, qty, entry/exit price, pnl,
  return, MFE, MAE, peak return, and giveback from peak.
- `ProactiveStrengthExit.Params` now has `min_hold_days=0` so combo scenarios can test the first
  sweep's hold-time signal without changing existing defaults.
- `scripts/run_408_george_range_30.py --rebuild-artifacts` now parses the new `EXIT_EVENT` rows into
  per-run `exit_events.csv` and aggregate `exit_events_all.csv`, while still tolerating legacy strings.
- `scripts/run_414_george_combo_30.py` defines exactly 30 recombination variants and reuses the #408
  local LEAN harness/exporter. Default command: `python3 scripts/run_414_george_combo_30.py --workers 6`.
- Worktree-safe cache command: `python3 scripts/run_414_george_combo_30.py --data-folder /Users/falk/projects/kumo-qc/data --full-warmup --workers 6`.
  The harness injects `--lean-config <generated lean.json>` when `--data-folder` is used, so LEAN
  mounts the populated main raw data cache instead of the skeletal worktree `data/` folder.

Second 30-pack design:
- Centered on `giveback_tight_no_bull` plus `buy_stop_005` / `buy_stop_010`.
- Tests 7d/14d proactive min-hold, 3-4.5% flat sizing, target-8 and min-peak-3 variants, tight scratch
  overlays, capped vol-risk, 0.75 ATR cushion, and stricter breadth/resistance cells.
- This creates the true recombination matrix the first 30-pack did not yet cover.

Verification:
- Focused pytest: 15/15 passing.
- Real Jan 2025 LEAN smoke through the combo harness:
  `combo_gb_buy005`, full warmup, main data cache, `rc=0`, `Completed`, 62 orders,
  net `3.495%`, DD `1.800%`, Sharpe `5.823`.
- Rebuilt `exit_events_all.csv` contains 20 per-symbol exit rows: 16 `target`, 4 `giveback`, with
  complete entry/exit, MFE, MAE, peak-return, and giveback fields. The parser rejoins LEAN-wrapped
  log lines before writing CSV.

# FOR_FALK - #398/#408 George-range 30-pack local BT sweep, 2026-06-08

Built and ran the 30-variant FY2025 local LEAN sweep for the George-style intraday architecture
proof. The harness is `scripts/run_408_george_range_30.py`: it generates 30 `StrategyConfig`
variants from the phase catalog, runs real local LEAN BTs, and preserves per-variant plus aggregate
orders/trades CSVs for later trade-history analysis.

## Verified

- Compile: `python3 -m py_compile scripts/run_408_george_range_30.py`.
- Prepare-only: all 30 configs built and cache attrs resolved.
- Smoke: Jan 2025, one variant, local LEAN `rc=0`.
- Full FY2025 sweep: 30/30 completed, 30/30 `ok=True`.
- Actual stable command: bundled Python + `scripts/run_408_george_range_30.py --workers 3`.
- Important runtime caveat: the runner defaults/supports `--workers 6`, but six active Docker LEAN
  jobs exceeded the current Docker Desktop 16 GiB memory envelope and killed one child. The successful
  banked FY2025 run used three parallel workers.
- Post-run artifact rebuild: `scripts/run_408_george_range_30.py --rebuild-artifacts`, adding
  `date`, `entry_date`, `exit_date`, and `duration_days` to the exported data.

## Artifacts

- Report dir: `sweeps/reports/george_range_30/`
- Summary: `sweeps/reports/george_range_30/summary.csv`
- Orders: `sweeps/reports/george_range_30/orders_all.csv` — 42,065 rows.
- Trades: `sweeps/reports/george_range_30/trades_all.csv` — 21,372 rows, 20,693 closed trades with
  populated dates and duration.
- Per-variant run dirs: `sweeps/runs/george_range_30/<variant>/fy2025_full/`

## First Read

| Variant | Family | Net Profit | Drawdown | Orders | Sharpe | Read |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `giveback_tight_no_bull` | exit_target | 10.960% | 17.600% | 257 | 0.569 | best clean return/DD tradeoff |
| `target_08_let_run` | exit_target | 10.330% | 17.700% | 223 | 0.530 | runner-up, low order count |
| `p_only_tight_giveback` | anchor | 10.292% | 17.400% | 326 | 0.535 | anchor still strong |
| `minpeak_low_03` | exit_target | 10.012% | 17.100% | 478 | 0.523 | best DD among ~10% return set |
| `buy_stop_005` | entry_trigger | 8.058% | 15.900% | 1291 | 0.415 | useful entry idea: lower DD |
| `buy_stop_010` | entry_trigger | 7.099% | 15.800% | 1084 | 0.371 | lower DD, lower return |
| `pos_03_atr_075` | risk_stack | 5.616% | 13.700% | 1870 | 0.338 | lowest DD, return too low |
| `volrisk_125` | risk_stack | 11.897% | 34.900% | 1870 | 0.404 | highest return, unacceptable DD |

Interpretation: exit policy matters more than scratch/no-progress management in this FY2025 slice.
The best clean cell is `giveback_tight_no_bull`; buy-stop entries are interesting because they cut DD
meaningfully, but they also give up return. Vol-risk sizing can manufacture return but blows up DD, so
it is a negative control until risk caps are reworked.

Caveats: `exit_events_all.csv` is structurally present but empty because the current phase logs emit
aggregate phase exit counts, not per-symbol exit-event rows. The trade/order CSVs are still usable for
analysis, but the phase contract should emit per-symbol exit diagnostics if we want reliable exit-reason
labels. `resistance_loose_010` and `breadth_050_strict` matched `scratch_base`, so those params likely
did not bind in this current config path and should not be treated as independent evidence.

## Analysis pass

Added `scripts/analyze_408_george_range_30.py` and generated
`sweeps/reports/george_range_30/analysis/`.

Outputs:
- `analysis.md`: human readout of best cells, low-DD cells, parameter confidence, indicator bins,
  hold-time bins, and symbol edges.
- `parameter_confidence.csv`: axis-level recommendations and confidence.
- `variant_trade_diagnostics.csv`: per-variant win rate, return, profit factor, duration, and
  decision-tag diagnostics.
- `metric_ranges.csv`: observed ranges for every usable summary/trade/order/entry-tag metric.
- `entry_indicator_bins.csv`: decision rank, gap, volatility, and hold-time bins.
- `symbol_edges.csv`: repeated-symbol winners/laggards across the variants.

First analysis reads:
- Exit target management has the best medium-confidence range: target 6-8%, min peak 3-5%, giveback
  1.5-2.5%, with `giveback_tight_no_bull` best observed.
- Buy-stop breakout offsets 0.5-1.0% are worth the next lower-DD entry experiment; 0.5% is the best
  return/DD balance in this panel.
- Scratch/no-progress exits should not be promoted as the primary edge; they prove the path contract
  but trail proactive-only return.
- Hold time is a large signal in this data: 0-3 day closed trades are negative on average, while
  7+ day holds are strongly positive. That argues against premature exits unless they are clearly
  failed entries.
- Negative gap entries below -1% are weak; 1-2% gap entries are strongest in this limited tag set.
- Best repeated symbol behavior: AVGO, AMD, ORCL, GOOGL, NVDA. Weakest repeated behavior: NFLX, HD,
  V, CRM.

# FOR_FALK - #398/#406/#407 George-style exit proof, 2026-06-06

What changed after your MFE tracker note: PR #411 adds a reliable `position_path` contract to the
phase stack. `PositionPathTracker` is a `trail` phase that provides the named downstream contract;
`ProactiveStrengthExit` and `ScratchFlatExit` now require `REQUIRES_UPSTREAM = ["position_path"]`.
The engine validates named downstream contracts at init, so a missing or misordered MFE/path tracker
fails before LEAN can run a fake proof.

## Built

- `PositionPathTracker`: per-position entry, peak, trough, last price, MFE/MAE, and days-held state.
- `ProactiveStrengthExit`: market exit for winners into bullish strength, currently target/giveback
  based.
- `ScratchFlatExit`: market exit for no-progress, roundtrip-flat, or capped-loss-after-MFE trades.
- Six Scenario-C proof blueprints:
  - `scenario_exit_proactive`
  - `scenario_exit_proactive_giveback_tight`
  - `scenario_exit_proactive_scratch`
  - `scenario_exit_proactive_scratch_fast`
  - `scenario_exit_proactive_scratch_patient`
  - `scenario_exit_proactive_scratch_tight_risk`
- `scripts/run_398_fy_exit_sixpack.py`: one-process runner that submits the six FY2025 rows through
  shared warmup/cache orchestration and supports targeted retry via `KUMO_398_MODULES`.

## Verified

- `PYTHONPATH=src pytest -q` -> 1447 passed, 3 skipped, 1 warning.
- `mypy` -> clean across 192 source files.
- GitHub PR checks for #411 -> passed.
- Three real LEAN Jan 2025 proof runs after the contract patch, all `lean rc: 0`.
- Cache was used on all three: weekly fp `90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c`.
- Six FY2025 LEAN rows are now banked with completed statistics blocks. First pass launched all six
  together (`workers=6`, `WARMUP_GATE_CAPACITY=6`) and completed four; Docker dropped two cells with
  non-terminal `Running` JSONs under resource pressure. The two dropped cells were rerun together
  (`workers=2`, same weekly cache fp) and completed cleanly.

| Blueprint | Config hash | Return | Net Profit | Drawdown | Total Orders | Exit activity |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `scenario_c` | `1962771d8813` | 3.33% | 3.329% | 2.300% | 272 | baseline |
| `scenario_exit_proactive` | `074d3833c494` | 3.62% | 3.617% | 2.200% | 45 | 12 proactive target exits |
| `scenario_exit_proactive_scratch` | `49d1c008f433` | 3.93% | 3.926% | 2.200% | 79 | 18 scratch exits + 11 proactive target exits |

### FY2025 six-pack

| Blueprint | Config hash | Net Profit | Drawdown | Total Orders | Sharpe | Exit activity |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `scenario_exit_proactive` | `074d3833c494` | 10.118% | 17.300% | 243 | 0.526 | 110 proactive exits: 71 target, 39 giveback |
| `scenario_exit_proactive_giveback_tight` | `b20162c96a94` | 9.956% | 17.900% | 383 | 0.511 | 181 proactive exits: 33 target, 148 giveback |
| `scenario_exit_proactive_scratch` | `49d1c008f433` | 5.996% | 18.300% | 1870 | 0.299 | 748 scratch exits + 177 proactive exits |
| `scenario_exit_proactive_scratch_fast` | `6198e1004968` | 3.783% | 18.600% | 2354 | 0.188 | 984 scratch exits + 184 proactive exits |
| `scenario_exit_proactive_scratch_patient` | `d3a568250513` | 7.877% | 18.900% | 1622 | 0.381 | 653 scratch exits + 147 proactive exits |
| `scenario_exit_proactive_scratch_tight_risk` | `8324ba659106` | 5.667% | 17.800% | 1413 | 0.286 | 543 scratch exits + 153 proactive exits |

Interpretation: proactive-only is the best FY2025 performer in this set. The scratch family proves the
path/MFE contract and produces heavy intraday exit activity, but it does not yet improve return or DD
versus proactive-only on FY2025. The next design step should tune scratch thresholds against intraday
trade context (gap behavior, day regime, sector/industry rotation), not add more arbitrary exits.

GitHub comments posted:
- #398 implementation/proof summary
- #406 proactive proof detail
- #407 scratch-flat proof detail
- #386 cache-backed intraday proof follow-up

# FOR_FALK - #386 scenario architecture proof, 2026-06-06

What happened: Claude stopped because of a session limit, after pushing the Scenario A stop wiring.
I picked up the branch and moved the proof from "one possible intraday run" to four marker-proven
direct LEAN runs: A, B, C, and a C parameter variant.

## What changed

- Added Scenario B catalog modules: sector-rotation universe, VIX regime, composite ranking,
  risk/reward filter, buy-stop intraday trigger, vol-adjusted intraday sizing, ATR initial stop,
  and profit-tightening trail.
- Added `scenario_b.py`, `scenario_c.py`, and `scenario_c_wide_entry.py` blueprints. A/B/C now prove
  module-map variation; C-wide proves parameter variation without engine changes.
- Kept the engine untouched in this pass. The only engine diff on the branch remains the existing
  #386 two-clock co-clock validation from the earlier commit.
- Kept production breadth behavior fail-closed, but made fixture blueprints explicitly skip missing
  breadth so proof runs are not vacuous when the runtime has no `breadth_pct_above_200ma` feed.
- Extended `scripts/run_386_arm_direct.py` with `jan2025_proof`, a shorter real LEAN window for
  intraday marker gates.
- After your cache question: confirmed the four completed proof runs did **not** arm the #358 weekly
  cache (`#358 weekly-cache: NOT armed` in logs). Patched the direct runner so future runs default to
  cache-backed trimmed warmup (`WARMUP_DAYS=320` + `WARMUP_WEEKLY_CACHE_FP=<data_fp>`) and keep
  `--full-warmup` as the explicit slow/canonical escape hatch.

## Proof Runs

All four direct LEAN runs used `scripts/run_386_arm_direct.py jan <blueprint>` before the cache-backed
runner patch, generated isolated run dirs under `sweeps/runs/`, exited `lean rc: 0`, and had zero
`DegradedDataError`, zero `ARM-PARITY`, zero `Runtime Error`.

| Run | Config hash | Result JSON | Arm markers | Intraday trigger markers | Intraday sizer markers | Entry lines |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A | `671af6ec6a46` | `direct_scenario_a/jan2025_proof/backtests/2026-06-06_14-20-35/1661479047.json` | 15 | 5071 | 5071 | 66 |
| B | `26d069e6539a` | `direct_scenario_b/jan2025_proof/backtests/2026-06-06_14-28-31/1137834601.json` | 15 | 5071 | 5071 | 694 |
| C | `1962771d8813` | `direct_scenario_c/jan2025_proof/backtests/2026-06-06_14-35-57/1392645598.json` | 15 | 5071 | 5071 | 143 |
| C-wide | `e2d4975532e0` | `direct_scenario_c_wide_entry/jan2025_proof/backtests/2026-06-06_14-43-23/1424912375.json` | 15 | 5071 | 5071 | 69 |

## Interpretation

The core idea now holds empirically: the engine is orchestration, and behavior lives in pluggable
phase modules plus typed params. Daily phases choose and arm candidates; intraday phases trigger and
size at the fire bar; `FIRE_ENTRIES` remains the engine seam. A/B/C/C-wide all ran the same engine
shape with different module or param maps.

Remaining caveat: these are architecture-proof fixtures, not deployable champion configs. The real
M3 entry-trigger work (#396) still has to replace the stub/proof trigger behavior with production
gap/open/morning timing.

# FOR_FALK — overnight run 2026-06-02 (branch feat/276b-1-intraday)

Falk — what shipped while you slept, why, and what's waiting on you. All committed + pushed
(branch tip below). Nothing merged to main; champion still NOT merged (your call).

## #451 Realized giveback candidate

This branch starts the post-scanner pivot: use an actual realized strategy candidate instead of the
headline-good scanner/baseline path whose FY2025 return was mostly unrealized open PnL.

Added `strategies.realized_giveback_no_bull`, a non-fixture module reproducing the
`giveback_tight_no_bull` #408 sweep variant:
- `target_pct=0.06`
- `min_peak_pct=0.04`
- `giveback_from_peak_pct=0.015`
- `require_still_bullish=False`

Archived FY2025 diagnostic for that candidate: `10.960%` return, `17.6%` DD, 117 closed trades,
93.2% closed win rate, and `+$24,815.07` closed-trade PnL. This is not champion promotion yet; the
next run must expose realized net, unrealized PnL, closed win rate, and forced-liquidation behavior
in the leaderboard before any comparison against scanner/baseline.

## What shipped (4 clean commits, all pushed)

1. **Run-class protocol** (`6ae4290`) — you caught real slack: the substrate runs were reported
   with Sharpe/Ret/DD like *validation grades*, but they're *substrate-generation* (mine fuel,
   full-year-OK, metrics-not-grades). Now every run DECLARES `run_class` (validation |
   substrate-generation) in result.json; CONVENTIONS + archive README document the distinction;
   the 5 prior regimes retro-flagged. No redo of the runs (as you said).

2. **FY2020 COVID-crash, 6th regime** (`38aafa5`) — +24.5%/Sharpe 0.881, 19 closed + 8 censored.
   Later extended with **FY2018 correction** (`7b6f41a`, −10.4% — sharp-correction-without-recovery)
   and **FY2019 bull** (`70470bc`, −4.2% — gap-edge underperforms a steady grind-up). The
   **8-regime** learn-substrate (FY2018-2025: correction/crash/grind-bear/recovery/bull/OOS) is now
   COMPLETE + durable (committed off-machine — QC purges backtests in hours). Key mine signal across
   regimes: the gap+confirm edge WINS in crash-recovery (gaps to catch) but LOSES in
   correction-without-recovery + steady-bull (no gaps) — it's volatility/gap-dependent, not a
   steady-trend strategy. FY2020 funnel shows
   the crash regime-gate blocked 62 days (protected through COVID, caught the recovery gaps) — a
   genuine regime signal for the mine vs FY2023's choppy −11.8%.
   - Caught a sharp lesson: QC purges `runtimeStatistics` (the funnel channel) in **~25min** — much
     faster than orders (hours). Fixed: funnel is now captured INLINE at run-time (fail-loud on
     empty, never faked). Documented in CONVENTIONS.

3. **Cloud-tag validator table** (`18c9307`) — the turnkey cloud-side of the #303 (c) cross-check
   (per-trade decision_score + cond_0..7 + outcome across all regimes), so the lab's 5-min-vs-cloud
   honesty-check is one join when the mine runs.

4. **FIX3 symbol-key migration** (`7b0d967`) — behavior-neutral hardening (HQ-approved gap-filler
   while the mine's gated). Unified all 15 symbol-resolution sites onto one `canonical_symbol_key`
   (extracted to `src/engine/symbol_key.py`), killing the recurring case-bug class (the open-coded
   `.value` UPPERCASE vs `.value.lower()` seams). PROVEN behavior-neutral two ways: config_hash
   UNCHANGED + orders BYTE-IDENTICAL (pre/post cloud BT, 46 orders Q4 2025). suite 1152 green.

## ⭐⭐ THE LEARNED SIGNAL — built + it beats the baseline (`91e2348`, #322, no-merge)
The copy→learn payoff, demonstrated. `DvRankPredictor` (in the OracleSignal seam): BCT screen =
the POOL (score≥7), DV-rank = the EDGE (the phase-1 finding). Local-tested on the 2021-2025 traded
substrate (real predictor, fired-subset vs plain-screen baseline):
- Baseline plain score≥7 (n=88): **33% win / +3.5% ret**.
- DvRank, top-DV cap=250 (n=33): **45% win / +11.0% ret** (+12pp win, +7.5pp ret).
- Tighter (cap=100, n=11): **64% win / +19.1% ret**. Monotonic — more DV-selective = better.
- Per-regime: beats baseline FY2021/22/24; honest caveat — doesn't rescue the FY2023 grind-bear.
**The DV-rank learned signal picks materially better trades than George's screen alone.** Not
merged (your call). Full validation next = a cloud-BT of the signal, or the rigorous counterfactual
(your hzgffl24 paste).

## The pivot (your call, mid-session): COPY → LEARN
Stop replicating George's BCT screen; LEARN which conditions/context predict good trades. The
8-regime substrate is the learn-fuel. The sweep is HELD. The mine (#303) ingests the substrate.

## ⭐ THE LEARN RESULT — phase-1 first-cut on the traded set (`b622e59`, PHASE1_FINDINGS.md)
You asked "why idle" — you were right, there was unblocked goal-work I'd mis-scoped. Mined the
committed traded substrate (no lab-paste needed). The headline:
- **George's 8 conditions do NOT separate winners from losers** (score 7.32 on BOTH sides) — the
  empirical case for copy→learn. Replicating the screen perfectly would NOT pick better trades.
- **decision_rank (DV/liquidity) predicts winners, ROBUSTLY across regimes:** top-DV beats
  bottom-DV win-rate in 4/4 testable regimes (+6 to +33pp, incl. losing FY2023) — regime-robust,
  NOT a bull-confound. **The first learnable edge — weight high-DV-rank.** This is the durable result.
- **Single loss mode:** losers all exit via the ~−9% protective stop; winners ride uncapped. (The
  raw "1% vs 88% win" split is provisional/structural — the rigorous lab mine supplies realized
  magnitudes; the rank-separation above is the defensible claim.)
- **#322 hypothesis ready:** BCT screen picks the pool; the learned signal RANKS within it by DV.
hzgffl24's rigorous mine + the untraded counterfactual (your paste) confirm + extend this.

## What's WAITING ON YOU (the one real gate)
**Paste the hzgffl24 lab-resume.** The #303 phase-1 mine (winners-vs-losers on the 6-regime traded
set) is STAGED, gate-free, SAFE — it reads the committed substrate, no backfill, no 160GB RAM risk
(only phase-2's 5-min scoring hits that gate). hzgffl24 is self-gated on your literal paste (post-OOM
conservative). Your one paste fires the mine. HQ (fintrack) has the one-liner for you.

Decisions HQ made under delegated authority (you can veto):
- **Untraded counterfactual = (c)**: the lab scores it from its own 5-min substrate (one consistent
  vendor — the local-daily generator is DEAD, over-counts ~6×), validated against the cloud-tags.
- **RAM gate** relaxed to HQ-level (phase-2 engineering task, not your checkpoint).

## When the mine fires
I pivot to: the cloud-tag cross-check (validator data ready) + the #322 OracleSignal learned-signal
wiring (deferred as speculative until the mine's output shape is known).

Branch tip: `7b0d967` · suite 1152 passing · worktree kumo-qc-276b1.

## #469 Rank-Aware Sizing/Revalidation Follow-Up

After #474, I tested whether the LambdaMART scanner rank should change capital allocation, not just
candidate inclusion. Added `RankAwareHeatcap`, an opt-in sizing phase that preserves the flat
heat-cap contract but scales per-symbol target size by frozen scanner-rank buckets.

FY2025 result: top20 rank sizing is rejected. The flat top20 scanner gate remains best in this
family at `29.133%` return, `18.800%` DD, Sharpe `1.065`, realized `-17328.77`, unrealized
`$46,510.78`. Top50 balanced sizing is the only interesting row: `28.646%` return, `20.100%` DD,
Sharpe `1.002`, realized `-18500.09`, unrealized `$47,193.47`. It improves the top50 flat control
by `+2.970` return points but does not beat top20 flat, and the gain is still unrealized-heavy.

Important mechanism: shrinking weaker-rank sizes can free cash and allow more entries, which
increased churn in the tail-tiny/top-heavy variants. Next useful slice is not "smaller tail"
again; it is top50 balanced plus an entry-count cap, stricter rank>20 revalidation, or realized-exit
overlay. No champion switch.
