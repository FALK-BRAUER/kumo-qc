# tests/harness/

Shared test infrastructure (no `src/` counterpart). Reused by unit tests, integration, and `sweeps/`.

- **Holds:** `bt_runner.py` (run a LEAN BT), `parity_diff.py` (cloud-vs-local / engine-vs-oracle diff, runs the `dist/` artifact), `assertion_lib.py` (G1-G5 + charter asserts), `metric_extractor.py`, `fixtures/` (FakeQCAlgorithm, stub phases).
- **Goes here:** reusable run/metric/assert primitives.
- **Does NOT:** specific test cases (those mirror src/).
