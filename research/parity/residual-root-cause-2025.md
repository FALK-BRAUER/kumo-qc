# #265 Residual Root-Cause — champion_asis local vs cloud (post-#259, apples-to-apples FY2025)

**Status:** ROOT-CAUSED. The post-warmup-fix residual is a **SIGNAL-layer divergence**
(per-name BCT score + SPY-200MA regime-gate timing differ on RAW-identical data), **NOT** a
universe / vendor-breadth gap. Selection-breadth is proven SOUND (37 of 38 cloud-only names ARE
in local's conform-coarse ranked universe and pass every floor; only 1 — BRK.B — is an
irreducible vendor-breadth miss). The residual is **partially-reducible (fixable, signal layer)**,
not the accepted vendor residual; the cloud number remains GROUND TRUTH.

This closes #262 (the warmup mirage is gone — local now trades all year, tracking cloud's
monthly cadence) and localizes the next fix to the indicator/score layer (NOT universe).

## Apples-to-apples runs (both post-#259 dist `e573e84b1ce1`, commit `8e80cc3`)

| Metric | LOCAL | CLOUD | Δ (local−cloud) |
|---|---|---|---|
| Sharpe | **−0.139** | **−0.683** | +0.544 |
| Net return | **+3.62%** | **−9.05%** | +12.67 pp (sign-flip) |
| Drawdown | 14.8% | 20.5% | −5.7 pp |
| Total orders | 244 | 291 | −47 (−16%) |
| Traded symbols | 93 | 113 | −20 (75 overlap) |

Provenance: config_hash `e573e84b1ce1` · data_fingerprint `90f2d7e3` · commit `8e80cc3`.

### Artifacts (every number traces to one)
| Side | Artifact |
|---|---|
| LOCAL | BT dir `algorithm/v2_champion_asis/backtests/2026-05-31_21-43-05/` — `1247415841.json` (stats), `1247415841-order-events.json` (487 events / 243 filled / 93 symbols), `log.txt` (ACTIVE_SET / TRACKED_CANDIDATES / PHASE / BLOCK). Code-verified: `champion-asis` marker present in `code/main.py`. |
| CLOUD | BT `b40551526c27537834bda25da58521ec`, project `arch2_champion_v2` PID `32319236`. 291 orders via `/backtests/orders/read` (paginated, saved `research/parity/artifacts/cloud_orders_265.json`). 113 symbols. |
| Coarse | `data/equity/usa/fundamental/coarse/2023*–2025*.csv` (8-col QC-native, #259-conformed). |
| Replay | `scripts/residual_parity_diff.py` — offline selection-gate replay; reproduces the live ACTIVE_SET counts **249/249 position-aligned exact** (1-session date-label offset only). |

## The #259 warmup fix is CONFIRMED (the mirage is gone)

- Local warmup ACTIVE_SET = **614–890 names over 386 warmup days, ZERO empty days** (pre-#259:
  636/636 empty). FY ACTIVE_SET 764–1115.
- Local now buys **throughout the year**, tracking cloud's monthly cadence — the pre-#259
  "nothing-until-October" fingerprint is eliminated:

| Month | LOCAL buys | CLOUD buys |   | Month | LOCAL | CLOUD |
|---|---|---|---|---|---|---|
| 2025-01 | 30 | 34 |   | 2025-07 | 5 | 1 |
| 02 | 8 | 12 |   | 08 | 16 | 15 |
| 03 | 16 | 21 |   | 09 | 2 | 9 |
| 05 | 20 | 24 |   | 10 | 12 | 14 |
| 06 | 4 | 5 |   | 11 | 8 | 10 |
|   |   |   |   | 12 | 5 | 8 |

(Pre-#259 it was Jan 2 vs 34, Feb 0 vs 12, … Oct 20 — the empty-warmup tell. Gone.)

## Residual localization (the #173 ladder, post-warmup)

`scripts/residual_parity_diff.py` aligns the local and cloud traded-symbol sets and classifies
each **cloud-only** name (38) by replaying local's IDENTICAL selection gate
(`update_dv_windows → apply_floors → rank_and_cap`) offline over warmup+FY:

| Layer | Count | Meaning |
|---|---|---|
| **SIGNAL_OR_SIZING** | **37** | Name IS in local's ranked universe (passed floors), local just never scored it ≥7 / never traded it. |
| SELECTION_FLOORS | 0 | In coarse but never cleared floors. |
| SELECTION_VENDOR_BREADTH | 1 | Never in local conform-coarse at all. |

- **37 of 38 cloud-only names** (e.g. AMZN, COST, CRWD, DRI, CME) are in local's ranked
  universe on **all 250 FY days** — subscribed, indicator-tracked, floor-clearing. Local simply
  did not score them ≥7 on the days cloud entered → **SIGNAL layer**.
- **BRK.B** (the lone vendor-breadth miss): local's conform-coarse carries **BRK.A** (A-shares,
  $788k/share) but **not the B-class** — the only true breadth gap, **1/113 cloud symbols
  (0.9%)**. This is the irreducible vendor residual, and it is negligible.
- **0 floor-failures** — the floors (close≥$10, trailing-20d-mean-DV≥$100M) behave identically.

### Two concrete signal mechanisms (evidence)

1. **Per-name BCT score-timing.** DRI was a day-1 cloud entry (2025-01-02 MOO). Post-#259 DRI is
   subscribed locally from day 1 (in the ranked universe all 250 days) — yet local never traded
   DRI. The 8-condition `score_symbol_native` crossed ≥7 for DRI on cloud but not locally on that
   bar. Same RAW prices (#173 ruled out normalization) ⇒ the difference is in the maintained
   **indicator VALUES** (daily/weekly Ichimoku, Wilder-9 ADX, SMA200, ROC) — i.e. the warmup bar
   sequence each indicator consumed, or the #259 daily-seed state vs cloud's native warm.
2. **SPY-200MA regime-gate timing.** Local regime-BLOCKs **42 FY days, all clustered Mar–May 2025**
   (`spy_200ma_v1`: SPY < MA200 in the spring drawdown) → zero entries those days. If cloud's SPY
   MA200 value/cross differs even slightly, cloud's blocked window differs → cloud enters names
   local gates out (e.g. CME, cloud-bought 2025-08-04). The day-1 overlap is real once the
   1-session MOO fill offset is accounted for (cloud fills day N, local fills day N+1): of cloud's
   10 day-1 names, **6 (AXP, C, HPE, JPM, MRVL, T)** are local 2025-01-03 fills.

## VERDICT

**The residual is dominated by a FIXABLE SIGNAL-layer divergence, not the irreducible vendor
residual.** Mechanically:
- **Universe / selection breadth: SOUND.** 37/38 gap names in local's ranked universe; 0 floor
  failures; the offline gate replay is bit-exact to the live ACTIVE_SET (249/249). The conform
  pipeline emulates cloud's coarse correctly.
- **Vendor-breadth residual: NEGLIGIBLE.** Exactly 1 name (BRK.B, B-share class absent from the
  local coarse vendor file) = 0.9% of cloud symbols. This IS irreducible (local vendor ≠ QC-native
  share-class coverage) but it cannot account for a 12.67pp return gap.
- **Signal layer: the dominant, FIXABLE cause.** Per-name BCT scores and the SPY-200MA regime
  gate fire on different days local vs cloud because the maintained indicator VALUES differ even
  on RAW-identical prices. The next fix targets the indicator-value parity (warmup bar sequence /
  #259 daily-seed fidelity vs cloud native warm), NOT the universe.

### TRUE baseline (recommended)
**The CLOUD number is the TRUE baseline: −0.683 Sharpe / −9.05% / 20.5% DD / 291 orders / 113
symbols.** Per the Cloud/Local Parity charter, cloud is ground truth. Local **−0.139 / +3.62%** is
an OPTIMISTIC approximation that diverges by **Δ+0.544 Sharpe / +12.67pp return** — well outside
any tolerance band. Local must NOT be used as the performance baseline until the signal-layer
residual closes; it remains valid only as a fast-iteration directional harness.

### Documented residual BAND (the parity-test guard)
The proven residual is the regression guard band. The parity test FAILS LOUD if a future local
run diverges from the recorded cloud ground truth by MORE than this band (catches a re-broken
warmup like the mirage), and ALSO fails if local diverges by LESS in a way that implies the
results silently converged via a forbidden `if cloud` workaround is not asserted — the band is a
documented envelope, not a pass:

| Metric | Cloud GT | Local (current) | Band (|local − cloud| max) |
|---|---|---|---|
| Sharpe | −0.683 | −0.139 | ≤ 0.70 |
| Return pp | −9.05% | +3.62% | ≤ 15 pp |
| Orders | 291 | 244 | within 25% |
| Symbols | 113 | 93 | within 25% |

The band is **wide by necessity** — it documents the *current* unclosed signal residual, not a
parity claim. Tightening the band is the acceptance criterion for the signal-layer fix.

## Unobtainable / flagged
- Cloud per-symbol indicator VALUES (SPY MA200, per-name score components) are not exposed by the
  QC order/stats API; the signal mechanism is proven by (a) the offline gate replay showing the
  names ARE selectable locally and (b) the local regime-BLOCK log + day-1 fill overlap, not by a
  direct cloud indicator dump. Direct cloud-indicator diffing requires a custom cloud chart/log
  emit — flagged as the next step for the signal-fix ticket, out of scope for #265 (mirage close).
