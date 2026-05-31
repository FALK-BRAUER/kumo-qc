# #253 Phase-1 — Entry-Confirm Measurement (champion_entry vs the −0.616 blind-entry baseline)

**Date:** 2026-05-31 · **Branch:** `feat/253-phase1-entry` · **Environment:** LOCAL LEAN
(conformed-coarse FY2025, 19,289-ticker pool, ~830 names/day active set, WARMUP_DAYS=560, RAW).
**NO cloud spend.** Local is an APPROXIMATION (cloud = ground truth); these are own-merits
deltas vs the LOCAL baseline run on the IDENTICAL code path + data, NOT vs the 0.778 adjusted
champion.

## Configs

| Config | config_hash | What | Orders fire? |
|---|---|---|---|
| `champion_asis` | `e573e84b1ce1` | the −0.616 BLIND-ENTRY baseline (no entry trigger) | 75 (FY) |
| `champion_entry` | `1b665ab98f13` | champion-asis stack VERBATIM + entry_selection(BctEntryConfirm) + entry_timing(MarketOnOpenEntry) | 70 (FY) — liveness PASS (>0) |

Only delta between them = the §4 Gate-2 entry-confirmation gate (controlled measurement).

## HEADLINE — Full FY2025 (the apples-to-apples vs the −0.616 reference)

| Config | Sharpe | Net % | Max DD % | Orders |
|---|---|---|---|---|
| **champion_asis (baseline)** | **−0.616** | +3.899 | 3.4 | 75 |
| **champion_entry** | **−1.016** | +0.194 | 4.4 | 70 |
| **Δ (entry − baseline)** | **−0.400** | −3.705 | +1.0 (worse) | −5 |

**Baseline EXACTLY reproduces the −0.616 / +3.9% / 75-order reference** → the local harness is
faithful (the entry measurement is trustworthy as a LOCAL delta).

## VERDICT (own merits) — the entry-confirm trigger does NOT earn its place at default params

At the methodology-canonical defaults (gate ≥2/4, volume 1.0×, pullback 0.5%, MACD 12/26/9), the
§4 Gate-2 trigger **degrades** risk-adjusted return on the local data: Sharpe −1.016 vs −0.616
(**−0.40**), return collapses (+0.19% vs +3.9%), drawdown rises (4.4% vs 3.4%), and it drops only
5 of 75 entries (≈7%). It removed a handful of entries that, net, were CONTRIBUTING — not cutting
the bad ones. **It does not improve entry quality here.** This is a clean negative result, reported
honestly (NOT spun): the trigger as specified + defaulted is not additive on this baseline/data.

### Why the small order drop (75→70) despite hard per-window gating
The 6-window split (below) shows aggressive gating (e.g. W1 4→2), but over the FULL year the gate
passes ≈93% of entries. The gate's binding sub-conditions (C2 T-Bounce pullback-touch on the
rebalance-day snapshot; C3 MACD turning) only rarely coincide with a rebalance-day candidate, so
most days the qualified set is tiny and the gate is near-inert — yet the few it removes were
net-positive. FLAG: the C2 once-daily-snapshot evaluation (vs an intraday touch) is a candidate
reason the trigger underperforms its methodology intent — see the reconciliation FLAGS.

## 6-window distribution (bi-monthly FY2025) — NOISE-DOMINATED, reported for completeness

Each window = an INDEPENDENT BT (fresh 560-day warmup, ~40 trading days, 0–4 orders). Annualizing
a Sharpe on ~40 days with 1–4 trades is statistically meaningless — these per-window Sharpes are
NOISE and must NOT be over-read. The full-FY single run above is the load-bearing measurement.

| Window | champion_asis Sharpe / Ret% / DD% / Ord | champion_entry Sharpe / Ret% / DD% / Ord |
|---|---|---|
| W1 (Jan–Feb) | −8.234 / −0.104 / 0.2 / 4 | −12.988 / −0.034 / 0.2 / 2 |
| W2 (Mar–Apr) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| W3 (May–Jun) | −4.784 / 0.396 / 0.2 / 1 | −4.784 / 0.396 / 0.2 / 1 |
| W4 (Jul–Aug) | −5.482 / 0.331 / 0.2 / 3 | −6.187 / 0.265 / 0.2 / 3 |
| W5 (Sep–Oct) | −6.177 / 0.214 / 0.3 / 3 | −6.177 / 0.214 / 0.3 / 3 |
| W6 (Nov–Dec) | −11.336 / 0.041 / 0.2 / 1 | −12.657 / −0.047 / 0.2 / 1 |
| **mean Sharpe** | **−6.00** | **−7.13** |
| **std Sharpe** | 3.79 | 4.69 |
| total orders | 12 | 10 |

Raw CSVs: `research/experiments/253_measure_asis.csv`, `253_measure_entry.csv`.

**Window caveat FLAGGED:** the 6-window distribution is starved of trades (2-month windows
barely let positions open before the window ends). For a real window distribution the windows must
be longer (quarterly minimum) or overlapping — recommend HQ run a proper walk-forward, or judge on
the full-FY delta (which is unambiguous: −0.40 Sharpe, the trigger hurts at defaults).

## Reproduction (NO cloud)

```bash
# build both dists (champion_entry is the tracked dist; champion_asis built to a side project)
python -c "import sys;sys.path[:0]=['src','build'];from build.cloud_package import build;build('strategies.champion_entry')"
# projects algorithm/v2_champion_{entry,asis} = dist copy + a lean.json; bake START/END on the
# generated BCTAlgorithm subclass (project copy only), then: lean backtest <proj>
bash scripts/measure_253_windows.sh algorithm/v2_champion_entry entry   # 6-window
# full-FY: bake (2025,1,1)..(2025,12,31) and lean backtest each project
```

## Caveats / integrity

- LOCAL approximation only; cloud is ground truth (charter). These are deltas on the local code
  path + conformed-coarse data, NOT a deployable verdict.
- The baseline reproduces −0.616/+3.9%/75-orders EXACTLY → harness faithful.
- Every number above is from a real LEAN backtest output JSON (no fabrication; the data-integrity
  rule). The `v2_champion_{entry,asis}` backtest dirs hold the source artifacts.
