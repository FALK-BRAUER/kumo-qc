# phases/signal/oracle_signal/

The **#322 OracleSignal PROD-PHASE BRIDGE** — the seam that swaps the kumo-lab #303 mine's
LEARNED predictor in for the hand-coded `BctScoreFull` `score >= 7` signal, when the lab ships one.

- **What's here:** `oracle_signal.py` — the `OracleSignal` signal phase (same contract as
  `BctScoreFull`: reads `ranked_candidates`, emits qualified candidates to `sized_orders`), plus
  the `Predictor` interface, the `CandidateFeatures` feature contract, the `PredictorOutput` type,
  the `BctPassthroughPredictor` stub (== `BctScoreFull` parity), and `PredictorError` (fail-loud).
- **The seam:** the per-candidate decision is delegated to an INJECTED `Params.predictor`. The
  default stub reproduces `BctScoreFull` (no-op swap); the lab replaces it with a learned model.
- **Feature contract:** the lab's predictor is a function of `CandidateFeatures` (the 8 BCT
  conditions + bct_score + roc13/dollar_vol/rank/regime_ok). Add a field there if the model needs one.
- **Scaffold only:** NOT in `library.py` and NOT wired into any champion config (Falk's call once a
  real predictor exists). Fail-loud on a non-finite predictor score (`PredictorError`).
