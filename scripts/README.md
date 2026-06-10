# scripts/

Hooks/infra shell scripts + the keeper scripts that the **`kumo` CLI wraps** (#221).
The CLI in `cli/` is the entry point — most ad-hoc one-offs were removed; what remains
is invoked via `kumo <group> <cmd>`, not run directly. No secrets — scripts read the
macOS keychain at runtime.

## What it holds
- **Git-hook / infra shell** (`kumo lib`): `install-hooks.sh`, `pre-commit-hook.sh`,
  `check-defaults.sh`, `clean-lean-containers.sh`, `worker-preflight.sh`. These stay as
  shell (they are the hook-install targets); `kumo lib <name>` shells out to them.
- **Data keepers** (`kumo data`): `build_daily_from_parquet.py`, `build_manifest.py`,
  `conform_coarse.py`, `build_etf_universe.py`, `extend_local_data_2026.py`.
- **Backtest keepers** (`kumo bt`): `lean-bt.sh`, `record_bt_result.py`,
  `validate_parity.py`, `collect_results.py`.
- **Scenario proof runners:** `run_386_arm_direct.py`, `run_398_fy_exit_sixpack.py`, and
  `run_408_george_range_30.py` are retained for marker-proven direct LEAN architecture proofs,
  FY2025 exit-management panels, and the 30-variant George-range local BT sweep. The George
  sweep can also refresh CSV artifacts from completed local JSONs with `--rebuild-artifacts`.
- **Combo proof runners:** `run_414_george_combo_30.py` reuses the #408 harness for the second
  30-variant recombination sweep around the best exit, buy-stop, min-hold, and sizing cells.
  From worktrees, pass `--data-folder /Users/falk/projects/kumo-qc/data` so LEAN mounts the
  populated raw cache instead of the skeletal branch-local `data/` folder.
- **George context proof runner:** `run_416_george_context_sweep.py` runs the named #416/#427
  George-context six-pack, first 30-pack, and MFE combo 30-pack variants from
  `sweeps/grids/george_context.py` using the `champion_george_context` base strategy and local
  weekly-cache path. It writes the resolved
  LEAN market-data `data-folder` into every generated project and copies George CSV inputs into
  the generated `/LeanCLI/data/...` project tree; from unusual worktrees, pass `--data-folder`.
  Generated cells compact phase logs and suppress intraday heartbeat logs so FY runs finish with
  parseable LEAN statistics instead of hitting the local log ceiling. Use `--only <variant_id>`
  to retry a failed cell without rerunning the full wave.
- **Scanner ranker proof runner:** `run_scanner_ranker_sweep.py` runs the #446/#448
  scanner-ranker first pack from `sweeps/grids/scanner_ranker.py` with the local LEAN Docker
  adapter. It expects the runtime-safe LambdaMART JSON at
  `storage/bct_lambdamart_qc_safe_v1.json`, which is served to LEAN through the repo ObjectStore
  symlink; pass `--only scanner_lambdamart_top10` or similar for smoke runs.
- **Sweep analysis:** `analyze_408_george_range_30.py` regenerates confidence tables, indicator
  ranges, and Markdown analysis from the George-range aggregate CSVs. `analyze_416_george_context_trades.py`
  reads completed #416 LEAN result JSONs and writes per-variant, per-symbol, and baseline-delta
  trade diagnostics for the George-context 30-pack. `aggregate_416_george_context_reports.py`
  combines wave and retry `summary.csv` files into one ranked report folder for leaderboard and
  diagnostics use.
- **Scanner research hygiene:** `validate_scanner_experiment_log.py` validates the BCT/George scanner
  experiment ledger schema and required provenance fields. `validate_scanner_promotion_gate.py` validates
  the runtime-promotion allow/deny gate. `audit_scanner_feature_parity.py` separates QC-deployable scanner
  features from lab-only or George-derived lift before new ranker tuning.
- **Deploy / live keepers** (`kumo deploy`): `qc_v2_cloud.py`, `gate.py`, `deploy.py`.
- **Held for cutover:** `qc_pe_cloud.py` (KEEP till #216), `build_ticker_sector_map.py`.

## Does NOT hold
- Strategy logic (that's `src/`). New operator commands → add to `cli/`, not new top-level scripts here.
- The 100+ Pe-era experiment one-offs (cancel_/poll_/submit_/fetch_/run_windows_/test_w*) — removed in #221.
