# sweeps/adapters/

The REAL `RunConfig` adapters (#214) — the run-a-config primitive behind the Protocol.

- `result_parse.py` — single QC-stats→`RunResult` parser (local JSON + cloud `/read` share
  the same QC key names). Fail-loud: NaN/inf → raise; empty-orders → degraded flag.
- `local_lean.py` — `LocalLeanRun`: drives `lean backtest` in an isolated per-(config,window)
  dir; marker-verify; fail-loud on degraded. The fast filter.
- `cloud_lean.py` — `CloudLeanRun` + `assert_cloud_clean`: drives a cloud deploy+run, gates on
  the clean-finish contract (raises `CloudValidationError`). Ground truth.

What goes here: real run-a-config impls + their shared parsing. What doesn't: the sweep
mechanics (enumerate/pool/score — parent dir), objective math (#323), or unit fixtures (tests/).
The dist-build / lean-run / cloud-call steps are INJECTED so the adapters unit-test on fixtures.
