# BCT Signal Phase — Methodology Reconciliation (#228)

**Phase:** `src/phases/signal/bct_score_full/bct_score_full.py` (scorer:
`src/phases/shared/oracle_helpers.py::score_symbol_native`)
**Methodology source:** the in-project canonical **BCT Signal Stack** — the 8-condition Blue
Flag checklist in `CLAUDE.md`.
**Scope:** the SIGNAL / QUALIFY phase only — *"does the name qualify"*. Entry TIMING
(T-Bounce / MACD / volume confluence) is a SEPARATE downstream `entry_timing` phase and is
explicitly out of scope here (see Divergence §4).

---

## 1. Component ↔ condition mapping (the 8 BCT Blue Flag conditions)

Each methodology condition maps 1:1 to a coded boolean in `score_symbol_native` (the
maintained-indicator scorer; `algorithm` is the QC algo, `ind` the maintained-indicator dict).
Line refs are into `oracle_helpers.py` as of this commit.

| # | Methodology (CLAUDE.md BCT Signal Stack) | Coded condition (`score_symbol_native`) | Line |
|---|---|---|---|
| C1 | Weekly price above cloud (Span A) | `d_price > w_cloud_top` where `w_cloud_top = max(w_ichi.senkou_a, w_ichi.senkou_b)` | L174 |
| C2 | Weekly Tenkan > Kijun | `w_ichi.tenkan > w_ichi.kijun` | L175 |
| C3 | Weekly Chikou > price 26 bars ago | `w_close[0] > w_close[26]` (completed-week close-vs-close) | L176 |
| C4 | Weekly cloud GREEN (Span A > Span B) | `w_ichi.senkou_a > w_ichi.senkou_b` | L177 |
| C5 | Daily price above cloud | `d_price > d_cloud_top` where `d_cloud_top = max(d_ichi.senkou_a, d_ichi.senkou_b)` | L178 |
| C6 | Daily price above Tenkan | `d_price > d_ichi.tenkan` | L179 |
| C7 | ADX rising + +DI > −DI + ADX ≥ 20 (period 9, Wilder's EWM) | `adx_window[0] > adx_window[3]` AND `+DI > −DI` AND `adx ≥ 20` | L180 |
| C8 | Price above 200-day MA | `d_price > sma200` | L181 |

**Rating bands** (`score = sum(conditions)`; L184-188): `8 → "+++"`, `6-7 → "++"`,
`4-5 → "+"`, `2-3 → "="`, `0-1 → "--"`. Methodology states `+++ = 8/8`, `++ = 6-7/8`,
`+ = 4-5/8` — **matches exactly**; the scorer additionally distinguishes the lower bands
(`=`, `--`) which are below the qualify threshold and never enter (informational only).

### Intentional, fintrack-ruled asymmetry (NOT a divergence — documented canonical)
- **Price-vs-structure conditions (C1, C5, C6, C8) use the LIVE current price** (`d_price =
  securities[symbol].price`), not a stale bar close. C1 (a *weekly* condition) therefore
  compares the **live** price to the **completed-week** cloud — by design.
- **C3 Chikou is a CLOSE-based lagging line** → completed-week close-vs-close
  (`w_close[0] > w_close[26]`), with an inherent ≤1-week lag, which avoids the partial-week
  look-ahead the history-path resample had.
- Weekly cloud (C1/C4) reads the **completed-week** `w_ichi`.
These are stated verbatim in the `score_symbol_native` docstring (L136-143) and are the
maintained-indicator (history-free) re-expression of the legacy `score_symbol` — proven
equivalent on identical values by the condition-logic tests.

## 2. Parameter surface

| Param | Default (champion) | Role | Sweep axis (`Params.space()`) |
|---|---|---|---|
| `min_score` | `7` | qualify threshold — a name FIRES only if `score ≥ min_score` | `(6, 7, 8)` |
| `parabolic_threshold` | `0.25` | overextension block — skip if maintained 13-day ROC `> threshold` | `(0.20, 0.25, 0.30, 0.35)` |
| `enabled` | `True` | wiring toggle — **not** a strategy axis (excluded from `space()`) | — |

Sweep grid cardinality = `3 × 4 = 12`. Free-param count (overfitting penalty) = `2`
(`COMPLEXITY = ComplexityDecl(free_params=2)`), kept in lockstep with `space()` axes by
`ComplexityDecl.validate` (no hidden knobs).

## 3. Explicit FIRE vs DECLINE conditions

The phase `evaluate()` (`bct_score_full.py`) decides, per candidate, FIRE (emit a sized-order
stub) vs DECLINE (skip), in this order:

**FIRE** ⇔ ALL of:
1. candidate resolves to an active, subscribed symbol (`active_by_value`), AND
2. NOT already invested (`not portfolio[symbol].invested`), AND
3. NO open order for the symbol (`not transactions.get_open_orders(symbol)`), AND
4. maintained indicators present (`_indicators[symbol] is not None`), AND
5. passes the pre-filter (price `> 0`, price `≥ sma200`, price `≥ daily cloud top` — the C5/C8
   short-circuit that bounds work; mirrors oracle L538-551), AND
6. `score_symbol_native(...).score ≥ min_score`, AND
7. NOT parabolic (`roc13` not-ready OR `roc13 ≤ parabolic_threshold`).

**DECLINE** ⇔ ANY of: not active / invested / open-order pending / no indicators / fails
pre-filter / `score < min_score` / parabolic (`roc13 > parabolic_threshold`).

Surviving FIRE candidates are sorted `(score DESC, dollar_volume DESC)` (entry-priority
tiebreak; the dedicated ranking phase #230 is downstream) and emitted as `OrderIntent` stubs
(`qty=0` — the sizing phase sets quantity).

## 4. Scope verdict (ADR D1) + divergence flag

**Verdict: RECONCILE-EXISTING.** `bct_score_full` IS the canonical BCT qualify-scorer. The
8-condition stack, the rating bands, and the qualify threshold map 1:1 to the in-project
methodology (the CLAUDE.md BCT Signal Stack). No methodology qualify-component is absent from
the coded carve, and no coded condition is foreign to the methodology. Action taken:
validate + golden-master + add the template patterns (`space()` / `COMPLEXITY` / catalog).
**No scorer logic was changed** (oracle_helpers is DO-NOT-MODIFY, champion-parity gated); the
config-hash is unchanged (`e573e84b1ce1`), proving scoring behavior is identical.

**Divergence FLAGGED for HQ (the bible vs the in-project methodology — a known open item).**
Issue #228's history records that the original 8-condition stack was golden-mastered to the
ORACLE, and that George's full methodology *bible* (`strategy/methodology.md`, which lives in
the **fintrack** repo, NOT kumo-qc) frames the SIGNAL differently: the 8-condition Ichimoku
rating is the **SCANNER** (Component 1 / the +++…--- watchlist), and the bible additionally
specifies a downstream **ENTRY trigger** (Component 2 T-Bounce, Component 3 MACD 12/26/9
confluence, Component 4 volume ≥1.5× 20-day avg) that the engine does not yet have.

Reconciling that against this ticket's LOCKED SCOPE:
- The T-Bounce / MACD / volume confluence is **entry TIMING, not qualify** — it is a *different
  algorithm* applied at a *different stage* (entry-timing), NOT a flag-branch of this scorer.
  Per ADR D1 that is a **NEW SIBLING phase** (`entry_timing` kind), a SEPARATE later ticket
  (#230-adjacent), **not** a modification of `bct_score_full`. This is consistent with the
  current champion entering on regime/qualify alone (no trigger).
- Conversely the bible's framing does not emphasize ADX/200MA, which the coded scanner uses;
  these are part of the proven in-project scanner and stay.

**Net:** within the qualify lane, the coded scorer and the methodology agree (reconcile-
existing, golden-mastered below). The bible's entry-trigger components are a recognized GAP to
be built as a sibling `entry_timing` phase — flagged here for HQ, out of scope for #228.

## 5. Reference fixtures (the methodology golden-master)

Encoded in `tests/phases/signal/bct_score_full/test_methodology_golden_master.py`. All
fixtures are hand-specified maintained-indicator states at LIVE price = 100, each margin set
so toggling one component flips exactly one condition. Golden-master discipline: these assert
LOGIC CORRECTNESS on identical bars (scorer's 8 conditions == methodology's 8 conditions),
NOT champion-number matching, and carry no universe/fixed-snapshot assumption.

| Fixture | Encodes | Asserted result |
|---|---|---|
| `test_golden_8_of_8_plusplusplus` | all 8 conditions true | `conditions == [True]*8`, `score 8`, `"+++"` |
| `test_golden_each_condition_failed_is_7` (×8, parametrised) | mutate one indicator → only that condition flips | exactly `conditions[i] is False`, `score 7`, `"++"` |
| `test_golden_c7_three_part_rule` (×3) | each of ADX<20 / +DI≤−DI / not-rising | `conditions[6] is False`, `score 7` |
| `test_golden_6_of_8_is_plusplus` | C1 + C8 fail | `score 6`, `"++"` |
| `test_golden_rating_bands` (×3) | 5/8→"+", 3/8→"=", 1/8→"--" | exact failure set + score + band |
| `test_golden_determinism` | same state scored 50× | byte-identical results |
| `test_rating_band_contract_full_range` | scores 0..8 → bands | full band table |

**Result: all pass** (alongside the pre-existing `score_symbol_native` condition-logic suite
and the `bct_score_full` FIRE/DECLINE/edge suite). The coded scorer reproduces every
methodology qualify decision exactly. No scorer discrepancy surfaced → no STOP/FLAG on the
scorer (the only FLAG is the out-of-scope entry-trigger gap, §4).

## 6. Provenance

- `version_marker`: `bct_score_full_v1` (unchanged — additive template patterns, no logic change).
- `dist/` rebuilt (`build/cloud_package.py strategies.champion_asis`): new closure member
  `shared_param_space.py`; signal phase flat file picks up the header/`space()`/`COMPLEXITY`.
- **`config_hash` UNCHANGED: `e573e84b1ce1`** → scoring behavior identical → no champion
  provenance pin dance required (DoD step 7). `data_fingerprint`
  `90f2d7e3…c535c` preserved; `git_commit` re-pinned to the #228 source commit.
