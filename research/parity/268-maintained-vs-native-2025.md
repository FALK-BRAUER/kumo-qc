# #268 LOCAL diagnostic — maintained-vs-NATIVE weekly Ichimoku (seed-overlap localization)

**Status:** LOCALIZED (local side; cloud capture lands separately). The seed-overlap hypothesis
is **RULED OUT for the #265 probe names** — the engine's maintained weekly Ichimoku VALUES are
**bit-identical** to a clean native warm for every probe (DRI/CME/AMZN/COST/CRWD/KGC), because
all of them are auto-warmed during the 560-day warmup, never `_seed_weekly`-seeded. The
seed-overlap defect IS real and CAN be material — but only for a **post-warmup mid-FY entrant**,
which none of the #265 names are. **The #265 signal divergence is therefore NOT explained by
seed-overlap; the next #268 fix must look elsewhere (root-cause candidate (c)/(d), below).**

This is a fully-LOCAL route (the night-charter fallback). Cloud capture (cloud-indicators-243.json)
is the other half of the cloud-vs-local diff; this doc covers the local side + the maintained-vs-
native correctness check. RAW conformed daily zips only; every number traces to a real artifact.

## Provenance / artifacts (every number traces to one)
| Item | Path |
|---|---|
| Local full-FY BT (extended ChartEmit) | `algorithm/v2_champion_asis/backtests/2026-05-31_23-36-54/1158674033.json` |
| PART 1 local-indicators capture | `research/parity/artifacts/local-indicators-243.json` |
| PART 2 maintained-vs-native diff | `research/parity/artifacts/diag-268-maintained-vs-native.json` |
| PART 2 diagnostic script | `scripts/diag_268_maintained_vs_native.py` |
| PART 1 extractor script | `scripts/extract_local_indicators_243.py` |
| Tests | `tests/parity/test_diag_268_maintained_vs_native.py` (3 green) |
| RAW daily | `data/equity/usa/daily/{dri,cme,amzn,cost,crwd,kgc}.zip` (deci-cents/10000) |

Engine source read first: `src/runtime/lean_entry.py` (`_seed_weekly`/`_seed_daily`/
`_register_indicators` + the `Calendar.WEEKLY` consolidator wiring), `src/runtime/indicators.py`
(`weekly_aggregate`/`weekly_friday`), `src/phases/shared/oracle_helpers.py` (`score_symbol_native`,
the 8 conditions).

---

## PART 1 — LOCAL chart capture (the local side of the cloud-vs-local diff)

The extended ChartEmit phase records the SAME `self.plot` series locally that it will on cloud.
LEAN wrote them to the local BT result `Charts` section; `scripts/extract_local_indicators_243.py`
pulls them into `research/parity/artifacts/local-indicators-243.json` in the SAME shape the cloud
capture (`cloud-indicators-243.json`) will land, so #268's cloud-vs-local diff is a key-by-key
compare. All 11 series captured, 497 FY2025 points each:

- `Regime/spy_close`, `Regime/spy_ma200` (the SPY-MA200 regime cross)
- `Signal/n_qualifying` (daily count scoring ≥ min_score)
- `Score/{DRI,CME,AMZN,COST,CRWD,KGC}` (per-name maintained-indicator BCT score; `-1.0` = not selectable)
- `Universe/active_set`, `Universe/ranked`

**Local trio (inert-emit confirm):** **Sharpe −0.139 / +3.620% net / 14.8% DD / 244 orders** —
**identical to the #265 baseline** (`residual-root-cause-2025.md`). The ChartEmit extension is
confirmed INERT (charting-only, config_hash unchanged). Local side is ready; the cloud-vs-local
diff completes when the cloud capture lands.

Notable from the local Score chart (informs PART 3): every probe DOES cross score ≥ 7 locally on
many FY days (CRWD 198, KGC 361, CME 157, AMZN 110, COST 64, DRI 41) — yet #265 found local never
*traded* them. So local's maintained scorer is NOT failing to reach 7; the divergence is in WHICH
days it reaches 7 (vs cloud) and/or the regime/entry gating — not a dead indicator.

---

## PART 2 — maintained-vs-NATIVE recompute (the seed-overlap hypothesis test)

Two weekly-Ichimoku(9,26,26,52,26,26) warm paths, replicated in pure Python over the IDENTICAL
RAW daily zips (LEAN-faithful math; unit-pinned exact-equal to the `oracle_helpers._mid`+`.shift(26)`
reference — `test_ichimoku_math_matches_oracle_reference`):

- **NATIVE/CLEAN** = ONE clean `weekly_aggregate` (W-FRI) into a fresh Ichimoku — what cloud's
  continuous `set_warmup` feed approximates (no seed/consolidator split, no partial-week double-count).
- **MAINTAINED** = `_seed_weekly` (WARMUP_DAYS=560 history → `weekly_aggregate`, Monday-timestamped;
  its LAST bucket is the PARTIAL current week) + the live `Calendar.WEEKLY` consolidator. The
  load-bearing detail: when the current week completes, the consolidator re-emits the FULL Mon..Fri
  bar at the SAME Monday timestamp the seed used for its partial bar → `IchimokuKinkoHyo` is
  **forward-only** → the re-emit is **REJECTED** → the indicator keeps the seed's **partial-week**
  value. (Pinned by `test_seed_overlap_retains_partial_week`.)

### Result 1 — REALISTIC path: ZERO diff for all 6 probes (seed-overlap RULED OUT for #265 names)

| Probe | data starts | predates warmup-start (2023-06-21)? | realistic maintained-vs-native diff |
|---|---|---|---|
| DRI | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |
| CME | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |
| AMZN | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |
| COST | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |
| CRWD | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |
| KGC | 2021-05-12 | yes | **0/53 weeks, max abs 0.000** |

Every #265 probe has daily history reaching back to 2021-05-12 — well before warmup-start
(2023-06-21) — and clears the floors (close≥$10, trailing-20d-mean-DV≥$100M) on every day, so it
is in the WARMUP universe. QC auto-warms the subscribed weekly consolidator over the 560-day
warmup, and the `if not self.is_warming_up` guard in `_register_indicators` **skips `_seed_weekly`**.
The maintained w_ichi for these names is therefore built by the SAME continuous live consolidator
the native path models → **maintained == native, bit-identical, zero divergence**. The score
chart's `first_active` (e.g. DRI 2025-06-09) reflects indicator-readiness *day*, NOT a mid-FY
subscription — it is not seeding.

**Conclusion: the seed-overlap double-count does NOT touch the #265 probe names. Hypothesis (a)
is ruled out for the trade divergence.**

### Result 2 — FORCED mid-week seed: the defect is REAL and CAN be material (for a true mid-FY entrant)

To quantify the defect *magnitude* (does it cross the score=7 threshold if a name WERE seeded
mid-week?), the diagnostic forces a Wednesday seed (2025-03-12) per probe and diffs the resulting
maintained sequence against native:

| Probe | weeks differing | max abs tenkan | max abs senkou_a | worst week (line) | maint vs native | rel |
|---|---|---|---|---|---|---|
| **COST** | 9/46 | **$14.18** | $7.09 | 2025-03-14 (w_close) | 929.86 vs 903.57 | **2.83%** |
| **DRI** | 25/46 | $2.24 | $1.12 | 2025-03-14 (w_close) | 189.34 vs 185.98 | 1.78% |
| CRWD | 2/46 | 0.00 | 0.00 | (senkou_b) | — | 0.30% |
| CME / AMZN / KGC | 1/46 | 0.00 | 0.00 | — | — | ~0% |

The forward-only-frozen PARTIAL week (Mon..Wed close instead of Mon..Fri) propagates into the
9-period tenkan and the senkou lines for several subsequent weeks. On COST the tenkan diverges by
$14.18 (1.5%) and the weekly close by 2.8% — **large enough to flip score conditions 1/2/5/6**
(price-vs-cloud, tenkan>kijun, price-vs-tenkan) for a name that *were* a post-warmup entrant.

**So the seed-overlap is an absolute-correctness bug that is MATERIAL in principle — but it does
not fire on the #265 names (Result 1), so it does not explain the #265 trade divergence.** It
should still be fixed (it will bite genuine mid-FY entrants and amplifying variants), and it runs
on the single code path (local==cloud) so it likely **cancels** in a local-vs-cloud diff anyway.

### Result 3 — weekly-bar-count check: NO off-by-one (the 78-week pole)

Does WARMUP_DAYS(560) + the weekly seed produce the same number of *completed* weekly bars at
FY-start as a clean warm, and does it clear the 78-bar Ichimoku readiness pole?

| | completed weeks pre-FY | clears 78-week pole |
|---|---|---|
| NATIVE (full history → W-FRI) | **190** | yes |
| SEED window (560d → W-FRI) | **80** | yes |

Both clear the 78-week pole with margin; there is **no off-by-one** that would shift the entire
SenkouA/B (the 26-delay) at FY-start. The seed window naturally holds fewer *total* weeks (80 vs
190) because it only spans 560 days vs full history — but the readiness pole is met identically, so
the FY-start Ichimoku alignment is sound. **Hypothesis (b) is ruled out.**

---

## PART 3 — localization (NO fix this step)

Root-cause candidates and the evidence:

- **(a) seed-overlap double-count (the hypothesis)** — **RULED OUT for the #265 trade divergence.**
  Zero maintained-vs-native diff on all 6 probes (Result 1); they are auto-warmed, never seeded.
  The defect is real and material *in principle* (Result 2: COST tenkan $14.18 / w_close 2.8% under
  a forced mid-week seed) but fires only on post-warmup mid-FY entrants — not these names — and runs
  on the single code path so it likely cancels local-vs-cloud. Fix it for correctness/amplifiers,
  but it is **not** the #265 cause.
- **(b) weekly bar-count / alignment off-by-one** — **RULED OUT.** Both warms clear the 78-week
  pole (native 190, seed 80 completed pre-FY); no count-driven SenkouA/B shift (Result 3).
- **(c) the conformed-daily-vs-native RAW bar SET feeding the indicators** — **the surviving local
  candidate.** Even with matching close *prices* (#173/#265 ruled out normalization), if local's
  conformed daily bar SET differs from cloud's native set (a different/missing session, a different
  OHLC on a given day, a holiday-orphan row) the W-FRI weekly buckets differ → different weekly
  Ichimoku → different score days. This diagnostic held the bar set CONSTANT (same zip on both
  sides), so it could not surface a local-vs-cloud bar-set delta — that requires the cloud capture.
  The local Score chart confirms the scorer reaches ≥7 on many days (it is alive), so the residual
  is *which* days, consistent with a bar-set/bucket difference rather than a dead/seed-broken indicator.
- **(d) something else (regime-gate timing / entry-confirm gating)** — **the surviving cross-cutting
  candidate.** #265 already showed local regime-BLOCKs 42 FY days clustered Mar–May (SPY<MA200); if
  cloud's SPY MA200 cross differs, the blocked window differs and cloud enters names local gates out.
  The captured `Regime/spy_ma200` + `Signal/n_qualifying` series (PART 1) are exactly the diff inputs
  for this once the cloud capture lands.

**Bottom line for the #268 fix target:** the maintained-indicator *warm mechanism* (seed-overlap,
bar-count) is **sound for the #265 names** — both hypotheses (a) and (b) are ruled out with concrete
zero-diff evidence. The fix must target **(c) the conformed-vs-native daily bar SET** and/or **(d)
the SPY-MA200 regime-gate / entry-confirm timing** — both of which require the cloud-side capture
(`cloud-indicators-243.json`) to diff against this local capture. Separately, the seed-overlap defect
(Result 2) should be fixed for absolute correctness even though it does not drive #265.

## Honest caveats
- This is the LOCAL route only. The maintained-vs-native check used the SAME RAW zip for both warm
  paths, so it tests absolute-correctness of the warm *mechanism*, NOT a local-vs-cloud bar-set
  delta. The cloud-vs-local VALUE diff (the other half of #268) needs `cloud-indicators-243.json`.
- The pure-Python Ichimoku replicates LEAN's `IchimokuKinkoHyo` math (unit-pinned exact-equal to
  the oracle reference) and the forward-only rejection of the same-Monday re-emit; it does NOT run
  the real C# indicator (unavailable locally). The forced-seed magnitudes are from this faithful
  replica over real RAW data, not a live LEAN instrumented run.
- `data_starts=2021-05-12` for all probes is the on-disk zip start, not necessarily the listing
  date; it is sufficient to prove "history predates warmup-start 2023-06-21" → auto-warmed.
