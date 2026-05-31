# ADR 0001 — Strategy Variant Architecture (entry/exit/sizing/regime proliferation)

**Status:** Proposed (2026-05-31) · **Owner:** fintrack HQ · **Epic:** #208 (phase-engine v2)
**Drivers:** Falk — "we will experiment with multiple entry/exit algos; there will be variations. When do we extend existing phases, when do we build new variants, when do we control behaviour via parameters vs new code? We should have a strategy — maybe address it architecturally."
**Inputs:** independent analysis from three sources (in-house research sweep over LEAN/backtrader/vectorbt/nautilus/zipline, Perplexity, Gemini-2.5-pro) — all three converged; see §7.

---

## Context

A strategy in this engine is a composition of typed **phase** plugins selected by **direct class reference**:

```python
Slot(impl=SomePhase, params=SomePhase.Params(...))
```

Each phase **kind** (`signal`, `entry_selection`, `entry_timing`, `exit`, `stops`, `trail`, `sizing`, `regime`, `adds`, `reentry`, …) owns a **library** of interchangeable implementations, each with its own nested typed `.Params` dataclass. We are `mypy --strict`, use `typing.Protocol` for the phase contract, and deliberately use **no runtime string registry**. The build flattens the active config's closure to `dist/`, which runs identically local + cloud (parity by construction).

We are about to build the **mass runner** (#214): sweep `params × configs × time-windows` in parallel, fast, → leaderboard. And we already have **~40 prototyped variants** to absorb (see §6). The design pressure is: make variation **cheap, clean, type-safe, and reproducible** — without letting the library rot into flag-soup or copy-paste sprawl, and without letting the sweep's combinatorial power overfit.

---

## Decision

### D1 — The boundary: PARAM vs NEW IMPL vs EXTEND

**Default verdict is NEW IMPL.** Reach for a parameter only for same-algorithm tuning; reach for extension almost never.

| You observe | Verdict | Why |
|---|---|---|
| A number/threshold/window/multiplier changes; code path identical | **PARAM** (field on the impl's `.Params`) | same algorithm, different magnitude; sweepable on a continuous axis |
| `if self.params.mode == "A": … else: …` branching over **algorithms** | **NEW IMPL** | each branch *is* an algorithm wearing a param's clothes — split it |
| A param is meaningful to A but **nonsense for B** (disjoint param sets) | **NEW IMPL** | disjoint `.Params` ⇒ disjoint classes |
| Different **inputs** or different **output shape** | **NEW IMPL** | not the same computation |
| You want to **sweep {A, B, C} categorically** | **NEW IMPL** | impls *are* the categorical axis of the sweep |
| Optional **guard/clamp**, default-OFF, same math, leaves past results byte-identical | **EXTEND** | strictly additive sub-mode of one algorithm |
| A boolean that toggles which of two algorithms runs | **NEW IMPL**, never a flag | bool-flag-soup → impossible states |

**The one-line tests (use in code review):**
- *Gemini:* "Can I describe the change **without** the words *if* or *instead*?" → yes ⇒ PARAM; no ⇒ NEW IMPL.
- *Perplexity:* > 2–3 `Literal`/enum modes with different code paths, **or** branch-on-type in > 2–3 places, **or** a phase class bloating past ~150–200 LOC purely from variant logic ⇒ split into impls.

**Failure modes this prevents:**
- *Treating new logic as a param* → **god-phase / boolean-flag soup**: 3 bools = 8 states, most invalid; untestable combinatorics; an `if/elif` cascade no one can reason about.
- *Treating a param as a variant* → **copy-paste sprawl**: `AtrStop_2x`, `AtrStop_2_5x`, `AtrStop_3x` as classes — a continuous knob you can no longer sweep continuously, and a bug fixed in one drifts in the others.
- *Over-extending* → **fragile base class**: a small base change breaks N descendants; behaviour scattered across a hidden inheritance stack.

### D2 — Co-locate the sweep space with the code (`space()` on `.Params`)

The searchable space **lives on the `.Params` dataclass**, never in the sweep driver (which is how it drifts — the LEAN `config.json`-separate-from-code failure mode).

```python
@dataclass(frozen=True)
class KijunAtrTrail:
    @dataclass(frozen=True)
    class Params:
        atr_period: int = 22
        atr_mult: float = 3.0
        source: str = "close"

        @classmethod
        def space(cls) -> dict[str, ParamAxis]:
            # the ONLY source of truth for this phase's sweepable axes
            return {
                "atr_period": IntAxis(low=14, high=40, step=2),
                "atr_mult":   FloatAxis(low=1.5, high=5.0, step=0.25),
                "source":     CategoricalAxis(["open", "high", "low", "close"]),
            }
```

- **Drift-proof under mypy:** `space()` keys are field names — a typo or a field that doesn't exist fails at check/attribute time. Adding a field without adding it to `space()` is a one-file reviewable change.
- **Axis type, not raw tuples:** define a small `ParamAxis` abstraction (`IntAxis`/`FloatAxis`/`CategoricalAxis`). **Make it structurally compatible with optuna distributions** (Gemini) so the runner can later swap grid-search → Bayesian (TPE/CMA-ES) **without touching any phase** — the `space()` declaration is stable.
- **Named presets** (Perplexity) for human-meaningful points, separate from the sweep grid:
  ```python
  AGGRESSIVE = KijunAtrTrail.Params(atr_mult=4.0)
  CONSERVATIVE = KijunAtrTrail.Params(atr_mult=2.0)
  ```

### D3 — Enumerate variants with explicit typed catalogs, NOT a string registry

Per kind, one typed tuple is the sweep driver's enumeration source:

```python
# src/phases/exit/library.py
EXIT_PHASES: tuple[type[ExitPhase], ...] = (KijunTrailExit, WeeklyCloudBreachExit, PartialLadderExit)
```

- **Keeps all the direct-reference wins:** mypy verifies each member satisfies the kind's Protocol; rename breaks loudly at check time; jump-to-definition works; dead variants are detectable; a serialized run references a concrete versioned class (no registry-population nondeterminism → reproducible).
- **Recovers the only thing a registry gave us** — enumeration — with zero of its costs. A string registry is added **only** at a future external-config edge (a non-Python tool writing a sweep grid as YAML), confined to a thin `resolve(name) -> type[Phase]` adapter that immediately yields a typed `Slot`; strings never enter core. (This is exactly Nautilus's split: typed configs in-process, `ImportableStrategyConfig` only at the serialization boundary.)
- A **`StrategySpace`** object models a sweep as the cartesian set of `Slot` choices × each impl's `space()` → a list of **fully-typed, reproducible** `StrategyConfig`s.

### D4 — Composition over inheritance for shared mechanics

Shared machinery (EOD stop evaluation, ATR computation, weekly-bar seeding) lives in **free helper functions** or thin mixins, consumed by impls — **not** a fat `BaseStop` template-method base. The phase contract is a `Protocol`; impls share *code*, never *inheritance state*. (backtrader's 1,700-line `Strategy` god-base is the cautionary tale.)

### D5 — The mass runner must defend against overfitting BY DESIGN

The architecture makes param/structure explosion *easy*; the dominant real-world risk is therefore **curve-fitting noise**, not engineering elegance (our own `feedback_no_hardcoded_params` + NOW −$359 lessons). The runner (#214) bakes in (Gemini):

1. **No single-number results.** Every config's output is the **distribution across the mandatory 6 windows**, never one backtest.
2. **Rank by stability, not peak.** Primary score ≈ `mean(Sharpe) / std(Sharpe)` across windows (robust alpha), not best-window Sharpe.
3. **Complexity penalty (Occam).** Each phase declares a `complexity` (≈ count of swept DoF); leaderboard shows `Sharpe`, `Complexity`, and a complexity-adjusted score so the optimizer prefers the simpler config at equal performance.
4. **Robustness surface.** For top-N candidates, auto-run a local grid around the optimum and report the gradient — prefer **flat regions, reject knife-edges**.
5. **DoF budget per strategy** — a soft cap on total swept parameters, logged loudly when exceeded.
6. Inherits the charter invariants already enforced: **no count caps, no time-based exits, no fixed slots**, out-of-window validation.

---

## Consequences

**Adopted now (rules, review-enforced):** D1 boundary table is the merge gate for every new variant; D4 composition rule; D5 is the runner's contract.

**Implementation gaps these create (→ tickets):**
- `space()` + `ParamAxis` abstraction: not built. New phases adopt it from day one; existing phases (`vix_percentile`, `dv_rank_cap`, `kijun_g3_exits`, …) retrofit a `space()`.
- `library.py` typed catalog tuples per kind: not built.
- `entry_timing` phase: **empty slot** — no impl exists (today entries fire blind off the signal; this is the #228-adjacent P&L gap). The first real variant work (doji-timing, resistance-proximity, T-bounce) lands here and is the proving ground for D1–D3.
- mass runner (#214): stub — builds against D2/D3/D5.

**What we explicitly are NOT doing:** no runtime string registry in core; no `mode=` algorithm-switch params; no fat base classes; no single-window champion claims.

---

## §6 — Our existing variant catalog (the evidence base)

~40 prototyped experiments already in our GH/branch history — the real cases D1–D3 must absorb. Mapped to phase kind:

| Phase kind | Existing variants (→ become sibling impls) | Tunable knobs (→ `.Params` axes) |
|---|---|---|
| `entry_timing` | doji-timing (c1), resistance-proximity (c2), pullback-to-tenkan / T-bounce (methodology §4), pre-breakout-zone (rs148) | zone %, body/wick thresholds, lookback |
| `stops` / `trail` | kijun-ATR-trail (e16), polarity-flip-trail (rs151), fixed-% | atr_period, atr_mult, kijun lookback |
| `adds` (pyramid) | staged-risk Pa–Pe (#172/#178), tiered step-up (#168, X2) | lots, risk-ceiling, step size |
| `sizing` | $-risk (#158-160), score-tier (#167/X1), vol-adjusted (#165/X5) | risk %, tier thresholds, vol lookback |
| `regime` | vix-2tier (e121), circuit-breaker (#32, ±vix), credit-risk-off (#29), market-breadth >50%>200MA (#157/V18), sector-RS (#156/V17) | vix threshold, DD %, breadth %, RS window |
| `exit` | weekly-cloud-breach, kijun-trail, partial-exit ladder (#179, X-ladder) | trim fractions, breach confirm |
| `reentry` | drawdown-reset (#169/X4) | reset DD, cooldown |
| `signal` | bct_score_full (8-cond), + multi-timeframe weekly cloud (#164/X3), composite ranking (#166/X7) | min_score, parabolic threshold |

Most of these were prototyped on the v1 oracle with **forbidden mechanics** (fixed slots, max-positions, day-holds). Per the charter's retrofit rule: **take the intent, drop the mechanic** — re-express each as a principled phase impl (exposure via `gross_exposure_cap`, exits via structure, sizing via $-risk). A retrofit expressible only as a fixed slot / max-hold is **rejected, not ported**.

---

## §7 — External references (kept, per Falk)

How the mature engines structure interchangeable variants — the landscape we're triangulating against:

| Framework | Composition unit | Variant mechanism | Param-space declaration | Catalog |
|---|---|---|---|---|
| **QuantConnect / LEAN** | 5 swappable framework modules (Universe/Alpha/Portfolio/Risk/Execution) | subclass + setter injection (`AddAlpha(EmaCrossAlphaModel())`) | `GetParameter()` reading `config.json` (strings, **separate from code → drift-prone**) | string/path config |
| **NautilusTrader** | `Strategy` + typed `StrategyConfig` (msgspec) | typed config-driven composition | typed config fields | path-string registry **only at serialization edge** |
| **backtrader** | `Strategy` subclass; distinct `Sizer`/commission **classes** (not flags) | subclass + `params` tuple | `optstrategy(S, p=range(...))` — co-located at call site | direct reference |
| **vectorbt** | vectorized `IndicatorFactory` | broadcasting; `vbt.Param([...])` makes any arg a swept axis | `vbt.Param` inline — value knows its own axis | direct reference |
| **zipline** | `Pipeline` of `Factor`/`Filter` terms | term composition + `CustomFactor` subclass | constructor args on terms | direct reference |

**Read:** our `Slot(impl, params=.Params)` over a typed-Protocol, direct-reference library is **Nautilus's typed-config discipline + LEAN's per-slot module swap, minus the stringly-typed weaknesses of both** — a coherent, defensible point in the design space. The community's consistent signals corroborate D1: backtrader uses **distinct Sizer classes, not a `mode` flag**; everyone uses params for numeric thresholds and new classes for algorithmic differences.

**Citations:** LEAN Algorithm Framework + Optimization/Parameters docs · NautilusTrader Strategies & StrategyConfig · backtrader `optstrategy` + Strategy source · vectorbt optimization + IndicatorFactory · zipline Pipeline · Martin Fowler "Flag Argument" · "curve fitting in trading" / "overfitting in algo trading" (QuantifiedStrategies, AlgoTrading101). Full URLs in the research appendix (`research/methodology/` — to be filed with this ADR).

---

## §8 — Decision summary (the rules, one screen)

1. **NEW IMPL by default.** Param only for same-algorithm scalars. `if mode==` over algorithms ⇒ split. Extend only for default-off orthogonal guards.
2. **`space()` on every `.Params`** — single, drift-proof, optuna-compatible source of the sweepable axes. Named presets for human points.
3. **Typed `*_PHASES` catalog tuple per kind** for enumeration. No string registry in core; only at a future external edge.
4. **Composition over inheritance** — Protocols + free helpers, no fat bases.
5. **Runner defends against overfitting** — 6-window distributions, rank by stability not peak, complexity penalty, robustness surface, DoF budget; charter invariants hold.
