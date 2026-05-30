# Phase-Based Strategy Engine — Design Spec
**Date:** 2026-05-30  
**Status:** Approved (Falk + fintrack)  
**Epic:** #200  
**Tickets:** ARCH-A #187 through ARCH-M #199  
**Refs:** docs/ARCHITECTURE.md, docs/PHASES.md, algorithm/performance_bct/src/main.py.example

---

## 1. Goal

Replace the monolithic `algorithm/performance_bct/main.py` (609 lines, dual-path universe loader, implicit exposure caps, no parity guarantee) with a phase-based engine where:

- Strategy = `STRATEGY_CONFIG` dict of composable phases over one engine
- Single code path local + cloud (local = harness emulating cloud)
- Every result is artifact-backed, marker-verified, auto-rejected if not
- Structural guardrails make artifact classes (phantom Sharpes, silent bypasses, dual-path divergence) impossible rather than just documented

---

## 2. Operating Model (Sonnet + Opus)

**Sonnet (orchestrator):** execution, worker dispatch, BT runs, packaging, doc consolidation, board movement. Fast loop. Autonomy on agreed-scope diagnostic/verification runs.

**Opus (fintrack HQ):** judgment calls, verification, architecture decisions, methodology design (DSR/PBO, parity gates). Reviews artifacts (diffs, markers, Sharpes) against source — not summaries.

**Never self-certify.** Every pass/fail routes through artifact + marker + commit to fintrack. Structural guardrails (fail-loud, marker-verify, auto-reject-no-artifact, parity-on-`_cloud/`) are the verification substitute at the build layer — not optional.

---

## 3. Phase-0: Pre-flight Hygiene (before any engine code)

Main branch is NOT clean enough to build on as-is. Phase-0 resolves ambiguity and removes contamination hazards. Authorized by Falk.

### Non-destructive (immediate):
1. `git tag baseline-oracle-v0` — freeze the parity oracle. ARCH-C carve diffs against this tag forever.
2. Fix `.gitignore`: add `*/backtests/`, `*.log` at root, `__pycache__/`.
3. Untrack/move root noise: `fy2025.log`, `w4_*.log`, `list_backtests*.py`, `fetch_logs.py` → `scripts/` or gitignored.
4. Resolve `lean.json` / `lean-api.json` ambiguity: one canonical config, one documented in README.

### Destructive (PENDING Falk explicit auth — do NOT execute yet):
5. Archive 6 dead algorithm dirs: `backtest_bct`, `live_bct`, `minimal_bct`, `test_lean`, `test_nowarmup`, `irprecisionfalcon` + stray root files (`live_bct.py`, `bct_signal.py`, `universe_filter.py`). `performance_bct` = only live algorithm. Git history preserves all. Pre-req: verify no uncommitted work in any worktree first.
6. Prune stale worktrees 49→3. Keep: `main`, `kumo-qc-p3b` (pyramid, unmerged), `kumo-qc-182` (#182 in flight). Pre-req: uncommitted-work check first.

---

## 4. Core Architecture

### 4.1 PHASE_ORDER — canonical with sentinel tokens

```python
PHASE_ORDER = [
    "rebalance", "universe", "signal", "regime", "ranking",
    "entry_selection", "entry_timing", "sizing",
    "reentry", "eligibility", "portfolio_risk", "cash",
    FIRE_ENTRIES,                                    # sentinel — submit entry orders
    "stops_initial", "trail",
    "exit_hard", "exit_target", "exit_regime", "exit_rotation",
    FIRE_EXITS,                                      # sentinel — submit exit orders
    "adds",
    FIRE_ADDS,                                       # sentinel — mini re-run risk+cash → submit adds
    "profit",
    FIRE_TRIMS,                                      # sentinel — submit trim orders
    "diagnostics", "circuit_breaker",
]
```

Engine loop: `if item is sentinel → fire_<x>(ctx); else → run phase`. Sentinels are declarative data — fire boundaries cannot detach from their position. Dependency validation and phase-iteration skip sentinels (cheap `isinstance` check).

### 4.2 PhaseContext — split design (Option C)

```python
class PhaseContext:
    # LEAN read-only refs (never mutated by phases)
    qc: QCAlgorithm
    time: datetime
    data: Slice
    
    # BarState — fresh every bar, written via apply() only
    bar_state: BarState

class BarState:
    ranked_candidates: list[str]   # after ranking phase
    sized_orders: list[OrderIntent]
    add_intents: list[OrderIntent]
    exit_intents: list[OrderIntent]
    trim_intents: list[OrderIntent]
    blocks: list[BlockEvent]       # per-candidate eligibility/portfolio_risk blocks
    phase_outputs: dict            # kind → PhaseResult, for downstream reads
```

`ctx.apply(kind, result)` rejects double-write of same `kind` (catches chain-ordering bugs).  
BarState = the serialization unit for parity diffing; trivial to unit-test via `FakeBarState`.

### 4.3 Block propagation

Block set = `{regime, cash, circuit_breaker}` — these abort the bar entirely.  
`eligibility` and `portfolio_risk` emit per-candidate `BlockEvent` into `BarState.blocks`, no bar-abort.  
`diagnostics` and `circuit_breaker` always run regardless of prior blocks.

### 4.4 Adds flow-back — mini re-run (Option A)

After `adds` emits add-intents into `BarState.add_intents`, before `FIRE_ADDS`:
- Adds phase handles lot sizing internally (via `lot_progression` / `lot_size_dollars` params) — no separate sizing re-run
- Engine re-runs the SAME `portfolio_risk` + `cash` phase instances over `add_intents` only (exposure + margin check)
- Uses LIVE portfolio state (post-entry fills, post-exit closes) — not start-of-bar snapshot
- Rationale: exits free cash/exposure that adds should use in the same bar; a single pre-exit risk snapshot would miss this
- Same phase instances — no re-instantiation, stateful loggers/markers stay consistent

### 4.5 PhaseInterface contract

```python
class PhaseInterface(ABC):
    # Class attributes (declarative metadata)
    PHASE_KIND: str                          # e.g. "adds"
    REQUIRES_UPSTREAM: list[str]             # e.g. ["signal", "sizing"]
    PROVIDES_DOWNSTREAM: list[str]           # e.g. ["add_intents"]

    # Abstract — must implement
    @abstractmethod
    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...
    
    @property
    @abstractmethod
    def version_marker(self) -> str: ...

    # Concrete — shared defaults
    @property
    def enabled(self) -> bool: return self._params.get("enabled", True)
    
    def validate_config(self, params: dict) -> None: ...  # raises on bad params

class PhaseResult:
    decision: Any
    blocked: bool
    reason: str
    facts: dict    # structured log payload
    metrics: dict
```

`evaluate()` runs once per bar. Iterates candidates internally (`ctx.bar_state.ranked_candidates`). Not called per-candidate by engine.

### 4.6 Charter invariants — enforced at engine init

```python
FORBIDDEN_PARAMS = {
    "max_positions", "max_lots", "max_entries_per_day",
    "max_hold_days", "exit_if_flat_after_days",
    "max_adds", "max_pyramid_lots", "max_position_adds",  # count caps
}

def validate_invariants(config):
    for phase_cfg in config["phases"].values():
        for param_key in phase_cfg.get("params", {}):
            if param_key in FORBIDDEN_PARAMS:
                raise CharterViolation(f"{param_key} is a count cap — forbidden")
    if config["phases"].get("adds", {}).get("enabled"):
        if not config["phases"].get("portfolio_risk", {}).get("enabled"):
            raise ImplicitExposureViolation("adds requires portfolio_risk.gross_exposure_cap")
```

Engine refuses to start on charter violation. NO silent fallback.

### 4.7 Universe loader — unified (resolves #182)

```python
# ONE loader, both envs. No if-cloud branch.
def _load_universe(self):
    poly = json.loads(self.object_store.read(UNIVERSE_KEY))
    if not poly:
        raise UniverseLoadError("universe empty — engine refuses to start")
    self._polygon_universe = poly

# Local harness mocks ObjectStore to serve the same JSON
# Cloud code runs verbatim locally
```

Fail-loud on empty: 8b50c1a bypassed silently → corrupted selection for days. The guard kills that class.

### 4.8 STRATEGY_CONFIG hash

```python
import hashlib, json

def _log_strategy_definition(self, config):
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    config_hash = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    self.qc.Log(f"STRATEGY_INIT|hash={config_hash}|name={config['name']}|version={config['version']}")
```

Same serialization on cloud and local → deterministic hash. Logged on every init, verified on deploy.

---

## 5. Source Tree

```
algorithm/performance_bct/
  src/
    main.py                          # STRATEGY_CONFIG only + engine.run(self)
    engine/
      engine.py                      # StrategyEngine, PHASE_ORDER, sentinels
      base.py                        # PhaseInterface, PhaseResult, BarState, PhaseContext
      context.py                     # PhaseContext, BarState
      logger.py                      # ComponentLogger
      README.md
      tests/
        test_engine.py
        test_phase_order.py
        test_invariants.py
        fixtures/
          fake_qc.py                 # FakeQCAlgorithm (Portfolio, Securities, Time, Log)
          fake_bar_state.py
          stub_phases.py             # 2-3 trivial stubs for engine loop tests

    phases/
      universe/polygon_daily/
      signal/bct_score/
      regime/vix_threshold/ + spy_200ma/
      ranking/dollar_volume/
      entry/buy_stop_kijun/
      sizing/risk_based_fixed/
      eligibility/already_held_check/
      portfolio_risk/gross_exposure_cap/
      stops/atr_initial/
      trail/kijun_trail/
      exit/cloud_breach/ + weekly_kijun/
      cash/no_margin/
      rebalance/daily_close/
      diagnostics/parity_logger/ + version_marker/
      adds/pe_signal_renewed/ + pe_rampup_antikelly/  # after #182

    tests/
      integration/
        test_strategy_baseline.py
        test_cloud_local_parity.py
      harness/
        bt_runner.py
        parity_diff.py              # diffs _cloud/ artifact, not src/
        assertion_lib.py
      conftest.py

  build/
    cloud_package.py                # flatten src/ → _cloud/, rewrite imports

  _cloud/                           # generated, git-tracked
```

---

## 6. Cloud Packaging

`build/cloud_package.py` flattens `src/` → `_cloud/`, skips `tests/`, rewrites imports:

```
src/phases/adds/pe_rampup_antikelly/pe_rampup_antikelly.py
  → _cloud/phase_adds_pe_rampup_antikelly.py

from phases.adds.pe_rampup_antikelly import PeRampupAntikelly
  → from phase_adds_pe_rampup_antikelly import PeRampupAntikelly
```

`_cloud/` is git-tracked. Diff visibility on every deploy. Parity tests run against `_cloud/` artifact, not `src/`.

---

## 7. Main Branch Merge Gate (7 checks, CI-enforced)

1. Phase unit tests pass (`pytest phases/<kind>/<impl>/tests/`)
2. Engine integration test passes (phase plugged into baseline strategy)
3. Cloud/local parity: `parity_diff.assert_within(delta=0.1)` on `_cloud/` — amplifying variants only, ±0.3 non-amplifying
4. README.md tested-params table populated (at least Set A with real artifact)
5. Phase file header complete (all required sections)
6. Charter compliance verified (no count caps, no time exits, explicit exposure)
7. Validation gate results recorded (passing OR honestly marked pending)

---

## 8. Migration Sequence

| Step | Scope | Ticket | Gate |
|------|-------|--------|------|
| 0 | Phase-0 hygiene: oracle tag, .gitignore, archive dead dirs, prune worktrees | pre-ARCH | Falk auth ✅ |
| 1 | Scaffold `src/engine/` + `src/tests/harness/` + `build/cloud_package.py` (stub phases, FakeQCAlgorithm) | ARCH-A/D/G | fintrack reviews base.py + engine skeleton |
| 2 | Carve main.py → phase modules, ±0.01 Sharpe parity vs oracle | ARCH-C/E | parity gate |
| 3 | Per-phase folders/tests/headers, PR gate enforced | ARCH-F/H | 7-check merge gate live |
| 4 | CI: GitHub Actions running 7-check gate on every PR | ARCH-H | CI green |
| 5 | Retrofit Pe/Pe-rampup (after #182 unified loader lands) | ARCH-I | parity on amplifying variant |
| 6 | Retrofit X3a, E40c/d, ladder, rotation | ARCH-J | per-phase gate |
| 7 | Cutover: old main.py archived | ARCH-M | baseline-essentials-v1 live |

---

## 9. Structural Guardrails (the anti-artifact layer)

| Guardrail | Kills |
|-----------|-------|
| `validate_invariants()` at engine init | count caps, time exits, implicit exposure |
| `UniverseLoadError` on empty universe | silent bypass class (8b50c1a) |
| `marker-verify` on every deploy | wrong-code contamination |
| `auto-reject` if no artifact + no VERSION_MARKER | phantom Sharpes, fabricated results |
| `parity_diff` runs on `_cloud/` not `src/` | local-only false passes |
| `apply()` rejects double-write | chain-ordering bugs |
| `amplifying-variant parity test` mandatory | baseline-passes-pyramid-fails (Pe disaster) |

---

## 10. Baseline-Essentials-v1 STRATEGY_CONFIG (first on main, no pyramid)

```python
STRATEGY_CONFIG = {
    "name": "baseline-essentials-v1",
    "version": "1.0.0",
    "phases": {
        "universe":       {"module": "phases.universe.polygon_daily",       "enabled": True,  "params": {"min_price": 20.0, "min_dv": 500_000}},
        "signal":         {"module": "phases.signal.bct_score",             "enabled": True,  "params": {"min_score": 7}},
        "regime": [
            {"module": "phases.regime.vix_threshold",  "enabled": True, "params": {"max_vix": 25}},
            {"module": "phases.regime.spy_200ma",       "enabled": True, "params": {}},
        ],
        "ranking":        {"module": "phases.ranking.dollar_volume",        "enabled": True,  "params": {"direction": "desc"}},
        "entry_timing":   {"module": "phases.entry.buy_stop_kijun",         "enabled": True,  "params": {"offset_pct": 0.75}},
        "sizing":         {"module": "phases.sizing.risk_based_fixed",      "enabled": True,  "params": {"risk_dollars": 500}},
        "eligibility":    {"module": "phases.eligibility.already_held_check","enabled": True, "params": {}},
        "portfolio_risk": [{"module": "phases.portfolio_risk.gross_exposure_cap", "enabled": True, "params": {"max_pct": 100}}],
        "stops_initial":  {"module": "phases.stops.atr_initial",            "enabled": True,  "params": {"atr_mult": 2.5}},
        "trail":          {"module": "phases.trail.kijun_trail",            "enabled": True,  "params": {}},
        "exit_hard": [
            {"module": "phases.exit.cloud_breach",   "enabled": True, "params": {}},
            {"module": "phases.exit.weekly_kijun",   "enabled": True, "params": {}},
        ],
        "cash":           {"module": "phases.cash.no_margin",               "enabled": True,  "params": {}},
        "rebalance":      {"module": "phases.rebalance.daily_close",        "enabled": True,  "params": {"time": "16:05"}},
        "adds":           {"module": "phases.adds.pe_signal_renewed",       "enabled": False, "params": {}},  # retrofit after #182
        "diagnostics": [
            {"module": "phases.diagnostics.parity_logger",  "enabled": True, "params": {}},
            {"module": "phases.diagnostics.version_marker", "enabled": True, "params": {}},
        ],
    },
    "invariants": {"no_count_caps": True, "no_time_exits": True, "explicit_exposure_only": True},
}
```

Pyramid off. Retrofit only after #182 unified loader + full parity gate.

---

## 11. Open Items (pre-implementation)

- `#182` universe loader unification: ObjectStore timestamp verification → unified loader + fail-loud guard → fintrack diff review → Pe local re-run → Pe cloud re-run (blocks ARCH-I)
- `#183` local harness ObjectStore mock: design needed so `_cloud/` runs verbatim locally
- CI provider: GitHub Actions vs pre-commit (needs decision before ARCH-H)
- G5 (DSR/PBO) implementation: greenfield, gates Phase 5 live trading
