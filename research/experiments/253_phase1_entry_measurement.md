# #253 Phase-1 — Entry-Confirm Measurement (champion_entry vs the −0.616 blind-entry baseline)

**Date:** 2026-05-31 · **Branch:** `feat/253-phase1-entry` · **Environment:** LOCAL LEAN
(conformed-coarse FY2025, 19,289-ticker pool, ~830 names/day active set, WARMUP_DAYS=560, RAW).
**NO cloud spend.** Local is an APPROXIMATION (cloud = ground truth); these are own-merits
deltas vs the LOCAL baseline run on the IDENTICAL code path + data, NOT vs the 0.778 adjusted
champion.

## RE-MEASUREMENT after the HQ #253-P1 C2 daily-OHLC fix (2026-05-31)

The C2 correctness fix (read the latest DAILY OHLC bar — low-touch pullback + bullish-close /
lower-wick bounce — NOT the close-snapshot) + the 5 ruled flags + the C3 positive-flat fix + the
dropped inert macd_signal axis are ALL applied (config_hash now `999ec7745455`). Re-running FY2025:

| Config | Sharpe | Net % | DD % | Orders |
|---|---|---|---|---|
| champion_entry (PRE-fix, close-snapshot C2) | −1.016 | +0.194 | 4.4 | 70 |
| **champion_entry (POST-fix, daily-OHLC C2)** | **−1.016** | **+0.194** | **4.4** | **70** |

**The corrected C2 did NOT move the FY trio — and that is a real STRUCTURAL finding, verified:**
- The fix IS live + correct: with an impossible C4 gate (`volume_gate_mult=100`) orders → **0**
  (confirmed:0 every bar) → the entry_selection gate provably binds. The X/4 score distribution is
  now rich (many 3/4 and 4/4 — the C2+C3 fixes produce more confirmations), confirmed in the BT log.
- min_confirm=2 vs **min_confirm=3** → **identical** (−1.016 / 70 orders). So C2/C3 do NOT change
  the FIRED-order set at the canonical params.
- ROOT CAUSE: at min_confirm=2 with C1(regime)+C4(volume) MANDATORY, **C1+C4 alone already = 2/4 →
  qualifies**, so C2/C3 only matter at min_confirm≥3 — AND even at 3, the names that actually FIRE
  are the top-of-rank ≥3/4 candidates the sizing CASH HEAT-CAP fills first; the marginal 2/4-only
  names the gate drops are beyond the cash cap anyway, so dropping them changes no fill. The gate's
  binding margin for the FIRED set is the mandatory **regime+volume** pair (which removes 5 of 75,
  75→70) — and that pair is identical under close-snapshot vs daily-OHLC C2.

**Net:** the C2 daily-OHLC fix is correct + necessary (the close-snapshot was a genuine bug, now
fixed + golden-mastered), but it does not rescue the −0.40 degradation because **C2 is not the
binding constraint on the orders that fire** — the sizing cash-cap truncates before the C2-marginal
names matter. The trigger still does not earn its place at default params on the local approximation.
FLAG for HQ: to make C2 actually bind on the fired set, the gate's X/4 score would need to drive
SIZING (the methodology's 4/4-full · 3/4-75% · 2/4-50% tiers) — i.e. a methodology SIZER consuming
`qc._entry_confirm`, which is Phase-2 scope (the baseline `flat_pct_heatcap` ignores the score).

The headline table below is unchanged by the fix (numbers identical); kept for the full record.

## Configs

| Config | config_hash | What | Orders fire? |
|---|---|---|---|
| `champion_asis` | `e573e84b1ce1` | the −0.616 BLIND-ENTRY baseline (no entry trigger) | 75 (FY) |
| `champion_entry` | `999ec7745455` (was 1b665ab98f13 pre-fix) | champion-asis stack VERBATIM + entry_selection(BctEntryConfirm) + entry_timing(MarketOnOpenEntry) | 70 (FY) — liveness PASS (>0) |

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
