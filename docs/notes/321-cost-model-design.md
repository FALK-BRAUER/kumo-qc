# GH#321 — Realistic transaction-cost + slippage model (design note)

Parent #320. BLOCKS sweep C. Status: design → build.

## Problem

A frictionless backtest lets the optimizer favour high-turnover params that are brittle and
lose money under real friction. Optimizing without costs = tuning a fake physics model
(Gemini-2.5-pro, 2026-06-02). Costs must land BEFORE sweep C so every swept result is
meaningful. The cost-aware baseline is what the sweep must beat.

## Chosen QC primitives

QC exposes three composable cost primitives. We use all three, at the right scope:

| Primitive | What it models | Our choice |
|---|---|---|
| `BrokerageModel` | broker-wide defaults (fees, slippage, fills, BP, supported order types) | `BrokerageName.INTERACTIVE_BROKERS_BROKERAGE`, `AccountType.MARGIN` |
| `FeeModel` (per security) | commission per fill | QC built-in `InteractiveBrokersFeeModel` |
| `SlippageModel` (per security) | fill price vs reference | `ConstantSlippageModel(slippage_percent)` |

### Why these

1. **`set_brokerage_model(INTERACTIVE_BROKERS_BROKERAGE, MARGIN)`** — IBKR is the LIVE broker
   (CLAUDE.md: paper DUK434934, live U18777181). Setting the IB brokerage model makes the
   backtest's fills, supported-order-type validation, and buying-power model match the venue we
   actually trade. This alone installs `InteractiveBrokersFeeModel` as the default fee model —
   but we ALSO set it explicitly per security (below) so the cost assumption is visible, pinned,
   and unit-testable rather than implicit in a brokerage default that QC could change.

2. **`InteractiveBrokersFeeModel` (QC built-in, NOT hand-rolled).** It encodes IBKR US-equity
   **tiered** commission: **$0.0035/share**, **min $0.35/order**, **max 1.0% of trade value**,
   plus exchange/regulatory pass-throughs. Charter rule = prefer QC built-ins over hand-rolled
   math; re-deriving the IBKR fee schedule by hand is exactly the kind of fragile duplication
   that drifts from the live venue. We wire the built-in and unit-test that the *wiring* and the
   *resulting per-fill commission* behave (min-per-order floor, per-share scaling) rather than
   re-implementing the schedule.

   - Conservative note: IBKR Tiered is cheaper than Fixed for our share counts, but Tiered adds
     variable exchange/clearing fees that the model includes. Using the built-in (which models
     Tiered with the regulatory add-ons) is the conservative, venue-accurate choice. We do NOT
     model the IBKR monthly minimum ($0 for an active account) — out of scope for a per-fill model.

3. **`ConstantSlippageModel(slippage_percent=0.0005)` = 5 bps per side.** Universe = liquid US
   equities (price ≥ $10, trailing-20d ADV ≥ $100M — the selection-gate floors in
   `lean_entry`). For names this liquid, a flat 5 bps is a defensible CONSERVATIVE estimate of
   spread + market impact for the small clip sizes a 10%-position strategy takes.

   - **Why ConstantSlippageModel, not VolumeShareSlippageModel.** `VolumeShareSlippageModel`
     scales impact by (order size / bar volume)². On a **daily** bar that ratio is tiny for our
     ADV≥$100M names → near-zero slippage → it would *under*-penalise turnover, defeating the
     whole point of #321 (Gemini: penalise high-turnover at equal gross edge). On the **intraday
     5-min** bars the bar-volume denominator is small and noisy → impact spikes that are an
     artifact of bar granularity, not real cost. A flat per-side bps is both conservative and
     turnover-monotone (2× the trades ⇒ 2× the slippage cost) — exactly the behaviour the
     acceptance test pins. `slippage_percent` is an EXPLICIT, version-pinned strategy input
     (charter: cost assumptions are a strategy input, must be explicit + version-pinned), not a
     hidden default.

## Where it wires — single code path, no `if cloud`

`InteractiveBrokersFeeModel` / `ConstantSlippageModel` are per-**security**. Securities are
added in two places, both in `lean_entry`:
- the equity universe via `add_universe(self._coarse_selection)` (daily), and
- the intraday 5-min feeds via `_subscribe_intraday` (`add_equity(..., MINUTE)`),
plus SPY (`add_equity`) and VIX (`add_index`).

The clean QC idiom for "apply the same fee/slippage to EVERY equity, however it was added" is a
**security initializer** (`set_security_initializer`). It fires once per security at
subscription time, on BOTH the universe-added and the explicitly-added equities, local and
cloud — a single code path. This avoids touching `_subscribe_intraday` / `_coarse_selection`
(owned by other tracks) entirely.

Wiring lives in a NEW module **`src/runtime/cost_model.py`** (pure-ish, QC-typed at the edges,
unit-testable via stubs) exposing:

```python
def wire_cost_models(qc, *, slippage_percent: float = 0.0005,
                     account_type=None) -> None:
    """Set the IB brokerage model + a security initializer that installs
    InteractiveBrokersFeeModel + ConstantSlippageModel on every EQUITY. Idempotent-safe.
    Indices (VIX) are skipped — they are not tradeable, carry no fees."""
```

`initialize()` gets ONE added line near the end of its setup block (after `set_cash`, before
`self.engine = StrategyEngine(...)`):

```python
from runtime.cost_model import wire_cost_models   # top-of-file import
...
wire_cost_models(self, slippage_percent=self.SLIPPAGE_PERCENT)
```

This is the minimal, localized edit the brief allows. `SLIPPAGE_PERCENT` is a new class attr on
`BctEngineAlgorithm` (default `0.0005`) so it is the single explicit source, overridable per
strategy without editing the helper.

**Why a security initializer and not a per-add call:** keeps the cost assumption in ONE place,
applies uniformly to universe + intraday + SPY (no chance a future feed-add path forgets it),
and never branches on environment. The IB brokerage model's own default fee model is also IB,
so even a security the initializer somehow missed still gets IB fees — defence in depth.

### Cloud/local parity

No environment branch. The security initializer + brokerage model run identically in the LEAN
container (cloud) and local LEAN. Costs are deterministic functions of fill share-count and
price, which are already parity-checked by the existing diff-ladder. Per charter §Parity, this
must be re-validated on the amplifying baseline (champion_intraday) — see re-baseline command.

## Provenance / config-hash impact

`SLIPPAGE_PERCENT` is a runtime class attr on `BctEngineAlgorithm`, NOT in `STRATEGY_CONFIG`, so
it does NOT enter `config_hash` (same treatment as the universe knobs PREFILTER_DV etc., which
are also lean_entry class attrs and the single source of their behaviour). The cost assumption
IS version-pinned: it is fixed in source (this commit), documented here, and logged at startup
via a new `COST_MODEL_INIT|...` log line in `wire_cost_models`. A re-baseline therefore pins to
(git commit + unchanged config_hash + data_fingerprint) — the commit is what records the cost
change, exactly as the universe floors do.

> If the orchestrator/HQ prefers the cost params to live in config_hash, promote `SLIPPAGE_PERCENT`
> into a tiny `cost` Slot/Params later. For #321 we follow the existing lean_entry-knob precedent.

## Tests (alongside, `tests/runtime/test_cost_model.py`)

Following the existing stub-the-QC-primitive pattern (`test_register_warmup_gating.py`):

1. **Wiring** — `wire_cost_models(fake_qc)` calls `set_brokerage_model(INTERACTIVE_BROKERS, MARGIN)`
   and registers a security initializer; the initializer, run on a fake EQUITY security, calls
   `set_fee_model(InteractiveBrokersFeeModel)` + `set_slippage_model(ConstantSlippageModel)`.
2. **Index skipped** — initializer run on a fake INDEX (VIX) security sets NO fee/slippage model.
3. **Slippage application** — `ConstantSlippageModel(0.0005)`: on a buy the fill ref price is
   raised by 5 bps, on a sell lowered (model the per-side directionality with the QC slippage
   contract via a stubbed order); flat-bps ⇒ turnover-monotone.
4. **Commission math** — `InteractiveBrokersFeeModel`: a 100-share order hits the **$0.35/order
   floor** (100 × $0.0035 = $0.35 → at/above floor); a 10-share order is floored to **$0.35**
   (10 × $0.0035 = $0.035 < $0.35); a 10,000-share order = **$35.00** ($0.0035 × 10,000, below
   the 1% cap). Asserts the min-per-order floor and per-share scaling.
5. **Initialize wires it** — driving the real `BctEngineAlgorithm.initialize()` body with the
   existing init-stub harness records that `wire_cost_models` ran (brokerage model + initializer
   set).
6. **Behavioral / turnover-penalty** (acceptance, GH#321): two synthetic fill streams at EQUAL
   gross edge — one high-turnover (N round-trips), one low-turnover (1 round-trip) — the
   high-turnover net is strictly lower after fees+slippage. Pins the optimizer-relevant property.

Tests 3/4 exercise QC's own `InteractiveBrokersFeeModel` / `ConstantSlippageModel` when importable;
in the dev venv (no `AlgorithmImports`) they assert against our own conservative arithmetic
reference for the SAME schedule, so the math is locked even where the QC classes are absent. The
wiring tests (1/2/5) always run via stubs.

## Re-baseline command for the orchestrator (DO NOT run here — orchestrator owns the cloud stream)

Re-baseline **champion_intraday** (the forward champion, the amplifying mechanic) WITH costs.
`champion_asis` is a retired blind-entry fixture (is_fixture=True) and is NOT the baseline.

```bash
# from /Users/falk/projects/kumo-qc-main (or the integration worktree), on the branch that has
# this cost-model commit merged, with dist/ rebuilt from champion_intraday:

# 1. build champion_intraday into dist/ (single code path; emits dist/main.py + _metadata.py)
PYTHONPATH=src:build python3 -c \
  "from build.cloud_package import build; from pathlib import Path; \
   r=build('strategies.champion_intraday', dist_dir=Path('dist')); print('built', r.config_hash)"

# 2. local full-FY2025 sanity (cost-aware) — confirms the model is active + green locally
DOCKER_HOST=unix:///Users/falk/.docker/run/docker.sock \
  bash scripts/measure_base_baseline.sh local   # (point the script's build target at champion_intraday)

# 3. CLOUD smoke interop gate FIRST (never run FY before smoke passes)
python3 scripts/qc_v2_cloud.py deploy
python3 scripts/qc_v2_cloud.py smoke

# 4. CLOUD full-FY2025 re-baseline (ground truth) — costs active local AND cloud (#321 acceptance)
python3 scripts/qc_v2_cloud.py run champion_intraday_costs_fy2025 5
python3 scripts/qc_v2_cloud.py orders <backtestId>   # diff-ladder: confirm fills carry IB fees

# Record the cost-aware baseline in bt-results.csv on main, provenance-pinned:
#   (git commit of this cost-model change + config_hash from step 1 + data_fingerprint 90f2d7e3)
# Report the metrics trio: Sharpe / Return% / Drawdown%.
```

Acceptance verification the orchestrator should confirm from the cloud run:
- fills in `/orders` carry a non-zero IB commission (fee model active on cloud), and
- the cost-aware Sharpe/Return/DD trio is the new baseline the sweep must beat.
