# George Context Framework Extension Plan

## Objective
Extend Kumo so George-style reasoning is represented as first-class framework behavior, not a one-off strategy tweak. The goal is to support top-down industry context, persistent watchlists, selection-gate carry-forward, and repeatable 6/30-pack sweeps without drifting away from phased modular architecture.

## Boundaries
- Keep existing champions behaviorally unchanged unless they explicitly opt in.
- Use RAW LEAN/coarse/parquet data paths only; no adjusted yfinance-derived prices for backtest signals.
- Selection/subscription belongs in `runtime.lean_entry._coarse_selection`; ranking/entry/exit decisions stay in phases.
- Every opt-in knob must be visible in provenance/config hash or logged as runtime provenance.
- Build in independently testable slices; do not jump straight to a 30-pack before contracts are covered.

## Phase 1: Runtime Contract And Build Plumbing
Files:
- `src/engine/config.py`
- `src/engine/engine.py`
- `build/cloud_package.py`
- `tests/build/test_cloud_package.py`
- `tests/strategies/test_champion_george_context.py`
- `src/runtime/README.md`
- `tests/build/README.md` if touched

Plan:
- Add a typed `RuntimeConfig` to `StrategyConfig` with defaults matching current `BctEngineAlgorithm` class attributes.
- Include new runtime knobs for default-off George extensions: `watchlist_carry_max`, `watchlist_carry_min_price`, `watchlist_carry_min_avg_dollar_volume`, optional profile/attention source names.
- Update config hashing and cloud package codegen so runtime settings are emitted into `dist/main.py` and included in provenance.
- Update build tests so field-completeness guards still fail loud when config grows unexpectedly.

Verification:
- Existing champion configs import without changes.
- Existing non-George strategy builds still emit old behavior defaults.
- George context strategy build emits explicit runtime config and hash changes when runtime knobs change.

## Phase 2: Selection-Gate Watchlist Carry
Files:
- `src/runtime/lean_entry.py`
- `src/runtime/watchlist_carry.py`
- `tests/runtime/test_lean_entry.py`
- `tests/runtime/test_watchlist_carry.py`
- `tests/runtime/README.md`

Plan:
- Add pure helper functions for watchlist carry ranking and eligibility.
- In `_coarse_selection`, after normal floors/rank/cap, optionally append bounded watchlist carry names.
- Eligibility: ticker must be in the current coarse feed, must have RAW price, must pass configured liquidity/price guards, and must not duplicate the normal ranked set.
- Store diagnostics on `qc._selection_sources` and `qc._watchlist_carry_today`.
- Log `WATCHLIST_CARRY|date|ticker|reason|price|trailing_dv|score` for every carried ticker.
- Default `watchlist_carry_max=0`, so existing champions do not change.

Verification:
- Selection path still never calls `history()`.
- Default-disabled carry produces byte-equivalent ranked outputs in unit tests.
- Enabled carry appends only eligible names and rejects missing/illiquid names.
- Active-set hash/logging remains deterministic.

## Phase 3: Profile, Industry, And Proxy Inputs
Files:
- `src/runtime/security_profiles.py`
- `src/phases/rebalance/industry_warmup/industry_warmup.py`
- `src/phases/ranking/george_industry_attention/george_industry_attention.py`
- `tests/runtime/test_security_profiles.py`
- `tests/phases/test_george_context_phases.py`

Plan:
- Define one runtime profile contract: `ticker -> sector, industry, subindustry, proxy_etf, source, confidence`.
- Load profile data from local/package source when available; fail soft to `unknown` with diagnostics, not hidden defaults.
- Add proxy ETF scoring input contract for industry warm-up, but keep price/indicator calculation in LEAN/raw paths.
- Harden `IndustryWarmup` so bad/incomplete per-symbol indicator state cannot crash the rebalance phase.
- Upgrade `GeorgeIndustryAttention` watchlist state to carry source, reason, last_seen date, age, confidence, and invalidation reason.

Verification:
- Profile loader handles stocks, ETFs, ADRs, country ETFs, unknowns.
- Industry warm-up can score with profiles, without profiles, and with partial indicators.
- Ranking phase emits stable feature facts suitable for later trade-history analysis.

## Phase 4: George Attention Priors From Lab Data
Files:
- `src/runtime/george_attention.py`
- `tests/runtime/test_george_attention.py`
- `src/strategies/champion_george_context.py`
- `FOR_FALK.md`

Plan:
- Convert transcript-grounded George rows from `kumo-lab` into two optional maps: ticker attention and industry attention.
- Preserve source-role separation: transcript/video discussion, scanner candidate, actual George trade, Falk scanner candidate.
- Use confidence-weighted priors, not binary flags.
- Wire the priors into the George context strategy through `RuntimeConfig`/runtime loader, not hardcoded phase globals.

Verification:
- Rows without direct transcript evidence are excluded or downweighted.
- Strategy still runs if attention files are absent.
- Diagnostics report counts by source role and confidence bucket.

## Phase 5: Backtest Protocol
Files:
- `sweeps/types.py`
- `build/sweep_build.py`
- `sweeps/grids/george_context.py`
- `tests/sweeps/test_sweep_runtime_overrides.py`
- `tests/sweeps/test_george_context_grid.py`
- leaderboard CSV/MD paths currently used by the sweep runner

Plan:
- Extend `SweepConfig` so runtime overrides and disabled phase choices are sweep identity.
- Build swept `rebalance`, `ranking`, and optional `trail` slots into the full `StrategyConfig`.
- First run a 6-pack FY2025 sweep: baseline, industry-only, attention-only, watchlist-only, industry+watchlist, full George context.
- Then run a 30-pack combination sweep over bounded parameters in five waves of six.
- Preserve 6 parallel workers where the runner supports it.
- Export trade history with realized and unrealized PnL, per-symbol exit diagnostics, watchlist source, industry context, and selection source.

Verification:
- Hashes remain backward-compatible for old default sweep configs.
- Runtime override hashes are deterministic and build into `StrategyConfig.runtime`.
- George protocol exposes exactly 6 + 30 named variants.
- Leaderboard appends to existing format, not a disconnected result file.
- Each scenario has orders, realized/unrealized return, max drawdown, trade count, and config hash.
- Trade-history review identifies scanner miss, universe miss, entry timing miss, premature exit, or sizing issue per symbol where possible.

## Phase 6: Documentation And Tracking
Files:
- `AGENTS.md` if present or created for repo-local architecture notes
- `FOR_FALK.md`
- relevant directory `README.md` files

Plan:
- Create or update a GitHub issue before implementation begins.
- Update repo architecture notes after the runtime/phase contract is accepted.
- Write `FOR_FALK.md` summarizing what changed, why, and how to run/interpret the first sweep.

Done Criteria
- Framework exposes George context through typed config and phase contracts.
- Old strategies remain default-compatible.
- Watchlist carry is controlled at the selection gate, not hidden inside ranking.
- Industry/profile/attention inputs are inspectable and confidence-bearing.
- At least one 6-pack backtest completes before scaling to the 30-pack.
