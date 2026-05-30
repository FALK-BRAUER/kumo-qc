# ARCH-A: Phase Engine Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold `src/engine/` with `base.py`, `context.py`, `engine.py`, `logger.py`, stub phases, and full test suite — ready for fintrack review before any main.py carve begins.

**Architecture:** PhaseContext = LEAN read-only refs + fresh BarState per bar. Engine iterates PHASE_ORDER (canonical list with FIRE_* sentinel tokens), sets `bar_blocked` on regime/cash block (does NOT hard-return), always runs diagnostics + circuit_breaker tail. PhaseInterface = class attrs (PHASE_KIND/REQUIRES_UPSTREAM/PROVIDES_DOWNSTREAM) + abstract evaluate()/version_marker + concrete enabled/validate_config(). All tests use FakeQCAlgorithm and stub phases — zero real LEAN dependency.

**Tech Stack:** Python 3.11+, pytest, dataclasses, abc, hashlib, json. No LEAN import in engine or tests.

**Spec:** `docs/superpowers/specs/2026-05-30-phase-engine-design.md` (d09f8ad)  
**Ticket:** ARCH-A #187  
**Gate:** fintrack reviews base.py interface + engine loop skeleton before ARCH-C carve begins. DO NOT start ARCH-C until fintrack approval.

---

## File Map

| File | Responsibility |
|------|---------------|
| `algorithm/performance_bct/src/engine/__init__.py` | package marker, exports |
| `algorithm/performance_bct/src/engine/context.py` | `OrderIntent`, `BlockEvent`, `BarState`, `PhaseContext` |
| `algorithm/performance_bct/src/engine/base.py` | `PhaseResult`, `PhaseInterface` ABC, `CharterViolation`, `UniverseLoadError` |
| `algorithm/performance_bct/src/engine/engine.py` | `FIRE_*` sentinels, `PHASE_ORDER`, `StrategyEngine` |
| `algorithm/performance_bct/src/engine/logger.py` | `ComponentLogger` |
| `algorithm/performance_bct/src/engine/tests/__init__.py` | package marker |
| `algorithm/performance_bct/src/engine/tests/fixtures/__init__.py` | package marker |
| `algorithm/performance_bct/src/engine/tests/fixtures/fake_qc.py` | `FakeQCAlgorithm`, `FakePortfolio`, `FakeSecurities` |
| `algorithm/performance_bct/src/engine/tests/fixtures/stub_phases.py` | `StubRegime`, `StubCash`, `StubSignal`, `StubAdds`, `StubDiagnostics`, `StubCircuitBreaker` |
| `algorithm/performance_bct/src/engine/tests/test_context.py` | BarState apply(), double-write guard, PhaseContext construction |
| `algorithm/performance_bct/src/engine/tests/test_engine.py` | Engine loop, PHASE_ORDER, fire sentinels, blocked-bar tail semantics |
| `algorithm/performance_bct/src/engine/tests/test_invariants.py` | Charter violation detection, validate_invariants() |
| `algorithm/performance_bct/src/pytest.ini` | pytest config, testpaths |

---

## Task 0: Phase-0a — Oracle Tag + Gitignore

**Files:**
- Modify: `.gitignore`
- No new files

- [ ] **Step 1: Tag the parity oracle**

```bash
git tag baseline-oracle-v0
git push origin baseline-oracle-v0
```

Expected: tag created. Verify: `git tag | grep baseline-oracle`

- [ ] **Step 2: Fix .gitignore**

Read current `.gitignore` first, then add these lines if not already present:

```
# backtests in all algorithm dirs
*/backtests/

# root log files
*.log

# pycache everywhere
**/__pycache__/
**/*.pyc
```

- [ ] **Step 3: Untrack any currently-tracked files now covered by .gitignore**

```bash
git ls-files --cached | grep -E '\.(log)$|/__pycache__/'
git rm --cached fy2025.log w4_local.log w4_parity.log 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: tag baseline-oracle-v0 + fix gitignore (backtests, logs, pycache)"
```

---

## Task 1: Directory Scaffold + Pytest Config

**Files:**
- Create: `algorithm/performance_bct/src/engine/__init__.py`
- Create: `algorithm/performance_bct/src/engine/tests/__init__.py`
- Create: `algorithm/performance_bct/src/engine/tests/fixtures/__init__.py`
- Create: `algorithm/performance_bct/src/pytest.ini`

- [ ] **Step 1: Create directories and empty package markers**

```bash
mkdir -p algorithm/performance_bct/src/engine/tests/fixtures
touch algorithm/performance_bct/src/engine/__init__.py
touch algorithm/performance_bct/src/engine/tests/__init__.py
touch algorithm/performance_bct/src/engine/tests/fixtures/__init__.py
```

- [ ] **Step 2: Write pytest.ini**

Create `algorithm/performance_bct/src/pytest.ini`:

```ini
[pytest]
testpaths = engine/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 3: Verify pytest discovers (no tests yet = 0 collected, no error)**

```bash
cd algorithm/performance_bct/src && python -m pytest --collect-only 2>&1 | head -10
```

Expected: `no tests ran` or `0 items` — no import errors.

- [ ] **Step 4: Commit**

```bash
git add algorithm/performance_bct/src/
git commit -m "feat(arch-a): scaffold src/engine/ directory + pytest config"
```

---

## Task 2: context.py — BarState and PhaseContext

**Files:**
- Create: `algorithm/performance_bct/src/engine/context.py`
- Create: `algorithm/performance_bct/src/engine/tests/test_context.py`

- [ ] **Step 1: Write the failing tests**

Create `algorithm/performance_bct/src/engine/tests/test_context.py`:

```python
import pytest
from engine.context import BarState, PhaseContext, OrderIntent, BlockEvent


def test_bar_state_starts_empty():
    bs = BarState()
    assert bs.ranked_candidates == []
    assert bs.sized_orders == []
    assert bs.add_intents == []
    assert bs.exit_intents == []
    assert bs.trim_intents == []
    assert bs.blocks == []
    assert bs.phase_outputs == {}


def test_bar_state_apply_stores_output():
    bs = BarState()
    result = object()
    bs.apply("signal", result)
    assert bs.phase_outputs["signal"] is result


def test_bar_state_apply_rejects_double_write():
    bs = BarState()
    bs.apply("signal", object())
    with pytest.raises(ValueError, match="double-write"):
        bs.apply("signal", object())


def test_order_intent_fields():
    oi = OrderIntent(ticker="AAPL", qty=10, price=150.0, stop=145.0, module="sizing.risk_based_fixed", risk_dollars=500.0)
    assert oi.ticker == "AAPL"
    assert oi.qty == 10


def test_block_event_fields():
    be = BlockEvent(ticker="AAPL", kind="eligibility", reason="already held", module="eligibility.already_held_check")
    assert be.kind == "eligibility"


def test_phase_context_holds_lean_refs_and_bar_state():
    class FakeQC:
        pass
    qc = FakeQC()
    from datetime import datetime
    t = datetime(2025, 1, 2)
    ctx = PhaseContext(qc=qc, time=t, data=None)
    assert ctx.qc is qc
    assert ctx.time == t
    assert isinstance(ctx.bar_state, BarState)


def test_phase_context_bar_state_fresh_each_construction():
    class FakeQC:
        pass
    qc = FakeQC()
    from datetime import datetime
    t = datetime(2025, 1, 2)
    ctx1 = PhaseContext(qc=qc, time=t, data=None)
    ctx2 = PhaseContext(qc=qc, time=t, data=None)
    assert ctx1.bar_state is not ctx2.bar_state
```

- [ ] **Step 2: Run tests — expect FAIL (ImportError)**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_context.py -v 2>&1 | head -20
```

Expected: `ImportError: No module named 'engine.context'`

- [ ] **Step 3: Write context.py**

Create `algorithm/performance_bct/src/engine/context.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class OrderIntent:
    ticker: str
    qty: int
    price: float
    stop: float
    module: str
    risk_dollars: float


@dataclass
class BlockEvent:
    ticker: str
    kind: str
    reason: str
    module: str


@dataclass
class BarState:
    ranked_candidates: list[str] = field(default_factory=list)
    sized_orders: list[OrderIntent] = field(default_factory=list)
    add_intents: list[OrderIntent] = field(default_factory=list)
    exit_intents: list[OrderIntent] = field(default_factory=list)
    trim_intents: list[OrderIntent] = field(default_factory=list)
    blocks: list[BlockEvent] = field(default_factory=list)
    phase_outputs: dict[str, Any] = field(default_factory=dict)

    def apply(self, kind: str, result: Any) -> None:
        if kind in self.phase_outputs:
            raise ValueError(f"double-write detected for phase kind '{kind}'")
        self.phase_outputs[kind] = result


@dataclass
class PhaseContext:
    qc: Any          # QCAlgorithm (read-only refs — Portfolio, Securities, Time, Log)
    time: datetime
    data: Any        # LEAN Slice
    bar_state: BarState = field(default_factory=BarState)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_context.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add algorithm/performance_bct/src/engine/context.py algorithm/performance_bct/src/engine/tests/test_context.py
git commit -m "feat(arch-a): PhaseContext + BarState with double-write guard (TDD)"
```

---

## Task 3: base.py — PhaseInterface and PhaseResult

**Files:**
- Create: `algorithm/performance_bct/src/engine/base.py`
- Create: `algorithm/performance_bct/src/engine/tests/fixtures/stub_phases.py`
- Modify: `algorithm/performance_bct/src/engine/tests/test_context.py` (add base import verification test)

- [ ] **Step 1: Write the failing tests**

Create `algorithm/performance_bct/src/engine/tests/test_base.py`:

```python
import pytest
from engine.base import PhaseInterface, PhaseResult, CharterViolation, UniverseLoadError
from engine.context import PhaseContext, BarState
from datetime import datetime


class ConcretePhase(PhaseInterface):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = ["ranked_candidates"]

    def __init__(self, params: dict, logger):
        self._params = params
        self._logger = logger

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(decision=[], blocked=False, reason="ok", facts={}, metrics={})

    @property
    def version_marker(self) -> str:
        return "stub_signal_v1"


class MissingEvaluatePhase(PhaseInterface):
    PHASE_KIND = "signal"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = []

    def __init__(self, params, logger):
        self._params = params
        self._logger = logger

    @property
    def version_marker(self):
        return "v1"


def make_ctx():
    class FakeQC:
        pass
    return PhaseContext(qc=FakeQC(), time=datetime(2025, 1, 2), data=None)


def test_phase_result_fields():
    r = PhaseResult(decision="buy", blocked=False, reason="signal ok", facts={"score": 8}, metrics={"count": 1})
    assert r.decision == "buy"
    assert not r.blocked
    assert r.facts["score"] == 8


def test_concrete_phase_implements_interface():
    phase = ConcretePhase(params={"min_score": 7}, logger=None)
    assert phase.PHASE_KIND == "signal"
    assert phase.version_marker == "stub_signal_v1"


def test_enabled_defaults_true():
    phase = ConcretePhase(params={}, logger=None)
    assert phase.enabled is True


def test_enabled_false_when_param_set():
    phase = ConcretePhase(params={"enabled": False}, logger=None)
    assert phase.enabled is False


def test_evaluate_returns_phase_result():
    phase = ConcretePhase(params={}, logger=None)
    result = phase.evaluate(make_ctx())
    assert isinstance(result, PhaseResult)
    assert result.blocked is False


def test_missing_evaluate_raises_on_instantiation():
    with pytest.raises(TypeError):
        MissingEvaluatePhase(params={}, logger=None)


def test_charter_violation_is_exception():
    with pytest.raises(CharterViolation):
        raise CharterViolation("max_positions is a count cap")


def test_universe_load_error_is_exception():
    with pytest.raises(UniverseLoadError):
        raise UniverseLoadError("universe empty — engine refuses to start")


def test_validate_config_default_passes():
    phase = ConcretePhase(params={"min_score": 7}, logger=None)
    phase.validate_config({"min_score": 7})  # should not raise
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_base.py -v 2>&1 | head -20
```

Expected: `ImportError: No module named 'engine.base'`

- [ ] **Step 3: Write base.py**

Create `algorithm/performance_bct/src/engine/base.py`:

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from engine.context import PhaseContext


class CharterViolation(Exception):
    pass


class UniverseLoadError(Exception):
    pass


@dataclass
class PhaseResult:
    decision: Any
    blocked: bool
    reason: str
    facts: dict
    metrics: dict


class PhaseInterface(ABC):
    # Subclasses MUST declare these as class attributes
    PHASE_KIND: str
    REQUIRES_UPSTREAM: list[str]
    PROVIDES_DOWNSTREAM: list[str]

    @abstractmethod
    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...

    @property
    @abstractmethod
    def version_marker(self) -> str: ...

    @property
    def enabled(self) -> bool:
        return self._params.get("enabled", True)

    def validate_config(self, params: dict) -> None:
        pass  # subclasses override to add param validation
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_base.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Write stub phases (needed by engine tests)**

Create `algorithm/performance_bct/src/engine/tests/fixtures/stub_phases.py`:

```python
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class StubPhase(PhaseInterface):
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = []

    def __init__(self, kind: str, blocked: bool = False, params: dict = None, logger=None):
        self.PHASE_KIND = kind
        self._blocked = blocked
        self._params = params or {}
        self._logger = logger
        self.called = False

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        self.called = True
        return PhaseResult(decision=None, blocked=self._blocked, reason="stub", facts={}, metrics={})

    @property
    def version_marker(self) -> str:
        return f"stub_{self.PHASE_KIND}_v1"


def make_stub(kind: str, blocked: bool = False) -> StubPhase:
    return StubPhase(kind=kind, blocked=blocked)
```

- [ ] **Step 6: Commit**

```bash
git add algorithm/performance_bct/src/engine/base.py algorithm/performance_bct/src/engine/tests/test_base.py algorithm/performance_bct/src/engine/tests/fixtures/stub_phases.py
git commit -m "feat(arch-a): PhaseInterface + PhaseResult + stub phases (TDD)"
```

---

## Task 4: logger.py — ComponentLogger

**Files:**
- Create: `algorithm/performance_bct/src/engine/logger.py`
- Create: `algorithm/performance_bct/src/engine/tests/test_logger.py`

- [ ] **Step 1: Write the failing tests**

Create `algorithm/performance_bct/src/engine/tests/test_logger.py`:

```python
from engine.logger import ComponentLogger
from engine.base import PhaseResult


class FakeQC:
    def __init__(self):
        self.logged = []

    def Log(self, msg: str):
        self.logged.append(msg)


def make_result(decision=None, blocked=False, reason="ok", facts=None, metrics=None):
    return PhaseResult(decision=decision, blocked=blocked, reason=reason, facts=facts or {}, metrics=metrics or {})


def test_logger_emits_phase_line():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(facts={"score": 8})

    class FakePhase:
        version_marker = "bct_score_v1"

    logger.log_phase("signal", FakePhase(), result)
    assert len(qc.logged) == 1
    line = qc.logged[0]
    assert line.startswith("PHASE|signal|")
    assert "bct_score_v1" in line
    assert "score" in line


def test_logger_emits_block_line_when_blocked():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    result = make_result(blocked=True, reason="VIX above threshold")

    class FakePhase:
        version_marker = "vix_threshold_v1"

    logger.log_phase("regime", FakePhase(), result)
    assert any("BLOCK" in line for line in qc.logged)
    assert any("VIX above threshold" in line for line in qc.logged)


def test_logger_emits_tick_summary():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_tick(chain=["regime", "signal"], entries=2, exits=1, adds=0)
    assert len(qc.logged) == 1
    line = qc.logged[0]
    assert line.startswith("STRATEGY_TICK|")
    assert "entries=2" in line
    assert "exits=1" in line


def test_logger_emits_strategy_init():
    qc = FakeQC()
    logger = ComponentLogger(qc)
    logger.log_strategy_init(config_hash="abc123", name="baseline-v1", version="1.0.0")
    assert len(qc.logged) == 1
    assert "STRATEGY_INIT" in qc.logged[0]
    assert "abc123" in qc.logged[0]
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_logger.py -v 2>&1 | head -20
```

Expected: `ImportError: No module named 'engine.logger'`

- [ ] **Step 3: Write logger.py**

Create `algorithm/performance_bct/src/engine/logger.py`:

```python
from __future__ import annotations
import json
from typing import Any
from engine.base import PhaseResult


class ComponentLogger:
    def __init__(self, qc: Any):
        self._qc = qc

    def log_phase(self, kind: str, phase: Any, result: PhaseResult) -> None:
        facts_str = json.dumps(result.facts, separators=(",", ":"))
        metrics_str = json.dumps(result.metrics, separators=(",", ":"))
        line = (
            f"PHASE|{kind}|{phase.version_marker}|"
            f"blocked={result.blocked}|reason={result.reason}|"
            f"facts={facts_str}|metrics={metrics_str}"
        )
        self._qc.Log(line)
        if result.blocked:
            self._qc.Log(
                f"BLOCK|{kind}|{phase.version_marker}|reason={result.reason}"
            )

    def log_tick(self, chain: list[str], entries: int, exits: int, adds: int) -> None:
        chain_str = ",".join(chain)
        self._qc.Log(
            f"STRATEGY_TICK|chain={chain_str}|entries={entries}|exits={exits}|adds={adds}"
        )

    def log_strategy_init(self, config_hash: str, name: str, version: str) -> None:
        self._qc.Log(
            f"STRATEGY_INIT|hash={config_hash}|name={name}|version={version}"
        )
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_logger.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add algorithm/performance_bct/src/engine/logger.py algorithm/performance_bct/src/engine/tests/test_logger.py
git commit -m "feat(arch-a): ComponentLogger with PHASE/BLOCK/TICK/INIT log lines (TDD)"
```

---

## Task 5: engine.py — PHASE_ORDER, Sentinels, StrategyEngine

**Files:**
- Create: `algorithm/performance_bct/src/engine/engine.py`
- Create: `algorithm/performance_bct/src/engine/tests/test_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `algorithm/performance_bct/src/engine/tests/test_engine.py`:

```python
import pytest
from datetime import datetime
from engine.engine import StrategyEngine, PHASE_ORDER, FireSentinel, FIRE_ENTRIES, FIRE_EXITS, FIRE_ADDS, FIRE_TRIMS
from engine.base import CharterViolation
from engine.context import PhaseContext
from engine.tests.fixtures.stub_phases import make_stub


class FakeQC:
    def __init__(self):
        self.logged = []
        self.orders = []

    def Log(self, msg):
        self.logged.append(msg)

    def MarketOrder(self, ticker, qty):
        self.orders.append((ticker, qty))


def make_ctx(qc):
    return PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)


def minimal_config(phases_override=None):
    phases = {
        "signal": {"module": "stub", "enabled": True, "params": {}},
        "portfolio_risk": {"module": "stub", "enabled": True, "params": {"max_pct": 100}},
    }
    if phases_override:
        phases.update(phases_override)
    return {
        "name": "test-strategy",
        "version": "1.0.0",
        "phases": phases,
        "invariants": {"no_count_caps": True, "no_time_exits": True, "explicit_exposure_only": True},
    }


def test_phase_order_contains_sentinels():
    assert FIRE_ENTRIES in PHASE_ORDER
    assert FIRE_EXITS in PHASE_ORDER
    assert FIRE_ADDS in PHASE_ORDER
    assert FIRE_TRIMS in PHASE_ORDER


def test_phase_order_sentinels_are_fire_sentinel_instances():
    for item in PHASE_ORDER:
        if not isinstance(item, str):
            assert isinstance(item, FireSentinel)


def test_phase_order_fire_entries_after_cash():
    order = [str(p) if isinstance(p, FireSentinel) else p for p in PHASE_ORDER]
    cash_idx = order.index("cash")
    entries_idx = order.index(str(FIRE_ENTRIES))
    assert entries_idx > cash_idx


def test_phase_order_fire_exits_after_exit_hard():
    order = [str(p) if isinstance(p, FireSentinel) else p for p in PHASE_ORDER]
    exit_idx = order.index("exit_hard")
    exits_fire_idx = order.index(str(FIRE_EXITS))
    assert exits_fire_idx > exit_idx


def test_phase_order_diagnostics_last_before_circuit_breaker():
    str_phases = [p for p in PHASE_ORDER if isinstance(p, str)]
    assert str_phases[-2] == "diagnostics"
    assert str_phases[-1] == "circuit_breaker"


def test_engine_charter_violation_on_count_cap():
    config = minimal_config({"sizing": {"module": "stub", "enabled": True, "params": {"max_positions": 10}}})
    with pytest.raises(CharterViolation, match="max_positions"):
        StrategyEngine(config=config, qc=FakeQC(), phase_instances={})


def test_engine_charter_violation_on_max_adds():
    config = minimal_config({"adds": {"module": "stub", "enabled": True, "params": {"max_adds": 3}}})
    with pytest.raises(CharterViolation, match="max_adds"):
        StrategyEngine(config=config, qc=FakeQC(), phase_instances={})


def test_engine_runs_enabled_phases():
    qc = FakeQC()
    signal_stub = make_stub("signal")
    config = minimal_config()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={"signal": [signal_stub]})
    ctx = make_ctx(qc)
    engine.on_data_with_ctx(ctx)
    assert signal_stub.called


def test_engine_skips_disabled_phases():
    qc = FakeQC()
    signal_stub = make_stub("signal")
    signal_stub._params = {"enabled": False}
    config = minimal_config()
    engine = StrategyEngine(config=config, qc=qc, phase_instances={"signal": [signal_stub]})
    ctx = make_ctx(qc)
    engine.on_data_with_ctx(ctx)
    assert not signal_stub.called


def test_blocked_bar_still_runs_diagnostics_and_circuit_breaker():
    qc = FakeQC()
    regime_stub = make_stub("regime", blocked=True)
    diag_stub = make_stub("diagnostics")
    cb_stub = make_stub("circuit_breaker")
    config = minimal_config()
    engine = StrategyEngine(
        config=config,
        qc=qc,
        phase_instances={
            "regime": [regime_stub],
            "diagnostics": [diag_stub],
            "circuit_breaker": [cb_stub],
        }
    )
    ctx = make_ctx(qc)
    engine.on_data_with_ctx(ctx)
    assert regime_stub.called
    assert diag_stub.called    # MUST run even on blocked bar
    assert cb_stub.called      # MUST run even on blocked bar


def test_blocked_bar_skips_trading_phases():
    qc = FakeQC()
    regime_stub = make_stub("regime", blocked=True)
    signal_stub = make_stub("signal")  # comes BEFORE regime in PHASE_ORDER
    sizing_stub = make_stub("sizing")  # comes AFTER regime — should be skipped
    config = minimal_config()
    engine = StrategyEngine(
        config=config,
        qc=qc,
        phase_instances={
            "regime": [regime_stub],
            "signal": [signal_stub],
            "sizing": [sizing_stub],
        }
    )
    ctx = make_ctx(qc)
    engine.on_data_with_ctx(ctx)
    assert sizing_stub.called is False


def test_engine_logs_strategy_init():
    qc = FakeQC()
    config = minimal_config()
    StrategyEngine(config=config, qc=qc, phase_instances={})
    assert any("STRATEGY_INIT" in line for line in qc.logged)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_engine.py -v 2>&1 | head -30
```

Expected: `ImportError: No module named 'engine.engine'`

- [ ] **Step 3: Write engine.py**

Create `algorithm/performance_bct/src/engine/engine.py`:

```python
from __future__ import annotations
import hashlib
import json
from typing import Any
from engine.base import PhaseInterface, PhaseResult, CharterViolation
from engine.context import PhaseContext, BarState
from engine.logger import ComponentLogger


class FireSentinel:
    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"FireSentinel({self.name!r})"


FIRE_ENTRIES = FireSentinel("FIRE_ENTRIES")
FIRE_EXITS   = FireSentinel("FIRE_EXITS")
FIRE_ADDS    = FireSentinel("FIRE_ADDS")
FIRE_TRIMS   = FireSentinel("FIRE_TRIMS")

PHASE_ORDER: list = [
    "rebalance", "universe", "signal", "regime", "ranking",
    "entry_selection", "entry_timing", "sizing",
    "reentry", "eligibility", "portfolio_risk", "cash",
    FIRE_ENTRIES,
    "stops_initial", "trail",
    "exit_hard", "exit_target", "exit_regime", "exit_rotation",
    FIRE_EXITS,
    "adds",
    FIRE_ADDS,
    "profit",
    FIRE_TRIMS,
    "diagnostics", "circuit_breaker",
]

ALWAYS_RUN = {"diagnostics", "circuit_breaker"}

FORBIDDEN_PARAMS = {
    "max_positions", "max_lots", "max_entries_per_day",
    "max_hold_days", "exit_if_flat_after_days",
    "max_adds", "max_pyramid_lots", "max_position_adds",
}


def validate_invariants(config: dict) -> None:
    for kind, phase_cfg in config.get("phases", {}).items():
        cfgs = phase_cfg if isinstance(phase_cfg, list) else [phase_cfg]
        for cfg in cfgs:
            for param_key in cfg.get("params", {}):
                if param_key in FORBIDDEN_PARAMS:
                    raise CharterViolation(
                        f"'{param_key}' is a forbidden count cap or time exit in phase '{kind}'"
                    )


def _config_hash(config: dict) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


class StrategyEngine:
    def __init__(self, config: dict, qc: Any, phase_instances: dict[str, list[PhaseInterface]]):
        self.config = config
        self.qc = qc
        self.phases = phase_instances
        self.logger = ComponentLogger(qc)
        validate_invariants(config)
        self.logger.log_strategy_init(
            config_hash=_config_hash(config),
            name=config.get("name", "unknown"),
            version=config.get("version", "0.0.0"),
        )

    def on_data_with_ctx(self, ctx: PhaseContext) -> None:
        bar_blocked = False
        phases_run = []

        for item in PHASE_ORDER:
            if isinstance(item, FireSentinel):
                if not bar_blocked:
                    self._fire(item, ctx)
                continue

            kind = item
            phase_list = self.phases.get(kind, [])

            for phase in phase_list:
                if not phase.enabled:
                    continue
                if bar_blocked and kind not in ALWAYS_RUN:
                    continue

                result = phase.evaluate(ctx)
                self.logger.log_phase(kind, phase, result)
                ctx.bar_state.apply(kind, result)
                phases_run.append(kind)

                if result.blocked and kind in {"regime", "cash"}:
                    bar_blocked = True

        self.logger.log_tick(
            chain=phases_run,
            entries=len(ctx.bar_state.sized_orders),
            exits=len(ctx.bar_state.exit_intents),
            adds=len(ctx.bar_state.add_intents),
        )

    def _fire(self, sentinel: FireSentinel, ctx: PhaseContext) -> None:
        # Stub: actual order submission wired in ARCH-C when LEAN integration lands
        pass
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_engine.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add algorithm/performance_bct/src/engine/engine.py algorithm/performance_bct/src/engine/tests/test_engine.py
git commit -m "feat(arch-a): StrategyEngine + PHASE_ORDER + FireSentinel + blocked-bar tail semantics (TDD)"
```

---

## Task 6: test_invariants.py — Charter Enforcement

**Files:**
- Create: `algorithm/performance_bct/src/engine/tests/test_invariants.py`

- [ ] **Step 1: Write the failing tests**

Create `algorithm/performance_bct/src/engine/tests/test_invariants.py`:

```python
import pytest
from engine.engine import validate_invariants, StrategyEngine
from engine.base import CharterViolation


def cfg_with_param(kind: str, param: str, value):
    return {
        "name": "t", "version": "1.0.0",
        "phases": {kind: {"module": "stub", "enabled": True, "params": {param: value}}},
        "invariants": {},
    }


@pytest.mark.parametrize("param", [
    "max_positions",
    "max_lots",
    "max_entries_per_day",
    "max_hold_days",
    "exit_if_flat_after_days",
    "max_adds",
    "max_pyramid_lots",
    "max_position_adds",
])
def test_forbidden_param_raises_charter_violation(param):
    config = cfg_with_param("sizing", param, 5)
    with pytest.raises(CharterViolation, match=param):
        validate_invariants(config)


def test_allowed_params_pass():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "sizing": {"module": "stub", "enabled": True, "params": {"risk_dollars": 500}},
            "adds": {"module": "stub", "enabled": True, "params": {"lot_size_dollars": 200}},
        },
        "invariants": {},
    }
    validate_invariants(config)  # should not raise


def test_forbidden_param_in_list_phase_raises():
    config = {
        "name": "t", "version": "1.0.0",
        "phases": {
            "regime": [
                {"module": "stub", "enabled": True, "params": {"max_positions": 5}},
            ],
        },
        "invariants": {},
    }
    with pytest.raises(CharterViolation, match="max_positions"):
        validate_invariants(config)
```

- [ ] **Step 2: Run tests — expect PASS (validate_invariants already implemented)**

```bash
cd algorithm/performance_bct/src && python -m pytest engine/tests/test_invariants.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 3: Run full suite — all green**

```bash
cd algorithm/performance_bct/src && python -m pytest -v
```

Expected: all tests PASS, no failures.

- [ ] **Step 4: Commit**

```bash
git add algorithm/performance_bct/src/engine/tests/test_invariants.py
git commit -m "test(arch-a): charter invariant enforcement — all FORBIDDEN params parametrized"
```

---

## Task 7: engine/__init__.py + README + Fintrack Review Gate

**Files:**
- Modify: `algorithm/performance_bct/src/engine/__init__.py`
- Create: `algorithm/performance_bct/src/engine/README.md`

- [ ] **Step 1: Write __init__.py exports**

Write `algorithm/performance_bct/src/engine/__init__.py`:

```python
from engine.base import PhaseInterface, PhaseResult, CharterViolation, UniverseLoadError
from engine.context import PhaseContext, BarState, OrderIntent, BlockEvent
from engine.engine import StrategyEngine, PHASE_ORDER, FIRE_ENTRIES, FIRE_EXITS, FIRE_ADDS, FIRE_TRIMS, FireSentinel
from engine.logger import ComponentLogger

__all__ = [
    "PhaseInterface", "PhaseResult", "CharterViolation", "UniverseLoadError",
    "PhaseContext", "BarState", "OrderIntent", "BlockEvent",
    "StrategyEngine", "PHASE_ORDER", "FIRE_ENTRIES", "FIRE_EXITS", "FIRE_ADDS", "FIRE_TRIMS", "FireSentinel",
    "ComponentLogger",
]
```

- [ ] **Step 2: Write README.md**

Create `algorithm/performance_bct/src/engine/README.md`:

```markdown
# engine/

Phase-based strategy engine for kumo-qc.

## What this is
The engine runs a `STRATEGY_CONFIG` dict through a canonical `PHASE_ORDER` each bar. Phases emit intents into `BarState`; the engine fires orders at `FIRE_*` sentinel boundaries.

## Key files
- `base.py` — `PhaseInterface` ABC, `PhaseResult`, `CharterViolation`, `UniverseLoadError`
- `context.py` — `PhaseContext` (LEAN refs + fresh `BarState` per bar), `OrderIntent`, `BlockEvent`
- `engine.py` — `StrategyEngine`, `PHASE_ORDER`, `FIRE_*` sentinels, `validate_invariants()`
- `logger.py` — `ComponentLogger` (PHASE/BLOCK/TICK/INIT log lines)

## What goes here
Engine core only. No phase implementations. No LEAN-specific logic beyond the `qc` ref on `PhaseContext`.

## What doesn't go here
Phase implementations (→ `phases/<kind>/<impl>/`). Test harness (→ `tests/harness/`). Cloud packaging (→ `build/`).

## Tests
```bash
cd algorithm/performance_bct/src
python -m pytest engine/tests/ -v
```
```

- [ ] **Step 3: Run full suite one final time**

```bash
cd algorithm/performance_bct/src && python -m pytest -v --tb=short
```

Expected: all tests PASS. Record exact count in the commit message.

- [ ] **Step 4: Push and tag for fintrack review**

```bash
git add algorithm/performance_bct/src/engine/__init__.py algorithm/performance_bct/src/engine/README.md
git commit -m "feat(arch-a): engine scaffold complete — PhaseInterface+Context+Engine+Logger, N tests passing"
git push origin main
```

- [ ] **Step 5: Send base.py interface + engine loop skeleton to fintrack for review**

Send fintrack (peer 95ratlkx) the following:
- Exact content of `base.py` (PhaseInterface class)
- Exact engine loop from `engine.py` `on_data_with_ctx()` method
- Test count and `pytest -v` summary

**DO NOT start ARCH-C (carving main.py into phases) until fintrack approves the scaffold.**

---

## Self-Review

**Spec coverage check:**
- §3 Phase-0a (oracle tag, gitignore): Task 0 ✅
- §4.1 PHASE_ORDER with sentinels: Task 5 ✅
- §4.2 PhaseContext (LEAN refs + BarState, apply() double-write guard): Task 2 ✅
- §4.3 Block propagation (ALWAYS_RUN tail, no hard-return): Task 5 test `test_blocked_bar_still_runs_diagnostics_and_circuit_breaker` ✅
- §4.4 Adds flow-back: stub in engine._fire(), noted as ARCH-C wire-up ✅
- §4.5 PhaseInterface contract: Task 3 ✅
- §4.6 Charter invariants FORBIDDEN_PARAMS: Task 6 ✅
- §4.8 STRATEGY_CONFIG hash: Task 5 (`_config_hash`, logged in `log_strategy_init`) ✅
- §7 Merge gate: not in scope for ARCH-A (CI setup = ARCH-H) ✅ (correctly deferred)
- §9 Structural guardrails (CharterViolation, UniverseLoadError): Task 3 exceptions defined ✅
- §14 open item: ComponentLogger defined but `_fire()` is a stub pending ARCH-C ✅ (correct)

**Placeholder scan:** None found. All code blocks complete. `_fire()` is intentionally a stub — LEAN order submission wires in ARCH-C. Noted explicitly in Task 5 Step 3 comment.

**Type consistency:**
- `PhaseResult` defined in Task 3, used in Tasks 4 (logger), 5 (engine) ✅
- `PhaseContext` defined in Task 2, used in Tasks 3, 5 ✅
- `BarState.apply(kind, result)` defined in Task 2, called in Task 5 engine loop ✅
- `ComponentLogger.log_phase(kind, phase, result)` defined in Task 4, called in Task 5 ✅
- `FireSentinel` defined in Task 5, tested in Task 5, exported in Task 7 ✅
- `ALWAYS_RUN = {"diagnostics", "circuit_breaker"}` defined in Task 5 engine.py, tested via `test_blocked_bar_still_runs_diagnostics_and_circuit_breaker` ✅
