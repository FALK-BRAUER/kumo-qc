# kumo-qc Architecture — Phase-Based Strategy Engine

**Status:** Architectural charter (2026-05-30, Falk)
**Linked from:** [CLAUDE.md](../CLAUDE.md)
**Owner:** fintrack HQ + kumo-qc orchestrator

This document defines the canonical architecture for kumo-qc strategy code. All new strategy work follows this. Migration tickets in GH (ARCH-A through ARCH-M).

---

## 1. Core Principles

1. **Phase decomposition.** Every strategy is a composition of discrete phases (universe → signal → regime → ranking → entry → sizing → stops → trail → adds → exit → ...). 29 phase types catalogued; most strategies use a subset.

2. **Slot-based main.py.** `main.py` is a thin orchestrator. It contains a `STRATEGY_CONFIG` block and an engine bootstrap call. No business logic. The engine resolves phase modules dynamically from config.

3. **Single code path — local and cloud.** No `if cloud: X else: local: Y` branches in strategy code. Local is a HARNESS that emulates cloud. See [CLAUDE.md → Cloud/Local Parity](../CLAUDE.md).

4. **Folder per phase + per-phase tests.** Each phase implementation lives in its own folder with its own `tests/` subdirectory. Unit-tested in isolation. Engine integration-tested with the phase plugged in.

5. **Dist packaging for cloud.** QC cloud requires flat .py files in project root. Build step (`build/cloud_package.py`) flattens `src/` → `_cloud/`, rewrites imports (`phases.adds.pe_rampup` → `phase_adds_pe_rampup`), strips tests. `_cloud/` is git-tracked for diff visibility.

6. **Main branch carries only tested, graduated phase implementations.** Feature branches develop; PR gate enforces tests + parity + header completeness; merged code becomes the default library. `STRATEGY_CONFIG` on main = current best-known production strategy.

7. **Phase file header is mandatory.** Tested-params table, setup context, validation gate status, charter compliance, changelog. No phase merges to main without complete header.

8. **Logging everywhere.** Engine logs every tick + phase chain + decisions. Each phase logs every evaluation step (inputs, decision, reason, metrics). Pipe-delimited or structured JSON. Markers verified on every deploy.

9. **Charter invariants enforced by engine.** No count caps (`max_positions`, `max_lots` forbidden), no time-based exits (`max_hold_days` forbidden), explicit exposure control only (implicit caps prohibited).

10. **Validation gates run on PR.** G1 (6-window robustness), G2 (no period concentration), G3 (OOS year), G4 (uncapped doesn't collapse), G5 (methodology audit — DSR/PBO). Automated in CI.

---

## 2. Phase Taxonomy (29 phases)

| # | Phase Kind | Purpose | Examples |
|---|---|---|---|
| 1 | **universe.source** | Which tickers exist | polygon snapshot, S&P 500, ETF basket, scanner output |
| 2 | **universe.filter** | Hard constraints on universe | price≥$20, DV≥$500K, has_fundamental_data |
| 3 | **universe.rotation** | Refresh cadence | daily, weekly, static |
| 4 | **signal** | Quality scoring per ticker | BCT 8-condition, RSI, breakouts |
| 5 | **regime** | Macro on/off switches | VIX<25, SPY>200MA, breadth>50% |
| 6 | **ranking** | Order candidates | composite, dollar-vol, ADX-weighted |
| 7 | **entry_selection** | Pick top-N | score-threshold, slot allocation |
| 8 | **entry_timing** | When to fire entry | open, limit, buy-stop above kijun, day-type aware |
| 9 | **sizing** | Position size | $X risk, %equity, ATR-normalized, score-tiered |
| 10 | **eligibility** | Pre-fire checks | already-held, sector cap, correlation cap |
| 11 | **stops_initial** | Initial stop placement | ATR-mult, kijun, swing-low, % |
| 12 | **risk_per_trade** | Max loss per trade | $X fixed, %equity, vol-scaled |
| 13 | **portfolio_risk** | Aggregate exposure caps | gross-exposure %, sector, correlation, max-DD |
| 14 | **cash** | Cash policy | no-margin, cash-floor, idle-deployment |
| 15 | **trail** | Stop trailing | kijun-trail, ATR-trail, breakeven-move, chandelier |
| 16 | **adds** | Pyramid adds | signal-renewed, rampup anti-Kelly, conviction, momentum |
| 17 | **profit** | Partial profit-taking | ladder trims, ATR targets, R-multiple |
| 18 | **reentry** | After stop-out rules | cooldown + buy-stop only |
| 19 | **exit_hard** | Forced exits | cloud breach, weekly kijun, kumo flip, sector ETF break |
| 20 | ~~**exit_time**~~ | Time-based — **FORBIDDEN by charter** | — |
| 21 | **exit_target** | Profit targets | cup-rim, swing high, R-multiple |
| 22 | **exit_regime** | Regime-forced | VIX spike, breadth collapse, SPY break |
| 23 | **exit_rotation** | Sell worst, buy better | rotation engine |
| 24 | ~~**cash.duplicate**~~ | (merged into #14) | — |
| 25 | **rebalance** | Scheduler tick | daily 16:05, weekly Friday, signal-driven |
| 26 | **slot_allocation** | How capital splits | uncapped, %per-slot, count-cap **(forbidden)** |
| 27 | **logging** | Decision trail | per-phase structured logger |
| 28 | **diagnostics** | Parity + signal dump | cloud/local divergence, signal-stack |
| 29 | **circuit_breaker** | Halt-on-anomaly | DD-reset, error-rate (F3 dead-latch removed) |

---

## 3. Source Tree

```
algorithm/performance_bct/
  src/                                       # SOURCE TREE (dev + test)
    main.py                                  # STRATEGY_CONFIG only + engine bootstrap
    engine/
      engine.py
      base.py
      context.py
      logger.py
      README.md
      tests/
        test_engine.py
        test_phase_order.py
        test_invariants.py
        fixtures/

    phases/
      universe/
        polygon_daily/
          polygon_daily.py
          README.md
          tests/
            test_polygon_daily.py
            fixtures/
        scanner_dynamic/
          ...

      signal/
        bct_score/
          bct_score.py
          README.md
          tests/

      regime/
        vix_threshold/
        spy_200ma/
        market_breadth/

      adds/
        pe_signal_renewed/
        pe_rampup_antikelly/
        pe_conviction/

      [... all 29 phase kinds, folder-per-implementation ...]

    tests/                                   # TOP-LEVEL HARNESS
      integration/
        test_strategy_baseline.py
        test_cloud_local_parity.py
        test_strategy_pe_rampup.py
        fixtures/configs/
      harness/
        bt_runner.py
        parity_diff.py
        metric_extractor.py
        assertion_lib.py
      conftest.py

  build/
    cloud_package.py
    requirements.txt

  _cloud/                                    # GENERATED, GIT-TRACKED
    main.py
    engine.py
    phase_universe_polygon_daily.py
    phase_signal_bct_score.py
    [...]

  scripts/
    test-all.sh
    test-phase.sh <phase-path>
    build-cloud.sh
    deploy-cloud.sh
    verify-parity.sh <strategy-config>
```

---

## 4. Strategy Definition (top of main.py)

```python
STRATEGY_CONFIG = {
    "name": "Pe-rampup-v3",
    "version": "1.0.0",
    "description": "BCT + signal-renewed anti-Kelly pyramid + kijun trail + cap",
    "tags": ["pyramid", "anti-kelly", "ichimoku", "BCT"],

    "phases": {
        "universe":       {"module": "phases.universe.polygon_daily",
                           "enabled": True,
                           "params": {"min_price": 20.0, "min_dv": 500_000}},

        "signal":         {"module": "phases.signal.bct_score",
                           "enabled": True,
                           "params": {"min_score": 7}},

        "regime": [
            {"module": "phases.regime.vix_threshold",
             "enabled": True, "params": {"max_vix": 25}},
            {"module": "phases.regime.spy_200ma",
             "enabled": True, "params": {}},
        ],

        "ranking":        {"module": "phases.ranking.dollar_volume",
                           "enabled": True, "params": {"direction": "desc"}},

        "entry_timing":   {"module": "phases.entry.buy_stop_kijun",
                           "enabled": True, "params": {"offset_pct": 0.75}},

        "sizing":         {"module": "phases.sizing.risk_based_fixed",
                           "enabled": True, "params": {"risk_dollars": 200}},

        "eligibility":    {"module": "phases.eligibility.already_held_check",
                           "enabled": True, "params": {}},

        "portfolio_risk": [
            {"module": "phases.portfolio_risk.gross_exposure_cap",
             "enabled": True, "params": {"max_pct": 100}},
        ],

        "stops_initial":  {"module": "phases.stops.atr_initial",
                           "enabled": True, "params": {"atr_mult": 2.5}},

        "trail":          {"module": "phases.trail.kijun_trail",
                           "enabled": True, "params": {}},

        "adds":           {"module": "phases.adds.pe_rampup_antikelly",
                           "enabled": True, "params": {"lot_progression": [200, 400, 600]}},

        "exit_hard": [
            {"module": "phases.exit.cloud_breach",   "enabled": True, "params": {}},
            {"module": "phases.exit.weekly_kijun",   "enabled": True, "params": {}},
        ],

        "cash":           {"module": "phases.cash.no_margin",
                           "enabled": True, "params": {}},

        "rebalance":      {"module": "phases.rebalance.daily_close",
                           "enabled": True, "params": {"time": "16:05"}},

        "diagnostics": [
            {"module": "phases.diagnostics.parity_logger", "enabled": True, "params": {}},
            {"module": "phases.diagnostics.version_marker", "enabled": True, "params": {}},
        ],
    },

    "invariants": {
        "no_count_caps": True,
        "no_time_exits": True,
        "explicit_exposure_only": True,
    },
}
```

---

## 5. Phase Contract

```python
# src/engine/base.py
class PhaseInterface(ABC):
    @abstractmethod
    def __init__(self, params: dict, logger: ComponentLogger): ...

    @abstractmethod
    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...

    @property
    @abstractmethod
    def version_marker(self) -> str: ...

    @property
    def phase_kind(self) -> str: ...

class PhaseResult:
    decision: Any              # phase-specific
    blocked: bool              # if regime/cash/eligibility blocks downstream
    reason: str
    facts: dict                # structured log payload
    metrics: dict
```

---

## 6. Engine

```python
# src/engine/engine.py
class StrategyEngine:
    PHASE_ORDER = [
        "universe", "signal", "regime", "ranking",
        "entry_selection", "entry_timing", "eligibility", "sizing",
        "portfolio_risk", "cash",
        "stops_initial", "trail",
        "adds", "profit", "exit_rotation", "reentry",
        "exit_hard", "exit_target", "exit_regime",
        "rebalance", "diagnostics", "circuit_breaker"
    ]

    def __init__(self, config: dict, qc_algo):
        self.config = config
        self.qc = qc_algo
        self.logger = ComponentLogger(qc_algo)
        self.phases = self._load_phases()
        self._enforce_invariants()
        self._log_strategy_definition()

    def on_data(self, data):
        ctx = PhaseContext(data, self.qc)
        for kind in self.PHASE_ORDER:
            phase = self.phases.get(kind)
            if phase is None or not phase.enabled:
                continue
            for sub_phase in self._iter_phase(phase):
                result = sub_phase.evaluate(ctx)
                self.logger.log_phase(kind, sub_phase, result)
                ctx.apply(kind, result)
                if result.blocked and kind in {"regime", "cash", "eligibility", "portfolio_risk"}:
                    return
```

---

## 7. Phase File Header (mandatory)

Every phase `.py` MUST open with this docstring:

```python
"""
Phase: adds.pe_rampup_antikelly
Kind: adds
Version: 1.0.0
Marker: pe_rampup_antikelly_v1

DESCRIPTION
-----------
<one-paragraph plain-english summary>

TESTED PARAMETERS
-----------------
| Set | params                          | Sharpe | Ret%   | DD%   | Orders | Setup                                  | Validation                |
|-----|--------------------------------|--------|--------|-------|--------|----------------------------------------|---------------------------|
| A   | lot_progression=[200,400,600]   | 1.486  | +36.8% | 7.1%  | 201    | exits=cloud+weekly_kijun, regime=...   | G4 PASS, G1-G3/G5 pending |

DEFAULT
-------
lot_progression = [200, 400, 600]   # Set A — best known, PROVISIONAL pending #182

REQUIRED UPSTREAM PHASES
------------------------
- signal: any
- entry: any
- sizing: any (OVERRIDDEN for adds)

KNOWN INTERACTIONS
------------------
- Pairs well with: trail.kijun_trail
- Conflicts with: adds.pe_conviction (mutually exclusive)
- Sensitive to: cash.no_margin (cap=100 changes fill rate)

VALIDATION GATES
----------------
G1 (6 windows ≥4 positive):    NOT RUN
G2 (no window > 50% annual):    FAILS — W4 = 62%
G3 (OOS year survives):         NOT RUN
G4 (uncapped doesn't collapse): PASS
G5 (methodology audit):         NOT RUN

CHARTER COMPLIANCE
------------------
- no_count_caps:        ✅
- no_time_exits:        ✅
- explicit_exposure:    ⚠️ depends on portfolio_risk.gross_exposure_cap

CHANGELOG
---------
2026-05-30: Phase 3c discovery. Local 1.486, cloud -0.055 (selection divergence).
            PROVISIONAL pending #182.
"""
```

---

## 8. Test Harness (reusable, grows over time)

```python
# src/tests/harness/bt_runner.py
class BTRunner:
    def run_local(self, config, period) -> BTResult: ...
    def run_cloud(self, config, period) -> BTResult: ...
    def run_both(self, config, period) -> tuple[BTResult, BTResult]: ...

# src/tests/harness/parity_diff.py
class ParityDiff:
    def diff(self, local: BTResult, cloud: BTResult) -> ParityReport: ...
    def assert_within(self, delta_sharpe: float = 0.1): ...

# src/tests/harness/assertion_lib.py
def assert_g1_windows(results, min_positive=4): ...
def assert_g2_concentration(window_returns, max_pct=0.5): ...
def assert_g3_oos(in_sample, oos, delta=0.3): ...
def assert_g4_uncapped(capped, uncapped): ...
def assert_no_count_caps(config): ...
def assert_no_time_exits(config): ...
def assert_no_implicit_exposure(config): ...
```

**Harness grows with every failure mode.** Diff-protocol violations → new assertions. Failed gates → new fixtures. Cloud-only bugs → new parity tests.

---

## 9. Logging Contract

**Engine logs (every bar):**
```
STRATEGY_TICK|<ts>|chain=<csv>|entries=<n>|exits=<n>|adds=<n>
```

**Per-phase logs (every evaluation):**
```
PHASE|<kind>|<module>|<version_marker>|in=<facts>|out=<decision>|reason=<text>|metrics=<json>
```

**Block events:**
```
BLOCK|<kind>|<module>|reason=<text>|ctx=<snapshot>
```

**Trade events:**
```
ENTRY|<ticker>|qty=<n>|price=<x>|stop=<y>|sizing=<module>|risk=<$>
ADD|<ticker>|qty=<n>|price=<x>|lot=<#>|module=<adds.module>
TRIM|<ticker>|qty=<n>|price=<x>|rung=<%>
EXIT|<ticker>|qty=<n>|price=<x>|reason=<exit.module>|pnl=<$>
```

**Parity diagnostics (periodic):**
```
PARITY|gross_exposure=<x>|cash=<y>|positions=<n>|markers=<json>
```

---

## 10. Cloud Packaging

```python
# build/cloud_package.py
class CloudPackager:
    SRC = Path("src")
    DST = Path("_cloud")

    def build(self):
        self._clean_dst()
        for phase_file in self.SRC.rglob("*.py"):
            if "tests" in phase_file.parts:
                continue
            flat_name = self._flatten_name(phase_file)
            content = self._rewrite_imports(phase_file.read_text())
            (self.DST / flat_name).write_text(content)
        self._copy_main()
        self._verify_no_subdirs(self.DST)
```

**Naming convention:** `phases/adds/pe_rampup_antikelly/pe_rampup_antikelly.py` → `_cloud/phase_adds_pe_rampup_antikelly.py`

**Imports rewritten:**
```python
# src/
from phases.adds.pe_rampup_antikelly import PeRampupAntikelly

# _cloud/
from phase_adds_pe_rampup_antikelly import PeRampupAntikelly
```

**`_cloud/` git tracked.** Diff visibility on every deploy. Commit message references built SHA.

---

## 11. Main Branch Merge Gate (PR checks)

Phase merges to main only when all 7 pass (CI-enforced):

1. ✅ Phase unit tests pass
2. ✅ Engine integration test passes (phase plugged into baseline strategy)
3. ✅ Cloud/local parity test passes (±0.1 Sharpe amplifying, ±0.3 non-amplifying)
4. ✅ README.md tested-params table populated (at least Set A)
5. ✅ Phase file header complete (all required sections)
6. ✅ Charter compliance verified (no count caps, no time exits, explicit exposure)
7. ✅ Validation gate results recorded (passing OR honestly marked pending)

**Main always has a working `STRATEGY_CONFIG`** = current best-known production strategy.

---

## 12. Migration Plan

| Step | Scope | Risk | Tickets |
|---|---|---|---|
| 1 | Scaffold `src/engine/` + `src/tests/harness/` + cloud packager. Empty phases. | Low | ARCH-A, D, G |
| 2 | Carve existing main.py logic into phase modules: universe + signal + regime + ranking + entry + sizing + stops + trail + exit. Baseline parity gate ±0.01 Sharpe. | High (forces correctness) | ARCH-C, E |
| 3 | Each phase: own folder, own tests, full header, README. PR-gate enforced. | Medium | ARCH-F, H |
| 4 | Migrate Pe variants → `phases/adds/` with full header + tests. Includes Pe-rampup once #182 parity fix lands. | Low | ARCH-I |
| 5 | Migrate X3a, E40c/d, E157 → `phases/regime/` + `phases/exit/`. | Low | ARCH-J |
| 6 | Add new phases: `gross_exposure_cap` (#181), `ladder_trim` (#179), `cooldown_buy_stop`, `rotation`. | Medium | new tickets |
| 7 | Cutover: main.py → STRATEGY_CONFIG only + engine call. Old code archived. | Cleanup | ARCH-M |
| 8 | Retrofit other good candidates from feat branches. | Per-candidate | per-candidate |

---

## 13. Decisions (locked, 2026-05-30)

1. **QC cloud has NO subdir support** → dist packaging mandatory (build/cloud_package.py flattens)
2. **`_cloud/` is git-tracked** → diff visibility per deploy
3. **pytest** = test framework
4. **Unit tests with mock LEAN** for phase isolation; real LEAN for parity
5. **Validation gates run on PR** = CI-enforced merge gate
6. **Semver per phase** for human readability
7. **STRATEGY_CONFIG hash** logged + verified on deploy

---

## 14. Open Items

- Mock LEAN scaffolding (Portfolio, Securities, Indicators) — needs design
- CI config for PR gates — GitHub Actions or pre-commit
- bt-results.csv reconciliation post-cutover — re-baseline or accept break

---

## 15. References

- [CLAUDE.md → Cloud/Local Parity Rule](../CLAUDE.md)
- [CLAUDE.md → Git as Source of Truth](../CLAUDE.md)
- GH #173 — Local vs Cloud Divergence Diagnosis Protocol
- GH #181 — Gross-exposure control
- GH #182 — Unify cloud/local universe code path
- GH #183 — Local harness emulates cloud
- GH #184 — Amplifying-mechanic parity test mandate
- GH #185 — 8b50c1a postmortem
- GH ARCH-A through ARCH-M — migration tickets
