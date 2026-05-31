# tests/parity/

G-DATA local↔cloud parity regression guards (#265). FAIL-LOUD, real recorded data.

- **Holds:** `test_local_cloud_parity.py` (local within documented band of the recorded cloud
  ground-truth; mirage guard on the real local BT), `test_dist_runs.py` (committed dist IS the
  champion closure + rebuilds to the pin + produces the recorded champion result),
  `test_residual_diff_constants.py` (the offline-replay floors stay pinned to the live engine).
- **Goes here:** parity / cloud-ground-truth regression tests that read the ledger
  (`results/bt-results.csv`) and on-disk BT artifacts. They never call the QC cloud API.
- **Does NOT:** run a live LEAN backtest (too heavy for CI — the heavy BT runs out-of-band and
  is recorded in the ledger; these tests assert the recorded result + the real artifact when present).
