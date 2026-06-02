# results/archive — the durable per-run learn-substrate (#303)

What's here: one directory per `<config_hash>/<backtest_id>/`, each holding the durable artifact of
a single backtest — `result.json` (provenance + stats + run_class), `trades.jsonl.gz` (closed +
censored-open trade rows with cloud-tag conditions cond_0..7), and `funnel.json` (per-run
signal→order attrition). Plus per-config helper tables (e.g. `cloudtag_validator.csv`).

These are **non-regenerable**: QC purges backtests within hours (orders → 0), so committing them
off-machine is the substrate's only survival (the May-23 local-loss lesson). Tracked in git; only
`*.tmp`/`*.partial`/`*~` are ignored.

## RUN-CLASS — read the metrics through the class (Falk 2026-06-02)

Every `result.json` carries a `run_class` field. **It governs how the metrics may be read:**

| run_class | what it is | window protocol | are Sharpe/Ret/DD grades? |
|---|---|---|---|
| `validation` | candidate/champion test | window-then-FY, **6-window mandatory**, never FY-first | **YES** — they decide advancement |
| `substrate-generation` | #303 mine fuel | full-year OK (goal = trade count / regime coverage) | **NO** — descriptive only, NOT a grade |
| `null` | undeclared (pre-2026-06-02 / not threaded) | unknown | treat as ungraded |

**Do not cite a `substrate-generation` run's full-year Sharpe as a validation result.** Its purpose
is to fuel the winners-vs-losers mine across regimes — its metrics describe what happened in that
window, they do NOT grade the config. See `CONVENTIONS.md` → "RUN-CLASS".

### Current contents — all SUBSTRATE-GENERATION
The committed runs under `fd8248b34265/` are the 5-(soon 6-)regime #303 learn-substrate
(FY2021-2025, + FY2020 COVID-crash when it lands). They are **substrate-generation, NOT validation**
— retro-flagged via `scripts/retroflag_run_class.py`. Their per-year metrics
(FY21 +17.9% / FY22 +16.2% / FY23 −11.8% / FY24 +32.5% / FY25 +20.4%) are descriptive regime
context for the mine, not config grades. The amplifying/champion VALIDATION grades live elsewhere
(window-validated), never here.

`cloudtag_validator.csv` — the cloud-side of the #303 (c) validator: per-traded-name cloud-tag
`cond_0..7` + `decision_score` + outcome across the regimes, for the lab's 5-min-vs-cloud
cross-check. Regenerate with `scripts/extract_cloudtag_validator.py`.
