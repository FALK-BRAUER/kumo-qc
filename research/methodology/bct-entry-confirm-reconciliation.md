# BCT Entry-Confirmation Phase — Methodology Reconciliation (#253 Phase-1)

**Phase:** `src/phases/entry_selection/bct_entry_confirm/bct_entry_confirm.py` (pure scorer:
`evaluate_gate2`; `ComponentScore`).
**Methodology source:** the bible **`strategy/methodology.md` §2 (Components 1–4) + §4 (Gate 2)**
(fintrack repo, NOT kumo-qc). The cross-repo **authoritative** spec for this golden-master is the
GH#253 comment "AUTHORITATIVE §4 Gate 2 + §2 components (from methodology.md — the bible)", which
CORRECTS two errors in the original ticket summary (X/4 scoring; the 1.0× vs 1.5× volume gate).
**Scope:** the ENTRY-CONFIRMATION trigger (entry_selection). Gate-1 rule-compliance, Gate-4
resistance-proximity, and Gate-5 day-type order mechanics are OUT of scope (phase-2 variants).

---

## 0. Why this phase exists — the P&L unlock

#228 proved the SIGNAL/QUALIFY scorer already matches the methodology (golden-master, scorer
byte-unchanged). So the champion's **−0.616 Sharpe is NOT a broken scorer** — a qualified name is
bought BLIND at next open with no entry trigger. The bible (§2/§4 Gate 2) defines an ENTRY trigger
the engine never implemented. This phase IS that trigger: it GATES the qualified+ranked candidates
so a name FIRES only on a CONFIRMED entry.

---

## 1. Component ↔ code mapping (the 4 §2 components, §4 Gate-2 scoring)

Each component maps to a boolean in `evaluate_gate2` (a PURE float-in scorer — no QC objects —
so the golden-master is a unit test). The phase's `_score_candidate` reads the maintained
`qc._indicators[sym]` suite and calls `evaluate_gate2`.

**HQ #253-P1 ruling applied — C2 reads the latest DAILY OHLC bar** (from the `TBounceTracker`,
fed by the daily consolidator), NOT the live close-snapshot. The old close-snapshot C2 was the
correctness bug; this is the fix.

| # | Methodology (§2 component) | Coded condition (`evaluate_gate2`) |
|---|---|---|
| **C1 Regime** | live price above cloud AND Tenkan > Kijun → BULL | `price > d_cloud_top AND d_tenkan > d_kijun` |
| **C2 T-Bounce** (daily OHLC) | (a) was above Tenkan; (b) PULLBACK = daily LOW touched/penetrated Tenkan OR within ≤tol ABOVE (a CEILING); (c) BOUNCE = bullish close OR lower-wick rejection; (d) T > K; (e) NOT inside cloud. Degrade if below-Tenkan >3 sessions / Tenkan flat (\|T/K−1\|≤flat_eps OR T<K) / gap-up (open vs prior close > thr) | `was_above(sessions<=3) AND pullback(daily_low<=tenkan OR (daily_low−tenkan)/tenkan<=tol) AND bounce(daily_close>daily_open OR lower_wick>=0.5*range) AND t_over_k AND not_in_cloud AND not tenkan_flat AND not (gap_up_frac>gap_up_threshold)` |
| **C3 MACD** | 12/26/9 daily (frozen-canonical): **hist ≥ 0 (positive OR FLAT)** = confirm; negative-turning-up = confirm (divergence); **only negative-turning-down/flat = NO** (flat is a SIZING nuance, not a gate fail) | `hist>=0 → confirm; elif hist[0]>hist[1] (turning up) → confirm; else → NO` |
| **C4 Volume** | entry candle volume ≥ **1.0×** 20-day avg (the GATE; 1.5× is the full-SIZE tier, NOT the gate) | `volume >= volume_gate_mult * vol_avg20` (default mult = 1.0) |

**Gate-2 SCORING (NOT binary):** `score = C1+C2+C3+C4` ∈ 0..4. **Qualify rule** =
`score >= min_confirm (default 2) AND C1 (regime) AND C4 (volume)` — regime + volume are
**MANDATORY** (a 2/4 missing either is DO-NOT-ENTER, per the GH#253 "only if regime + volume both
pass"). The bible's size tiers (4/4 full · 3/4 75% · 2/4 50%) are emitted as the X/4 score on
`qc._entry_confirm[ticker]` for a downstream methodology sizer; phase-1's baseline sizer
(`flat_pct_heatcap`) ignores it — the **GATE** is the phase-1 behavioral effect.

## 2. Parameter surface

| Param | Default | Role | Swept (`space()`)? |
|---|---|---|---|
| `macd_fast` | 12 | MACD fast EMA | **NO** — frozen canonical (§2 "NOT per-ticker optimized") |
| `macd_slow` | 26 | MACD slow EMA | **NO** — frozen canonical |
| `macd_signal` | 9 | MACD signal-line EMA | **NO** — frozen canonical (#253-P1: dropped the INERT sweep) |
| `volume_gate_mult` | 1.0 | C4 gate multiple | yes `(1.0,1.25,1.5)` |
| `tenkan_pullback_tol` | 0.005 | C2(b) pullback CEILING above Tenkan | yes `(0.003,0.005,0.008)` |
| `flat_eps` | 0.002 | C2 Tenkan-flat degrade band (\|T/K−1\|≤eps) | yes `(0.001,0.002,0.005)` |
| `gap_up_threshold` | 0.01 | C2 gap-up degrade (open vs prior close >) | yes `(0.005,0.01,0.02)` |
| `min_confirm` | 2 | X/4 qualify floor | yes `(2,3,4)` |
| `enabled` | True | wiring toggle | NO |

Sweep grid = 3⁵ = **243**. `COMPLEXITY = ComplexityDecl(free_params=5)`, kept in lockstep with
`space()` by `ComplexityDecl.validate` (no hidden knobs). **Judgment calls:** (a) FROZE all three
MACD periods (§2 forbids per-ticker MACD opt); (b) **DROPPED `macd_signal` from the sweep** — the
#214 reviewer caught it was INERT (the MACD indicator is built 12/26/9 in lean_entry and the phase
never read `Params.macd_signal`), so sweeping it burned 3× budget for a no-op; (c) `flat_eps` +
`gap_up_threshold` are now first-class swept axes (the degrade thresholds the methodology defines).

## 3. CANONICAL-SOURCE FLAGS — RULED by HQ (#253-P1)

The 5 flags raised in the first cut are now **RULED** (recorded here; the uncertainty is removed).
The C2 correctness fix (read the DAILY OHLC bar, not the close-snapshot) is applied across all five.

1. **FLAG 1 — C2(b) pullback is a CEILING, not a floor-band.** C2(b) fires if the daily **LOW** ≤
   Tenkan (touched/penetrated) **OR** the low sits within ≤ `tenkan_pullback_tol` ABOVE Tenkan:
   `daily_low <= tenkan OR (daily_low − tenkan)/tenkan <= tol`. A closer/deeper touch is BETTER,
   never rejected. Default 0.5%, kept as a `space()` axis.
2. **FLAG 2 — C2 "Tenkan flattened" = T≈K proximity.** Degrade (don't count C2) if
   `|tenkan/kijun − 1| <= flat_eps` (default 0.2%) **OR** `tenkan < kijun`. `flat_eps` is a new
   `.Params` field + `space()` axis (replaces the old `tenkan_pullback_tol`-reuse for flatness).
3. **FLAG 3 — C3 "flat" is a SIZING nuance, NOT a gate fail.** C3 confirms if `hist >= 0`
   (positive **OR flat** both count) OR (`hist < 0 AND Δhist > 0`, divergence). C3 fails ONLY if
   `hist < 0 AND Δhist <= 0` (negative turning down/flat). The old code wrongly failed positive-flat
   / zero-flat — fixed.
4. **FLAG 4 — sessions + gap.** `sessions_below_tenkan > 3` = downtrend (don't count). Gap-up
   degrade = today's `open` vs the PRIOR daily `close` > `gap_up_threshold` (default **1%**, NOT
   5%). `gap_up_threshold` is a `space()` axis.
5. **FLAG 5 — C2(c) literal daily-candle bounce.** Bullish close (`close > open`) OR lower-wick
   rejection (`lower_wick >= 0.5*candle_range`, where `lower_wick = min(open,close) − low`,
   `candle_range = high − low`, guard `range > 0`). Replaces the old `price >= tenkan` close proxy.

**Data plumbing for the C2 daily-OHLC read:** `runtime/indicators.py::TBounceTracker` now stores
`last_open/high/low/close` (fed each completed daily bar by the `daily_consolidator` in
`lean_entry._register_indicators`) plus `sessions_below_tenkan` + `gap_up_frac` (open vs PRIOR
close). The phase declines a candidate with no daily bar yet (`last_close is None`). Unit-tested in
`tests/runtime/test_indicators.py`.

## 4. Golden-master (the methodology anchor)

`tests/phases/entry_selection/bct_entry_confirm/test_entry_confirm_golden_master.py` — hand-spec
float fixtures at price=100, each margin set so toggling one input flips one component. Asserts the
exact per-component pass/fail AND the X/4 count.

| Fixture | Encodes | Asserted |
|---|---|---|
| `test_golden_4_of_4_all_confirm` | all 4 components true | `(T,T,T,T)`, score 4, qualifies at 2 and 4 |
| `test_golden_each_component_failed_is_3` (×3) | isolate C2 / C3 / C4 single-flip | that flag False, score 3 |
| `test_golden_c1_regime_fail_couples_c2` | C1's T>K leg is SHARED with C2 (documented coupling) | C1=F, C2=F, score 2 |
| `test_golden_c2_subconditions` (×7) | each of the 5 ANDed C2 sub-clauses + 2 degrade guards | C2 False |
| `test_golden_c2_boundary_near_tenkan_exact_tol` | pullback exactly at the 0.5% edge | C2 True (inclusive) |
| `test_golden_c3_macd_states` (×6) | the §2 MACD table (pos+up/pos+flat/neg+up/neg+down/neg-flat/zero) | only pos OR neg-turning-up confirm |
| `test_golden_c4_volume_gate_boundary_inclusive` | gate at exactly 1.0× | inclusive PASS; 1.5× also passes |
| `test_golden_c4_custom_gate_multiple` | 1.5× gate | 1.0× volume fails, 1.5× passes |
| `test_golden_qualify_2of4_with_mandatory_passes` | C1+C4 pass, C2+C3 fail | qualifies at min=2, not min=3 |
| `test_golden_qualify_2of4_missing_regime_is_do_not_enter` | 2/4 missing regime | DO NOT ENTER |
| `test_golden_qualify_missing_volume_is_do_not_enter` | 3/4 missing volume | DO NOT ENTER |
| `test_golden_determinism` | same inputs ×50 | identical |

**Result: all pass.** Golden-master discipline: these assert LOGIC CORRECTNESS on identical
hand-computed inputs (the coded components == the §2 components), NOT champion-number matching. If
this file ever fails, the gate DIVERGED from the methodology — STOP + FLAG for HQ; do NOT edit the
scorer to make it pass.

## 5. The maintained-indicator additions (single code path)

The phase reads `qc._indicators[sym]` O(1)/candidate (NO per-bar history — the isolator-timeout
rule). #253 ADDED to the indicator contract (`runtime/indicators.py::INDICATOR_KEYS`,
`runtime/lean_entry.py::_register_indicators`): `macd` (MACD 12/26/9 EXPONENTIAL), `macd_hist_window`
(RollingWindow[2] of the histogram → C3 turning), `vol_sma20` (SMA(20) of VOLUME → C4),
`tbounce` (the pure `TBounceTracker` — sessions-below-Tenkan + gap-up, fed by a daily
consolidator → C2 degrade), `daily_consolidator`. **ADDITIVE — the signal/exit phases do NOT read
these, so champion-asis scoring/sizing/exit is byte-unchanged (its config_hash `e573e84b1ce1` is
intact; parity preserved).** `TBounceTracker` is unit-tested in `tests/runtime/test_indicators.py`.

## 6. Provenance

- `version_marker`: `bct_entry_confirm_v1`.
- Measurement config `strategies/champion_entry.py` (NEW): champion-asis stack VERBATIM + this
  phase + `MarketOnOpenEntry`. Its OWN config_hash **`1b665ab98f13`** (distinct from champion-asis
  `e573e84b1ce1`). dist rebuilt for champion-entry. champion-asis UNCHANGED.
