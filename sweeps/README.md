# sweeps/

The mass-runner (#214): massive config-permutation testing over the phase library, with
overfitting defenses baked in (ADR-0001 §D5). Optimization/research — distinct from `tests/`
(correctness). Phase-agnostic: the mechanics consume only the public `space()` / `COMPLEXITY`
contract + a `*_PHASES` catalog tuple; they never hardcode signal/champion specifics.

## Pipeline (the components)
- `types.py` — the shared typed interface: `SweepConfig`/`PhaseChoice` (an enumerated
  variant + its config-hash), `Window`, `ResultMetrics` (the Sharpe/Ret%/DD% trio), and the
  **`RunConfig` Protocol** — the injected run-a-config primitive (mock in tests, real LEAN
  adapter in prod).
- `enumerate.py` — catalog × `space()` → the cartesian config grid; DoF-budget split (flag +
  drop over-budget configs, ADR D5.5).
- `windows.py` — the mandatory **6 validation windows** + the per-config runner (D5.1: no
  single-number results).
- `pool.py` — bounded-concurrency, **isolated** parallel pool over (config, window) units;
  deterministic collation. The real adapter (unique LEAN project/local-id/cache, data
  symlink, marker verification) lives behind the `RunConfig` Protocol — integration-flagged,
  never unit-run.
- `aggregate.py` — per-metric distribution (mean / std / min / max / worst) across windows.
- `score.py` — the **ADR-D5 composite**: `stability(mean/std) − complexity_penalty −
  robustness_penalty`. Rank by stability, not peak.
- `leaderboard.py` — rank by composite (DESC), deterministic tie-break (stability → Occam →
  hash); CSV / Markdown render with the metrics trio + complexity + config-hash on every row.
- `provenance.py` — pin every result to (commit + config-hash + data-fingerprint); write the
  canonical ledger rows (round-trips). Promotion target: `results/bt-results.csv`.

## Layout
- `grids/` — permutation specs (TRACKED).
- `runs/` — generated isolated LEAN projects (GITIGNORED; excluded from mypy).
- `reports/` — aggregated leaderboards.

## Compute boundary
The unit/integration tests MOCK the run-a-config primitive — ZERO real LEAN / cloud spend.
The actual sweep runs LATER, when phases adopt `space()` and entry-retrofits land. The
mechanics here are proven on a tiny mock enumeration, not a real giant sweep.

## Does NOT
Unit/parity correctness tests (that's `tests/`); runtime phase wiring (runtime uses
direct-ref `Slot` configs — this catalog enumeration is for DISCOVERY/SWEEP only).
