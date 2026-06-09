# scanner-ranker-artifact-sweeps

Plan for the post-#448 scanner integration validation.

1. Add a reproducible train-all exporter to `sweeps/archive/george_lambdamart_ranker.py` that emits the runtime JSON schema validated by `src/runtime/scanner_ranker.py`.
2. Keep George labels confined to the exporter/training path; exported artifacts may contain metadata, not label/source columns as runtime features.
3. Write the generated local artifact to ignored `storage/bct_lambdamart_qc_safe_v1.json` so the existing local ObjectStore symlink can serve `objectstore://bct_lambdamart_qc_safe_v1.json`.
4. Add a scanner-ranker local sweep runner for baseline, fallback, and top10/top20/top50 variants from `sweeps/grids/scanner_ranker.py`.
5. Run unit tests for exporter/runtime/grid wiring, then run at least a local smoke sweep; full top-X pack runs if local LEAN/Docker time permits.
