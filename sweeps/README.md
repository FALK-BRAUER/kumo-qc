# sweeps/

Massive config-permutation testing over the phase library. Optimization/research — distinct from `tests/` (correctness).

- **Holds:** `driver.py` (expand a grid → bounded parallel LEAN pool, each run FULLY isolated [unique project/local-id/cache, data symlinked, marker-verified] → aggregate), `grids/` (permutation specs, tracked), `runs/` (generated isolated LEAN projects, GITIGNORED), `reports/` (leaderboards).
- **Goes here:** sweep driver + specs + outputs.
- **Does NOT:** unit/parity tests. The driver may introspect the library to enumerate phases (discovery catalog only — never runtime wiring; runtime uses direct-ref configs).
