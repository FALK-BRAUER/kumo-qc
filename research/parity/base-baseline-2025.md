# champion_asis — MASTER BASE-BASELINE (FY2025)

**The authoritative reference baseline.** Everything (exit phase, sweeps, variants) measures against
this. Provenance-pinned: `commit 369b5d9` · `config_hash e573e84b1ce1` · `data_fingerprint 90f2d7e3`.

Recorded in `results/bt-results.csv` (rows marked `BASELINE-MASTER-LOCAL` / `BASELINE-MASTER-CLOUD`).

---

## A. LOCAL full-FY2025 (the canonical single number — REPRODUCED EXACTLY)

| Metric | Value |
|---|---|
| **Sharpe** | **−0.616** |
| Net profit | **+3.899%** |
| Max drawdown | **3.4%** |
| Total orders | **75** |
| Round-trips | 32 |
| Win rate | 31% |

- Window: FY2025 (2025-01-01 .. 2025-12-31), `WARMUP_DAYS = 560`.
- Artifact: `algorithm/v2_champion_asis/backtests/2026-05-31_20-46-41/` (throwaway lean project,
  built from `src/strategies/champion_asis.py` via `build/cloud_package.py` — NOT committed; `dist/`
  tracks the champion, this is the `dist_tmp`-pattern side project).
- **Reproduces the prior unrecorded −0.616 / +3.9% / 75-order reference EXACTLY** → the local harness
  is faithful. This is the number that was floating around uncommitted; it is now recorded + pinned.

## B. CLOUD full-FY2025 (ground truth — arch2_champion_v2, PID 32319236)

| Metric | Value |
|---|---|
| **Sharpe** | **−0.787** |
| Net profit | **−11.848%** |
| Max drawdown | **21.9%** |
| Total orders | **324** |
| Win rate | 35% |

- bt_id: `8cd94678f037055e1bf4263ee4c9315f` (name `base-baseline-fullFY-e573e84b`).
- Full-FY default baked in dist (NO Step-A short-window injection — the driver's
  `STEP_A_WINDOW` was nulled for this run). 560-warmup, completed in ~25 min (the #240 rolling-DV
  path; no per-day history fan-out).
- ACTIVE_SET via `/backtests/chart/read` (Universe chart, #243 emit): **UNAVAILABLE** — the QC chart
  endpoint returned `"Error retrieving backtest chart, please try again later"` on every retry
  (known QC flakiness on this endpoint for this BT). Used the **orders** as the ground-truth
  selection proxy instead (stronger signal than the chart count anyway).

## CLOUD ≈ LOCAL PARITY — **FAIL (material divergence)**

| Metric | Local | Cloud | Delta |
|---|---|---|---|
| Sharpe | −0.616 | −0.787 | **−0.171** |
| Net % | +3.899% | −11.848% | **−15.7 pp** |
| DD % | 3.4% | 21.9% | **+18.5 pp** |
| Orders | 75 | 324 | **+249 (4.3×)** |
| Unique symbols traded | 37 | 118 | **3.2×** |

**This is NOT the expected ~vendor-residual (the Step-A ~1.10× active-set band). The trio is
materially off and the sign of the return flips (+3.9% local → −11.8% cloud).** Sharpe alone
(−0.171) looks within a loose band, but return, drawdown, and order count all diverge hard — Sharpe
is NOT a sufficient parity metric here (the charter's "±0.3 Sharpe on a non-amplifying baseline hides
selection divergence" lesson, made concrete).

### First-order diff (orders = ground truth; NO fabrication)

- **Cloud trades 118 unique symbols / 324 orders; local trades 37 / 75.** Cloud's traded set is ~3×
  wider and turns over ~4× more.
- Both DO trade SPY (local: `SPY XOF4GF67NMG5`, 8 fills, its top symbol; cloud: SPY 6 + QQQ 6) — SPY is
  in the tradeable universe on both sides, not a cloud-only artifact. So the divergence is not "cloud
  added ETFs."
- Cloud order distribution by month is dense and roughly uniform (60/23/41/15/27/20/8/30/12/38/31/19)
  — i.e. cloud is entering/rotating across far more names every month than local's ~6/month.
- Local substrate is NOT the constraint: `data/MANIFEST.json` = 19,292 daily zips (fingerprint
  `90f2d7e3`) — local has plenty of names to select from. So the gap is in the **selection mechanics**
  (the once-daily coarse `filter→rank→cap` gate), not the data pool size.

### Root-cause direction (for HQ — needs the full #173 first-divergence-day diff)

The selection gate (`runtime/lean_entry.py::_coarse_selection`) is supposed to run the SAME
filter→rank→cap code path local + cloud. The 4.3× order / 3.2× symbol gap says the **effective active
set differs materially** between LEAN-local coarse and QC-cloud native coarse — either:
  1. the `coarse_max` cap / DV-rank floors resolve to a much larger qualifying set on cloud (cloud's
     native coarse feed delivers far more names/day with fundamentals than the local coarse the LEAN
     container synthesizes from `data/`), or
  2. a rank/floor parameter is not biting identically on the two coarse feeds.

This is the **exact selection-divergence class the charter warns amplifies** (E40d tolerated it at
±0.3 Sharpe; Pe pyramid exploded it). champion_asis is non-amplifying so the Sharpe gap is "only"
−0.171 — but the underlying selection divergence is large and WILL explode under any amplifying
variant. **Before any variant is trusted, this gate must be diffed to first-divergence-day
(concurrent active set local vs cloud on day 1) per #173.** Recommend HQ open that as the load-bearing
follow-up; it is OUT OF SCOPE for this measurement-and-record task.

**Load-bearing baseline = the FULL-FY rows (local AND cloud), recorded as-is.** The cloud row is the
ground truth and it is RED. The local row is the faithful harness reproduction.

## C. 6-WINDOW LOCAL (robustness distribution — NOISY, trade-starved)

Six contiguous ~2-month FY2025 windows, each with a fresh 560-day warmup before its start.

| Window | Period | Sharpe | Net % | DD % | Orders |
|---|---|---|---|---|---|
| W1 | 2025-01-01 .. 02-28 | −8.234 | −0.104 | 0.2 | 4 |
| W2 | 2025-03-01 .. 04-30 | 0.000 | 0.000 | 0.0 | 0 |
| W3 | 2025-05-01 .. 06-30 | −4.784 | +0.396 | 0.2 | 1 |
| W4 | 2025-07-01 .. 08-31 | −5.482 | +0.331 | 0.2 | 3 |
| W5 | 2025-09-01 .. 10-31 | −6.177 | +0.214 | 0.3 | 3 |
| W6 | 2025-11-01 .. 12-31 | −11.336 | +0.041 | 0.2 | 1 |

Artifacts: `algorithm/v2_champion_asis_win/backtests/*` (per-window dirs in `results/bt-results.csv`).

### FLAG — this is a NOISY distribution, NOT a clean per-window signal

A ~75-order/yr strategy over 2-month windows = **~12 orders/window expected; actual 0–4**. The
windows are **trade-starved + noise-dominated** — positions barely open before the window ends, the
560-warmup eats most of the lookback, and the Sharpe values (−4 to −11) are annualized artifacts of
1–4 trades, not robustness signal. The #253-P1 measurement already found this exact pathology. W2
opened ZERO trades. **Do not read these as a per-window verdict.** The **full-FY (local + cloud) is
the load-bearing baseline.**

### WINDOW-DEFINITION FLAG (flag-don't-guess) — for HQ

The "mandated 6 windows" are NOT cleanly defined for an FY2025-only run:
- The conformed-coarse substrate is **FY2025-ONLY** (`90f2d7e3`) — there is no multi-year conformed
  coarse data locally.
- The #214 `SIX_WINDOWS` default is **2020–2024** — NOT FY2025, and not runnable on the FY2025-only
  substrate.
- So I **proposed + ran** a defensible FY2025 6-split (6 contiguous ~2-month windows, above). It is
  the best available within the FY2025 substrate, but it is trade-starved (above).
- **The real 6-window robustness gap:** a proper walk-forward needs **data beyond FY2025** (quarterly
  or overlapping multi-year windows), which is **not conformed locally**. This is the genuine gap —
  flagged for HQ. Recommend either (a) conform multi-year coarse data, or (b) judge robustness on the
  full-FY local+cloud trio + a cloud walk-forward, not the FY2025 bi-monthly split.

---

## Provenance (every row pinned)

- `commit`: `369b5d955c9c88522ce65f5684ac2a36747de9a4` (`369b5d9`, branch `chore/base-baseline` off
  `mainV2`)
- `config_hash`: `e573e84b1ce1` (champion_asis built closure — matches `dist/_metadata.py`)
- `data_fingerprint`: `90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c`
  (`data/MANIFEST.json`, 19,292 tickers, RAW daily)
- Phase markers: `dv_rank_cap_v1` · `bct_score_full_v1` · `spy_200ma_v1,vix_percentile_v1` ·
  `flat_pct_heatcap_v1` · `kijun_g3_exits_v1` · `version_marker_v1,chart_emit_v1`

## Data integrity

Every number above is from a real BT artifact — local result `summary.json` + order-events, and the
cloud `/backtests/read` statistics + `/backtests/orders/read` (324 orders fetched and counted). The
cloud ACTIVE_SET chart could NOT be retrieved (endpoint error, reported honestly, not fabricated);
the orders were used as the selection proxy. NO values were inferred or filled in.
