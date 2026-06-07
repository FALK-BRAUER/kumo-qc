# tests/harness/

Shared test infrastructure (no `src/` counterpart). Reused by unit tests, integration, and `sweeps/`.

- **Holds:** `stub_phases.py` (slot-instantiable engine stubs, including upstream/downstream contract metadata); `realdata.py` (#260 — real on-disk loaders for daily/intraday-5min/coarse + the `_coarse_selection` driver + the canonical QC-native value-WRAPPERS the real-data tests share, replacing the triplicated `_Cur`/`_Ichi`/`_Adx`/`_Window` shapes); `gdata_asserts.py` (#260 — the G-DATA assertion verbs: non-empty/warm, cold-cannot-score, crash-not-mirage, the #237 zero-coverage trap).
- **Planned:** `bt_runner.py` (run a LEAN BT), `parity_diff.py` (cloud-vs-local / engine-vs-oracle diff, runs the `dist/` artifact), `assertion_lib.py` (G1-G5 + charter asserts), `metric_extractor.py`, `fixtures/` (FakeQCAlgorithm, stub phases).
- **Goes here:** reusable run/metric/assert primitives.
- **Does NOT:** specific test cases (those mirror src/).
