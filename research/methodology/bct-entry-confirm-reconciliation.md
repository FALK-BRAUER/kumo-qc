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

| # | Methodology (§2 component) | Coded condition (`evaluate_gate2`) |
|---|---|---|
| **C1 Regime** | price above cloud AND Tenkan > Kijun → BULL | `price > d_cloud_top AND d_tenkan > d_kijun` |
| **C2 T-Bounce** | (a) was above Tenkan; (b) pullback within 0.3–0.5% of Tenkan; (c) bounced (lower wick / bullish close); (d) T > K; (e) NOT inside cloud. Degrade → don't count if below-Tenkan >3 sessions / Tenkan flattened / first test after large gap-up (Rule #10) | `was_above(sessions_below_tenkan<=3) AND near_tenkan(|price/tenkan−1|<=tol) AND bounced(price>=tenkan) AND t_over_k AND not_in_cloud(not cloud_bottom<=price<=cloud_top) AND not tenkan_flat AND not large_gap_up` |
| **C3 MACD** | 12/26/9 daily (NOT per-ticker optimized): hist positive+turning-up = full; positive-flat = valid; negative-turning-up = half (divergence); **negative-turning-down = NO** | `hist>0 → confirm; elif hist[0]>hist[1] (turning up) → confirm; else → NO` |
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
| `macd_fast` | 12 | MACD fast EMA | **NO** — canonical (§2 "NOT per-ticker optimized") |
| `macd_slow` | 26 | MACD slow EMA | **NO** — canonical |
| `macd_signal` | 9 | MACD signal-line EMA | yes `(8,9,12)` |
| `volume_gate_mult` | 1.0 | C4 gate multiple | yes `(1.0,1.25,1.5)` |
| `tenkan_pullback_tol` | 0.005 | C2 pullback band | yes `(0.003,0.005,0.008)` |
| `gap_up_threshold` | 0.05 | C2 large-gap-up degrade | not swept (degrade guard, not a strategy axis) |
| `min_confirm` | 2 | X/4 qualify floor | yes `(2,3,4)` |
| `enabled` | True | wiring toggle | NO |

Sweep grid = 3×3×3×3 = **81**. `COMPLEXITY = ComplexityDecl(free_params=4)`, kept in lockstep
with `space()` by `ComplexityDecl.validate` (no hidden knobs). **Judgment call — the swept axes:**
chose the 4 genuinely-tunable confirmation thresholds; deliberately FROZE `macd_fast`/`macd_slow`
because §2 forbids per-ticker MACD optimization (sweeping the MACD periods would BE that).

## 3. CANONICAL-SOURCE FLAGS (for HQ — could not byte-confirm vs the bible from this repo)

Implemented to the GH#253 authoritative comment + standard defs; the following nuances need HQ's
canonical §4 Gate-2 ruling (built to a defensible default + FLAGGED, did NOT invent a bespoke rule):

1. **C2 pullback band — `0.3–0.5%` is a RANGE or a CEILING?** §2 says "within 0.3–0.5% of
   Tenkan". Implemented as a single symmetric `<= tenkan_pullback_tol` band (default 0.5% = the
   upper edge). If the bible means "reject pullbacks CLOSER than 0.3%" (a band floor), C2 needs a
   two-sided test. **FLAGGED.**
2. **C2 "Tenkan flattened (~Kijun)" epsilon.** "~Kijun" needs a numeric tolerance; used Tenkan
   within `tenkan_pullback_tol` of Kijun as the flat proxy. **FLAGGED** (the bible may define a
   slope-based flatness, not a T≈K proximity).
3. **C3 turning-up/down/flat thresholds.** Used strict `hist[0] vs hist[1]` sign-of-delta (flat =
   exactly equal). The bible's "flat" may carry a tolerance band. **FLAGGED.** Also: negative-flat
   and zero-flat are treated as NO (only positive OR negative-turning-up confirm).
4. **C2 "large gap-up (Rule #10)" magnitude + "below Tenkan >3 sessions" count.** Used the
   methodology-stated `>3` sessions and a `gap_up_threshold` (default 5%) for the degrade. The
   exact Rule #10 gap magnitude is **FLAGGED.**
5. **C2 "bounced (lower wick OR bullish close)".** Implemented as `price >= tenkan` (a reclaim of
   the line) since the maintained suite exposes the live price, not the intraday wick. A
   wick-based test would need the daily bar's low/open/close — available via the daily
   consolidator if HQ wants the literal wick rule. **FLAGGED.**

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
