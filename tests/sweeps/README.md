# tests/sweeps/

Tests for the #214 mass-runner (mirrors `sweeps/` 1:1). ALL on a TINY MOCK catalog + a
deterministic fake run-a-config primitive — **ZERO real LEAN / cloud spend** (the #214 HQ
constraint: build the mechanics, mock the run).

- **Holds:** `conftest.py` (the mock catalog: `TwoAxisPhase`/`OneAxisPhase`/`NoAxisPhase`/
  `BigDoFPhase` + `make_runner`), and `test_<module>.py` per `sweeps/` component.
- **Goes here:** behavioral unit tests of enumeration / pool / windows / aggregate / score /
  leaderboard / provenance, sweep-to-build mapping, plus a tiny integration test wiring the REAL
  `SIGNAL_PHASES` through `enumerate` (the RUN stays mocked).
- **Does NOT:** run real backtests, touch cloud, or import LEAN. The run-a-config primitive is
  always injected as a fake.
