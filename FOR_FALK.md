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
