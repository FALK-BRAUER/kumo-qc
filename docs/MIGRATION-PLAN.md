# Migration Plan — v1 → v2 (port-and-rewrite + data-rework)

**Epic #208.** Integration branch = `mainV2`. main stays legacy+working until ONE cutover.

## Key framing (read first)
We are NOT carving from scratch. The carve **already exists** on `worktree-arch-a-engine-scaffold @ 3705cd3` and was **parity-proven** (engine reproduces the monolith at 0 delta on the raw substrate). So migration = **PORT the sound parts + REWRITE the v2-deltas + REWORK the data layer** (which had real problems). Then look at legacy (decommission at cutover, last).

## What ports as-is (sound, parity-proven — relocate + v2-delta rewrite only)
- `src/engine/` (base, context, engine, logger + tests)
- `src/phases/signal/bct_score_full`
- `src/phases/regime/{vix_ichimoku_tier, vix_percentile, spy_200ma}`
- `src/phases/sizing/flat_pct_heatcap`
- `src/phases/exit/kijun_g3_exits`
- `src/phases/diagnostics/version_marker`
- `src/phases/shared/oracle_helpers`
- `main_champion_asis.py` → `src/strategies/champion_asis.py`
- `main_engine_parity.py` → `tests/integration/` (the re-verification harness)

**v2-delta rewrites applied during the port:** PhaseInterface ABC→`Protocol` (+`@runtime_checkable`); `dataclass(slots=True)` for BarState/PhaseResult; config dict → typed `StrategyConfig` of `Slot(impl=, params=.Params())` (direct class refs); root paths (`algorithm/performance_bct/src` → `src`).

## What is REWORKED, not ported (the carve's data problems → v2 fixes)
| Existing-carve data problem | v2 fix |
|---|---|
| #182: cloud loaded all 326 (filter inert) → different selection vs local | unified single-path loader + **`dist/` runs BOTH local & cloud** (code parity by construction) |
| `polygon_local` = hardcoded **326 snapshot** (contamination) | **dynamic universe** — rework the universe phase OFF the snapshot |
| cloud-vs-local **data-vendor residual** (QC prices ≠ local parquet) | **cloud = ground-truth** methodology; local-on-raw-parquet = approximation; pin by fingerprint |
| back-adjusted data corrupted Ichimoku (1.079 artifact) | **clean raw-only `data/`** + `MANIFEST` fingerprint (ba8307b6, #219) |
| results not pinned to data state | **data-fingerprint in `dist/_metadata.py`** + `results/` schema |

→ The **universe phase + data loader/path are REBUILT on v2**, not lifted from the broken `polygon_local`.

## Stages (test-driven — each move carries its verification)
0. **Foundation** (#210/#211): port engine → root `src/` + Protocol/slots/direct-ref rewrite; AST closure build; test harness. *Test:* ported engine tests + `mypy --strict` + build-script unit tests.
1. **Data + universe rework** (#219 + #214 dynamic-universe + the loader): clean raw `data/` + MANIFEST + symlink; unified loader; dynamic universe phase. *Test:* BT reads data (non-zero); fingerprint == ba8307b6.
2. **Port sound phases + assemble** (#212): relocate signal/regime/sizing/exit/diagnostics + `champion_asis` config (direct-refs). *Test:* **re-run `main_engine_parity` → still 0 delta vs `baseline-oracle-v0` on the raw substrate.** Per-phase tests port over.
3. **Deploy parity** (#213): lean.json→`dist/`, deploy from `dist/`. *Test:* cloud `dist/` run vs local `dist/` — adopt cloud=ground-truth; document any data-vendor delta (don't chase exact).
4. **Validation gates** (#215): G1–G5 (incl DSR/PBO #202) on champion_asis. *Test:* gate suite green or honestly-pending.
5. **Cutover** (#216): full regression green → archive `algorithm/performance_bct` (the legacy oracle) → flip `mainV2`→`main`. *Test:* whole `pytest` + parity re-run.

## Legacy
`algorithm/performance_bct/main.py` on `main` = the **oracle / parity reference**, untouched, working throughout. Decommissioned ONLY at cutover (#216), after ported v2 runs at parity + deploys.

## Testing principle
Every move produces a permanent automated test in `tests/` (mirroring `src/`). The parity harness re-run after each rewrite catches behavior drift. By cutover, the migration is re-verifiable with one `pytest` + one parity run.
