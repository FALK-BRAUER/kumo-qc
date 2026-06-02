# results/archive/candidates/

The (B) signal-winner candidate-universe artifacts — the #303 learn-substrate INPUT side. One
JSONL per fiscal year: the FULL daily candidate population (every score>=7 BCT signal-winner) plus
each candidate's signal-time context, generated deterministically from local LEAN daily zips by
`scripts/gen_candidate_universe.py` (logic in `sweeps/archive/candidates.py`).

Goes here: `<year>.jsonl` per-year populations (e.g. `2024.jsonl`), `2025_snapshot.jsonl` (FY2025
from the polygon snapshot). Does NOT go here: the per-run TRADED archive (that lives under
`results/archive/<config_hash>/<backtest_id>/` — closed/censored trades only).

Format: line 1 = header record (`record_type=header`: data vendor/normalization, funnel params,
fiscal year, field list); each subsequent line = one signal-winner row (date, symbol, score,
cond_0..cond_7, signal-time features, scanner_rank, passed_prefilter/floors/parabolic flags). The
kumo-lab mine joins its forward-outcome oracle onto this authoritative population (zero parity
drift — kumo-qc owns the funnel def + runs the SAME shared scoring core).

NOTE — FY2021 is PARTIAL: local daily data begins 2021-05-12, so the FY2021 artifact covers only
~May–Dec 2021. FY2022–FY2025 are full years.
