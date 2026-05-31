# tests/acceptance/

Acceptance-gate tests: fast (no docker / no backtest) checks that enforce the
`docs/ACCEPTANCE_CONTRACT.md` criteria per-PR.

- **Holds:** `test_liveness.py` (#244-D — the SDLC LIVENESS GATE: the real champion_asis CONFIG fires `orders > 0` through StrategyEngine on the #247 FakeQC harness, plus the 0-trades GUARD where a deliberately-dead config fails the shared `assert_liveness` gate; also unit-tests the periodic full-FY band logic in `scripts/check_liveness_band.py`).
- **Goes here:** per-PR gate assertions that codify an acceptance-contract criterion (anti-0-trades / anti-collapse / contract invariants) and run in the standard `pytest` collection.
- **Does NOT:** per-phase unit tests (mirror `src/phases/...`), end-to-end lifecycle scenarios (`tests/integration/`), or anything requiring docker / a real LEAN backtest (that is the PERIODIC runbook in the acceptance contract).
