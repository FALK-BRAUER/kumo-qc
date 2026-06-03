# tests/scripts

Unit tests for the analysis/diagnostic helpers under `scripts/` (not the strategy engine — those live under `tests/engine`, `tests/phases`).

Goes here: tests for script-level tools — funnel counts, cloud-clean asserts, the #349/#353 feature panel (as-of-date, no-look-ahead, fail-loud on missing data).
Does not go here: phase/engine tests, parity tests, or anything importing the LEAN runtime.
