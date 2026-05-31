# phases/signal/

The **signal / qualify** phase kind: score each universe candidate for entry quality and keep
the ones that qualify (`score ≥ min_score`). Answers *"does the name qualify?"* — NOT *"is now
the moment to enter?"* (that is the separate `entry_timing` kind).

- **Holds:** one subdir per impl (`<impl>/<impl>.py` + `README.md`), plus `library.py` — the
  `SIGNAL_PHASES` catalog (typed tuple of DIRECT CLASS REFS for sweep discovery; ADR D3).
- **Members:** `bct_score_full` (the canonical 8-condition BCT scorer). `sample_bct` is a
  config-only teaching fixture and is deliberately NOT in the catalog.
- **Contract:** reads `ranked_candidates`, provides qualified candidates downstream; declares
  `PHASE_KIND="signal"`, a `version_marker`, a `Params.space()`, and a `COMPLEXITY` decl.
- **Does NOT:** entry timing, sizing, ranking, or universe selection.
