# #372 stage-1 — multi-timeframe SHAPE discrimination on the score-7 entry pool

**Date:** 2026-06-05
**Branch:** feat/362-snapshot-spike (worktree kumo-qc-362)
**Type:** OFFLINE hypothesis test (NO LEAN, NO Docker, NO mainV2 change). Not a proven edge.
**Verdict: FAILS the #349 robustness bar → joins #371. Entry-selection exhausted for this representation too.**

## Question

#349 graded single daily scalars on the score-7 entry pool and found **nothing** robust across regimes.
The #372 hypothesis: the discriminator between a base-breakout winner (CIBR-style) and a parabolic-spike
loser (IGV 94→107 vertical, entry at the blow-off) is the **SHAPE** of the last few weeks plus
multi-timeframe agreement — `dist_ath` cannot separate them (similar distance from high). This stage-1
test asks the same #349 question with a richer SHAPE representation, held to the same honest bar.

## Method

- **Pool:** score==7 candidates (the marginal entry pool — `passed` fate == score≥7; score-8 are the
  easy names, score-7 is exactly where #349 failed). Per ticker the earliest score-7 date per quarter;
  features as-of that date; FY-horizon label (entry→2025-12-31). Pool = entered + non-entered, winner +
  loser. The CIBR/IGV pair is NOT the pool.
- **Quarters (config_hash 65c0cf447168):** Q1 bear (447), Q2 bull (391), Q3 bull (548), Q4 bear (557).
- **No look-ahead:** every shape feature reads only bars with date ≤ asof. Proven by
  `scripts/test_372_shape_asof.py` — appends 60 wild future bars (±1e6 spikes, vol 9e9) and asserts every
  feature value is byte-identical (all 11 features: **OK**, none None).
- **Features (`scripts/feature_panel_shape.py`):**
  1. multi-TF trend agreement — `mtf_agreement` (sign sum of daily/weekly/monthly slopes, the
     IGV-divergence flag), `mtf_slope_dispersion` (daily − monthly slope = recent acceleration vs base),
     `mtf_slope_weekly`, `mtf_slope_monthly`.
  2. base-vs-spike — `extension_above_base`, `parabolic_accel` (2nd-derivative of close = blow-off),
     `range_expansion` (recent ATR / base ATR), `consolidation_quality` (base tightness),
     `days_since_breakout` (breakout recency).
  3. `stage_room` — distance-above-base ÷ distance-to-prior-high (early-with-room vs late-extended).
- **Grade:** per-feature Spearman IC per quarter + Q1∧Q3 robustness gate (same-sign, both |Sp|≥0.10);
  multi-feature interpretable composite (`regime_composite.fit_composite`/`oos_evaluate`) graded OOS
  BOTH directions (fit Q1→test Q3 AND fit Q3→test Q1, frozen, no leak).

## Result 1 — per-feature Q1∧Q3 IC (sign + magnitude)

| feature | Q1 (bear) | Q2 (bull) | Q3 (bull) | Q4 (bear) | Q1∧Q3 μ | robust? |
|---|---:|---:|---:|---:|---:|:--:|
| parabolic_accel | -0.155 | -0.085 | -0.052 | -0.020 | -0.104 | . |
| mtf_slope_weekly | -0.001 | +0.060 | +0.168 | +0.039 | +0.083 | . |
| mtf_slope_dispersion | +0.021 | +0.030 | -0.124 | -0.031 | -0.052 | . |
| stage_room | -0.032 | +0.092 | +0.132 | +0.060 | +0.050 | . |
| range_expansion | -0.008 | -0.149 | -0.087 | +0.001 | -0.047 | . |
| mtf_slope_monthly | -0.040 | -0.007 | +0.130 | +0.021 | +0.045 | . |
| consolidation_quality | +0.072 | -0.256 | -0.155 | +0.025 | -0.042 | . |
| dist_ath (contrast) | +0.088 | -0.055 | -0.038 | +0.100 | +0.025 | . |
| mtf_agreement | -0.035 | -0.087 | +0.066 | +0.011 | +0.015 | . |
| days_since_breakout | +0.055 | +0.062 | -0.042 | +0.003 | +0.007 | . |
| extension_above_base | -0.054 | +0.107 | +0.048 | +0.004 | -0.003 | . |

**PER-FEATURE ROBUST (Q1∧Q3 same-sign, both |Sp|≥0.10): NONE.**

Every feature fails the gate. The closest is `parabolic_accel` (Q1 -0.155, monotone-decaying across
quarters to -0.020) — directionally sensible (steepening/blow-off → worse forward return) but it does
NOT clear |Sp|≥0.10 in Q3 (-0.052), and the effect fades with regime rather than holding. This is the
exact #349 disproof pattern: a one-quarter signal that does not survive into the other regime.

## Result 2 — multi-feature composite, OOS both directions (the spec's key test)

10 SHAPE features, interpretable correlation-signed z-score composite, fit frozen on one quarter, scored
on the held-out quarter:

| fit→test | Sp(OOS) | AUC | n_test |
|---|---:|---:|---:|
| Q1→Q3 | **-0.162** | 0.403 | 548 |
| Q3→Q1 | -0.031 | 0.442 | 447 |

Need BOTH Sp>0 AND AUC>0.5 to pass. Both directions are **negative Sp** and **AUC<0.5** — the composite
ranks the wrong way out of sample. Combining the features does not rescue them; the single-IC weakness is
not a multivariate-aggregation artifact.

## Result 3 — CIBR / IGV shape sanity (illustrative only)

IGV reaches score-7 (`passed`) in Q4 2025-10-02; **CIBR never reaches the score-7 entry gate** in any
quarter, so it is not a pool member. CIBR shape is computed as-of IGV's entry date purely for contrast.

| feature | IGV | CIBR |
|---|---:|---:|
| FY label | -8.7% | -7.4% |
| mtf_agreement | +3.0 | +3.0 |
| mtf_slope_dispersion | -0.0160 | -0.0093 |
| extension_above_base | -0.1643 | -0.0072 |
| parabolic_accel | -0.0030 | -0.0004 |
| range_expansion | +0.7258 | +0.7420 |
| consolidation_quality | -0.1215 | -0.0938 |
| days_since_breakout | +10.0 | +10.0 |
| stage_room | +999.0 | +999.0 |
| dist_ath | -0.7420 | -0.0012 |

Honest caveats:
- At this particular date the shape features do NOT cleanly separate the two (both ~aligned trend, both
  range-expanded ~0.73, identical days_since_breakout / stage_room sentinels). The one big split is
  `dist_ath` — the very scalar #372 expected to be useless — and even that points to IGV being far below
  a 2021 ATH (vendor series is split/adjusted; IGV 333.78 in 2021 → 105.72 end-2025), not to the
  blow-off geometry the hypothesis targets.
- This date is NOT the spec's motivating +$121/−$111 event (CIBR isn't even in the pool here; both names
  show negative FY labels as-of Oct-02). The motivating dollar P&L pair came from a different
  entry/config and is anecdotal.
- **Pair-separation would not have implied pool-generalisation anyway** (the #349 trap). The pool-level
  grades above are decisive; the pair table is a sanity sniff, not evidence.

## Verdict

**FAILS the #349 robustness bar.**
- No per-feature is Q1∧Q3 robust (same-sign, |Sp|≥0.10): NONE.
- The multi-feature composite does not rank OOS in either direction (both Sp<0, both AUC<0.5).
- CIBR/IGV pair separation is absent/anecdotal and would not generalise regardless.

The multi-timeframe SHAPE representation does **not** discriminate winners from losers on the score-7
entry pool any better than the single daily scalars #349 already disproved. It is **banked with #371 —
entry-selection is exhausted for this representation too.** It is NOT a candidate for stage-2 BT
(#370-gated). Consistent with the project's standing finding (memory): the lever is per-name entry
TIMING/exit discipline (intraday confirm + stop-market), not a richer as-of-entry static feature set —
no static feature, single or shape-based, separates the score-7 winners from losers.

## Artifacts (new files, this branch)

- `scripts/feature_panel_shape.py` — 11 multi-TF SHAPE features (as-of, no look-ahead).
- `scripts/test_372_shape_asof.py` — no-look-ahead unit test (append-wild-future, assert unchanged).
- `scripts/run_372_shape.py` — the grader (per-feature Q1∧Q3 gate + OOS-both-directions composite + CIBR/IGV sanity).
- `results/372_stage1_discrimination.md` — this report.

Reproduce: `cd /Users/falk/projects/kumo-qc-362 && python3 scripts/test_372_shape_asof.py && python3 scripts/run_372_shape.py`
