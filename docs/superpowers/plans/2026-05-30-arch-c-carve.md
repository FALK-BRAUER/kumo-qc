# ARCH-C: Carve main.py → Phase Modules — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faithful decomposition of `baseline-oracle-v0` (`main.py` 609 lines, champion-asis-v1) into phase modules wired to `StrategyEngine`. Prove LOCAL parity ±0.01 Sharpe vs oracle. No cleanup. No behavior change.

**Architecture:** Thin-wrapper approach — phase modules delegate to existing oracle helper functions (score_symbol, _adx_wilder, etc.) preserved in `phases/shared/oracle_helpers.py`. Behavioral identity guaranteed by preserving every oracle quirk: G3 Phase-3 stop, dollar-vol tiebreak, pre-filter SMA200/cloud, committed_cash heat cap, exit-before-regime ordering, E121 VIX-tier (capacity only), E28 VIX-pct (block default OFF), E51 parabolic (default ON, 25%).

**Tech Stack:** Python 3.11+, pytest, StrategyEngine (ARCH-A), cloud_package.py (ARCH-G), lean-bt.sh (local LEAN docker).

**Spec:** `docs/superpowers/specs/2026-05-30-phase-engine-design.md` + `baseline-oracle-v0` tag  
**Ticket:** ARCH-C #189  
**Gate:** fintrack reviews parity proof (Sharpe ±0.01 + same selection per day + same fills on LOCAL run) before ARCH-C merges. Cloud parity deferred until #182 unified loader lands.

**CRITICAL — FINTRACK ENTRY CONDITIONS:**
1. Carve = faithful decomposition. DO NOT improve, clean up, or restructure oracle logic.
2. Preserve EVERY quirk: G3 stop, dollar-vol tiebreak, pre-filter L538-552, committed_cash loop, exit-runs-before-regime-gate ordering, E121 VIX-tier.
3. Parity proof = artifact + marker + Sharpe table to fintrack. Not self-certified.
4. #182 dual-path loader: carve uses the LOCAL path (polygon JSON from file) — same as oracle. Cloud parity deferred to #182 fix.

---

## Phase Boundary Map (from oracle main.py)

| Phase Kind | Oracle Location | Module Name |
|------------|----------------|-------------|
| universe.source | Initialize L283-320 | `polygon_local` |
| exit_hard | _rebalance L429-468 (runs FIRST, always) | `kijun_g3_exits` |
| regime | _rebalance L470-520 | `vix_ichimoku_tier` + `spy_200ma` + `vix_percentile` |
| signal | _rebalance L522-590 (score_symbol_native) | `bct_score_full` |
| eligibility | _rebalance L527-535 (polygon filter + held + open orders) | `polygon_daily_filter` |
| ranking | _rebalance L589-590 (sort score DESC, dollar_vol DESC) | `score_dollarvol` |
| sizing | _rebalance L591-609 (flat-10%, committed_cash) | `flat_pct_heatcap` |
| diagnostics | Initialize VERSION_MARKERs + REBALANCE log | `version_marker` |

**Shared helpers** (oracle functions preserved verbatim):
- `score_symbol`, `_adx_wilder`, `_resample_weekly`, `_fetch_ohlcv`, `score_symbol_native`, `BCTUniverseFilter`
- `_daily_vals`, `_seed_weekly`, `_has_open_orders`, `_register_indicators`

---

## File Map

| File | Role |
|------|------|
| `src/phases/shared/oracle_helpers.py` | All oracle helper functions verbatim — score_symbol, _adx_wilder, etc. |
| `src/phases/exit/kijun_g3_exits/kijun_g3_exits.py` | Exit phase: Kijun stop + G3 cloud-bottom + cloud/weekly-kijun (optional) |
| `src/phases/regime/vix_ichimoku_tier/vix_ichimoku_tier.py` | E121 VIX-tier slot capacity (NOT a blocker — emits max_positions to ctx) |
| `src/phases/regime/spy_200ma/spy_200ma.py` | E40b SPY>200MA block |
| `src/phases/regime/vix_percentile/vix_percentile.py` | E28 VIX-pct gate (default OFF) |
| `src/phases/universe/polygon_local/polygon_local.py` | Universe loader — local polygon JSON path only (cloud path after #182) |
| `src/phases/signal/bct_score_full/bct_score_full.py` | BCT 8-condition score with pre-filter + parabolic block + dollar-vol tiebreak |
| `src/phases/sizing/flat_pct_heatcap/flat_pct_heatcap.py` | POSITION_PCT=10% + committed_cash heat-cap loop |
| `src/phases/diagnostics/version_marker/version_marker.py` | VERSION_MARKER logs + REBALANCE summary |
| `src/main_champion_asis.py` | STRATEGY_CONFIG for champion-asis-v1 wiring all phases |
| `src/tests/integration/test_champion_asis_parity.py` | Integration test: local oracle BT vs engine BT, assert ±0.01 Sharpe |

---

## Task 0: Shared Oracle Helpers

**Files:**
- Create: `src/phases/shared/__init__.py`
- Create: `src/phases/shared/oracle_helpers.py`

- [ ] **Step 1: Extract oracle helper functions verbatim**

Copy from `main.py` lines 44-191 (functions + BCTUniverseFilter):
`_mid`, `_adx_wilder`, `_resample_weekly`, `_fetch_ohlcv`, `score_symbol`, `score_symbol_native`, `BCTUniverseFilter`

Create `src/phases/shared/oracle_helpers.py` — copy exact code, no changes.

```bash
mkdir -p algorithm/performance_bct/src/phases/shared
touch algorithm/performance_bct/src/phases/shared/__init__.py
```

- [ ] **Step 2: Write a smoke test**

Create `src/phases/shared/tests/test_oracle_helpers_import.py`:
```python
def test_oracle_helpers_importable():
    from phases.shared.oracle_helpers import score_symbol, _adx_wilder, BCTUniverseFilter
    assert callable(score_symbol)
    assert callable(_adx_wilder)
```

- [ ] **Step 3: Run**
```bash
cd algorithm/performance_bct/src && .venv/bin/python -m pytest phases/shared/tests/ -v
```
Expected: PASS (import only — no LEAN dependency needed).

- [ ] **Step 4: Commit**
```bash
git add algorithm/performance_bct/src/phases/
git commit -m "feat(arch-c): shared oracle_helpers — score_symbol/_adx_wilder/BCTUniverseFilter verbatim"
```

---

## Task 1: Exit Phase — kijun_g3_exits

**Files:**
- Create: `src/phases/exit/kijun_g3_exits/kijun_g3_exits.py`
- Create: `src/phases/exit/kijun_g3_exits/tests/test_kijun_g3_exits.py`

- [ ] **Step 1: Write the failing test**

```python
from engine import PhaseContext, PhaseResult, BarState
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from datetime import datetime

def test_kijun_exit_emits_exit_intent_when_below_kijun():
    # FakePortfolio with one holding where close < kijun
    phase = KijunG3Exits(params={}, logger=None)
    # ... inject ctx with one held position, close=90, kijun=100
    # result.exit_intents should contain one OrderIntent for that symbol
    ...

def test_g3_exit_triggers_when_below_cloud_bottom_after_56d_15pct():
    ...

def test_no_exit_when_close_above_kijun():
    ...
```

- [ ] **Step 2: Implement kijun_g3_exits.py**

Extract oracle logic from `_rebalance` L429-468. The phase:
- Reads ctx.qc.portfolio (held positions)
- Reads ctx.bar_state.phase_outputs["indicators"] (daily vals)
- Emits `OrderIntent(qty=-holding.quantity)` into `ctx.bar_state.exit_intents` for each stop
- Reads `_position_meta` from ctx for G3 phase tracking
- Returns `PhaseResult(blocked=False)` — exits never block

- [ ] **Step 3: Run tests**
```bash
cd algorithm/performance_bct/src && .venv/bin/python -m pytest phases/exit/kijun_g3_exits/tests/ -v
```

- [ ] **Step 4: Commit**
```bash
git commit -m "feat(arch-c): kijun_g3_exits phase — Kijun stop + G3 cloud-bottom (TDD)"
```

---

## Task 2: Regime Phases

**Files:**
- Create: `src/phases/regime/spy_200ma/spy_200ma.py` + tests
- Create: `src/phases/regime/vix_ichimoku_tier/vix_ichimoku_tier.py` + tests
- Create: `src/phases/regime/vix_percentile/vix_percentile.py` + tests

- [ ] **Step 1: Write and test spy_200ma**

Oracle logic: L514-520. If SPY < SPY_SMA200 → `blocked=True`. Writes to ctx "REGIME_BLOCK" log.

```python
def test_spy_below_200ma_blocks():
    phase = SpySma200(params={}, logger=None)
    # ctx.qc.securities["SPY"].price = 400, sma200 = 450
    result = phase.evaluate(ctx)
    assert result.blocked is True

def test_spy_above_200ma_passes():
    ...
```

- [ ] **Step 2: Write and test vix_ichimoku_tier**

Oracle logic: L470-480. This is NOT a blocker — it just sets max_positions in ctx. Emits to BarState:
`ctx.bar_state.phase_outputs["vix_tier"] = {"max_positions": N, "tier": 1_or_2}`

```python
def test_vix_above_cloud_top_sets_tier2_unlimited():
    ...

def test_vix_below_cloud_top_sets_tier1():
    ...
```

- [ ] **Step 3: Write and test vix_percentile (default OFF)**

Oracle logic: L482-499. Only blocks when `params.get("vix_percentile_enabled") == True`.

- [ ] **Step 4: Commit**
```bash
git commit -m "feat(arch-c): regime phases — spy_200ma + vix_ichimoku_tier + vix_percentile (TDD)"
```

---

## Task 3: Universe Phase — polygon_local

**Files:**
- Create: `src/phases/universe/polygon_local/polygon_local.py` + tests

- [ ] **Step 1: Write and test polygon_local**

Oracle logic: L283-314 LOCAL PATH ONLY (not cloud path — #182 deferred).

Phase initialize():
- Reads polygon JSON from file (same candidates as `_load_polygon_universe()`)
- Stores as `ctx.bar_state.phase_outputs["polygon_universe"]` = dict keyed by date_str

Phase evaluate() per-bar:
- Gets today's date_str
- Filters to today's tickers from polygon_universe
- Writes `ctx.bar_state.ranked_candidates` with today's eligible tickers

```python
def test_polygon_local_filters_to_today_tickers():
    # Inject universe with {"2025-01-02": ["AAPL", "MSFT"]}
    # ctx.time = 2025-01-02
    # ranked_candidates should be ["AAPL", "MSFT"]
    ...

def test_polygon_local_empty_date_uses_full_set():
    # If date not in universe, ranked_candidates = all unique tickers (???)
    # Actually: fail-loud per charter — raise or return empty, never silently 326
    ...
```

- [ ] **Step 2: Commit**
```bash
git commit -m "feat(arch-c): polygon_local universe phase — local JSON only, fail-loud on empty date (TDD)"
```

---

## Task 4: Signal Phase — bct_score_full

**Files:**
- Create: `src/phases/signal/bct_score_full/bct_score_full.py` + tests

- [ ] **Step 1: Write and test**

Oracle logic: L527-590 (full entry selection including pre-filter + score + parabolic + dollar-vol tiebreak).

Phase evaluate():
- Iterates `ctx.bar_state.ranked_candidates` (from polygon_local)
- Applies pre-filter (SMA200/cloud, L538-551)
- Applies BCT score (delegates to `score_symbol_native` from oracle_helpers)
- Applies parabolic block (E51, L556-570)
- Computes dollar-vol tiebreak (L572-587)
- Writes `ctx.bar_state.sized_orders` = sorted list of OrderIntent stubs (no qty yet — sizing does that)

```python
def test_pre_filter_skips_below_sma200():
    ...

def test_bct_score_below_min_score_excluded():
    ...

def test_parabolic_block_excludes_13d_runup():
    ...

def test_ranking_is_score_desc_then_dollarvol_desc():
    ...
```

- [ ] **Step 2: Commit**
```bash
git commit -m "feat(arch-c): bct_score_full signal phase — pre-filter + score + parabolic + dollar-vol tiebreak (TDD)"
```

---

## Task 5: Sizing Phase — flat_pct_heatcap

**Files:**
- Create: `src/phases/sizing/flat_pct_heatcap/flat_pct_heatcap.py` + tests

- [ ] **Step 1: Write and test**

Oracle logic: L591-609. POSITION_PCT=10% of portfolio value. committed_cash heat-cap: stop adding when cash exhausted. Respects slot count from regime (vix_ichimoku_tier max_positions).

Phase evaluate():
- Reads `ctx.bar_state.sized_orders` (ranked candidates from signal)
- Reads portfolio cash + total value from ctx.qc
- Reads `max_positions` from `ctx.bar_state.phase_outputs["vix_tier"]` (or MAX_POSITIONS=9999)
- Counts open positions
- Fills qty for each candidate up to cash limit
- Writes `ctx.bar_state.sized_orders` with qty populated

```python
def test_positions_limited_by_cash():
    ...

def test_heat_cap_stops_on_exhaustion():
    ...

def test_10pct_sizing():
    ...
```

- [ ] **Step 2: Commit**
```bash
git commit -m "feat(arch-c): flat_pct_heatcap sizing — POSITION_PCT=10% + committed_cash heat cap (TDD)"
```

---

## Task 6: Diagnostics Phase + champion-asis-v1 STRATEGY_CONFIG

**Files:**
- Create: `src/phases/diagnostics/version_marker/version_marker.py`
- Create: `src/main_champion_asis.py`

- [ ] **Step 1: version_marker phase**

Logs the oracle's VERSION_MARKER strings + REBALANCE summary on each bar.

- [ ] **Step 2: champion-asis-v1 STRATEGY_CONFIG**

```python
# src/main_champion_asis.py
STRATEGY_CONFIG = {
    "name": "champion-asis-v1",
    "version": "1.0.0",
    "description": "Faithful carve of baseline-oracle-v0 (G3/flat-10%/E40d). Carve parity target.",
    "phases": {
        "universe": {"module": "phases.universe.polygon_local", "enabled": True, "params": {}},
        "exit_hard": [
            {"module": "phases.exit.kijun_g3_exits", "enabled": True, "params": {
                "cloud_exit_enabled": False,
                "weekly_kijun_exit_enabled": False,
                "phase3_days": 56,
                "phase3_pnl": 0.15,
            }},
        ],
        "regime": [
            {"module": "phases.regime.vix_ichimoku_tier", "enabled": True, "params": {}},
            {"module": "phases.regime.spy_200ma", "enabled": True, "params": {}},
            {"module": "phases.regime.vix_percentile", "enabled": True, "params": {"vix_percentile_enabled": False}},
        ],
        "signal": {"module": "phases.signal.bct_score_full", "enabled": True, "params": {"min_score": 7, "parabolic_threshold": 0.25}},
        "sizing": {"module": "phases.sizing.flat_pct_heatcap", "enabled": True, "params": {"position_pct": 0.10}},
        "diagnostics": [
            {"module": "phases.diagnostics.version_marker", "enabled": True, "params": {}},
        ],
    },
    "invariants": {"no_count_caps": True, "no_time_exits": True, "explicit_exposure_only": True},
}
```

- [ ] **Step 3: Commit**
```bash
git commit -m "feat(arch-c): champion-asis-v1 STRATEGY_CONFIG + version_marker diagnostics"
```

---

## Task 7: _fire() Implementation in Engine

**Files:**
- Modify: `src/engine/engine.py` — implement _fire() with LEAN order submission
- Modify: `src/engine/tests/test_engine.py` — add _fire() tests

- [ ] **Step 1: Implement _fire()**

```python
def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
    if sentinel is FIRE_ENTRIES:
        for intent in ctx.bar_state.sized_orders:
            if intent.qty > 0:
                ctx.qc.market_on_open_order(intent.ticker_symbol, intent.qty)
                self._fired_entries += 1
    elif sentinel is FIRE_EXITS:
        for intent in ctx.bar_state.exit_intents:
            ctx.qc.market_on_open_order(intent.ticker_symbol, intent.qty)  # qty is negative
            self._fired_exits += 1
    elif sentinel is FIRE_ADDS:
        for intent in ctx.bar_state.add_intents:
            ctx.qc.market_on_open_order(intent.ticker_symbol, intent.qty)
            self._fired_adds += 1
    elif sentinel is FIRE_TRIMS:
        for intent in ctx.bar_state.trim_intents:
            ctx.qc.market_on_open_order(intent.ticker_symbol, intent.qty)
```

Also wire fired_entries/exits/adds counters to log_tick().

- [ ] **Step 2: Commit**
```bash
git commit -m "feat(arch-c): wire _fire() — LEAN market_on_open_order + fired counters"
```

---

## Task 8: Parity Proof — LOCAL BT oracle vs engine

**Gate: send diff to fintrack before claiming pass.**

- [ ] **Step 1: Ensure data symlink exists in worktree**
```bash
# From worktree root
ls data/equity/usa/daily 2>/dev/null || (rm -rf data && ln -s /Users/falk/projects/kumo-qc/data data)
```

- [ ] **Step 2: Run oracle BT (baseline-oracle-v0 code)**
```bash
DOCKER_HOST=unix:///Users/falk/.docker/run/docker.sock \
bash scripts/lean-bt.sh algorithm/performance_bct FY2025-oracle 2025-01-01 2025-12-31
```
Record: Sharpe, return%, DD%, orders from BT output JSON.

- [ ] **Step 3: Run engine BT (champion-asis-v1 STRATEGY_CONFIG)**
```bash
DOCKER_HOST=unix:///Users/falk/.docker/run/docker.sock \
bash scripts/lean-bt.sh algorithm/performance_bct FY2025-engine 2025-01-01 2025-12-31
# (using main_champion_asis.py as main.py entry point)
```

- [ ] **Step 4: Diff results**

| Metric | Oracle | Engine | Delta | Pass? |
|--------|--------|--------|-------|-------|
| Sharpe | 1.079 | ? | ? | ≤0.01 |
| Return% | +33.3% | ? | ? | |
| DD% | 11% | ? | ? | |
| Orders | 232 | ? | ? | |
| Selection overlap | 100% | ? | % | |

Delta Sharpe ≤ 0.01 → PASS. If FAIL → first-divergence walk (#173) on closedTrades.

- [ ] **Step 5: Report to fintrack**

Send: BT artifact paths, VERSION_MARKER confirmed, parity table, selection-per-day comparison (spot check 5 dates). Do NOT claim pass without fintrack confirmation.

- [ ] **Step 6: Rebuild _cloud/ and verify**
```bash
cd algorithm/performance_bct && python3 build/cloud_package.py build && python3 build/cloud_package.py verify
```

- [ ] **Step 7: Commit parity results to bt-results.csv on main**

After fintrack confirms PASS, cherry-pick or direct commit to main with the parity row.

---

## Self-Review

**Spec coverage:**
- §4.1 PHASE_ORDER with exits-first (kijun_g3_exits before regime): ✅ Task 1 before Task 2
- §4.3 Block = entry side only, exits always run: ✅ kijun_g3_exits has blocked=False
- §4.4 Adds flow-back: N/A — no adds in champion-asis-v1 ✅
- §4.5 PhaseInterface: ✅ all phases implement it
- §4.6 Charter invariants: ✅ no count caps, heat-cap is explicit cash check not max_positions
- §9 Structural guardrails: ✅ fail-loud in polygon_local, marker-verify in diagnostics
- §12 Migration step 2: ✅ parity ±0.01 vs oracle tag

**Placeholder scan:** Task 7 `ticker_symbol` attribute on OrderIntent needs to be verified — OrderIntent currently has `ticker: str`, engine needs to resolve the LEAN Symbol object. Check this before implementing _fire().

**Type consistency:** `ctx.bar_state.sized_orders` = `list[OrderIntent]`. Task 4 writes it, Task 5 reads + modifies it, Task 7 fires from it. All consistent. `ctx.bar_state.phase_outputs["vix_tier"]["max_positions"]` = int. Written by Task 2 vix_ichimoku_tier, read by Task 5 flat_pct_heatcap. Consistent.

**Open issue — indicates further discussion needed before Task 7:** The engine's `_fire()` calls `ctx.qc.market_on_open_order(symbol, qty)` but `OrderIntent.ticker` is a str (e.g. "AAPL"). The LEAN API needs a Symbol object, not a string. Options: (a) store the LEAN Symbol in OrderIntent, (b) resolve str→Symbol in _fire() via `ctx.qc.securities`. Resolve before Task 7.
