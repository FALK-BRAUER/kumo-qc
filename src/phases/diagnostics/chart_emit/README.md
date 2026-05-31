# phases/diagnostics/chart_emit

Cloud-observability diagnostics phase (#243): emits the universe-selection counts as a
custom QC CHART so cloud diff-ladder parity is observable WITHOUT instrumenting `main.py`.

- **What it holds:** `chart_emit.py` (the phase) + its test mirror.
- **Why:** QC's API no longer returns user `Log()` output and ObjectStore export is blocked
  (non-Institutional). The ONLY remaining channel for cloud backtest internals is custom
  CHART series, which surface via `POST /backtests/chart/read`. This phase replaces a former
  uncommitted `main.py` instrumentation hack with a git-clean, committed phase.
- **What it emits** (chart `"Universe"`, two numeric series):
  - `active_set` = `len(qc._ranked_today)` — the daily selected-universe size. THE parity
    signal (the Step-A 1.10x vendor residual was measured on this count). Defensive read:
    missing attr / None → 0.
  - `ranked` = `len(bar_state.ranked_candidates)` — the per-bar tracked-candidate count
    (what the `dv_rank_cap` universe phase emitted this bar).
- **Upstream:** `REQUIRES_UPSTREAM = []` — reads qc runtime state + bar_state, provides
  nothing downstream. List-kind sibling of `version_marker` (the engine keys diagnostics by
  `(kind, module)`, so two diagnostics sub-phases coexist).
- **QC plot API (verified via Context7 — `/quantconnect/documentation`):**
  `self.plot("<chart>", "<series>", value)` (snake_case Python; C# `Plot()`). Chart + series
  auto-create; numeric value plotted at `QC.Time`. Custom numeric series read back via
  `POST /backtests/chart/read` → `ReadChartResponse.chart.series[].values`.
- **Single code path:** the plot runs IDENTICALLY local + cloud (locally LEAN records the
  chart too — harmless). NO `if cloud`. `qc.plot` is `getattr`-guarded so a unit-test FakeQC
  without `plot` no-ops gracefully; LEAN always provides it.
- **Charter:** observability ONLY. Zero trading effect — never mutates LEAN, never sizes,
  exits, or selects. Do NOT add trading logic here.
