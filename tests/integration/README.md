# tests/integration/

Cross-cutting tests that exercise multiple phases / the whole engine end-to-end.

- **Holds:** `test_e2e_lifecycle.py` (#247 — the real champion_asis CONFIG driven through StrategyEngine across warmup→universe→signal→regime→sizing→exit→diagnostics, order/position ledger asserted) + its `fake_qc.py` harness (a realistic FakeQC that lets the REAL phases run). `test_warm_before_score_realdata.py` (#264 — the anti-mirage seed guard on real daily data). `test_gdata_chain_realdata.py` (#260 — the `gdata`-marked real-data CHAIN: REAL `_coarse_selection` → REAL seed/warm → REAL `score_symbol_native` on one real session, plus the cold-cannot-score pair, the crash-not-mirage degraded-feed pair, and the #237 zero-coverage trap). `test_strategy_baseline.py` (a full strategy runs end-to-end), `test_cloud_local_parity.py` (dist/ runs identically local vs cloud).
- **Goes here:** tests spanning >1 phase or the engine loop as a whole.
- **Does NOT:** single-phase unit tests (those mirror `src/phases/<kind>/<impl>/`).
