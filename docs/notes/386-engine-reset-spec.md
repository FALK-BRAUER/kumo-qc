# The real intraday engine — design, legacy-to-delete, and 3 scenarios to prove the modular phase concept

This ticket resets the foundation. It (1) records the mistakes that got us here so we don't repeat them, (2) specifies the real engine — how it ticks and how it uses phase modules, with legacy parts marked for deletion — and (3) defines 3 real validation scenarios, built on one branch, that prove the module-per-phase concept by composing genuinely different strategies across the whole day-phase pipeline (swap algos, tune params, change behavior, engine untouched).

---

## PART 1 — The mistakes (so we don't repeat them)

1. **Optimized a champion that was never validated.** A full tournament (~16 levers) ran against "S1" and concluded "S1 is the efficient frontier." S1 is not a champion — it's a misconfiguration (below). Every conclusion from that work is **void.**

2. **Rewrote the engine instead of building modules.** The pyramid / #378 / #379 work added **+197 lines to `engine.py`** (`_resize_protective_stop_for_add`, `_resize_protective_stop_for_trim`, FIRE_TRIMS handling, the over-sell guard, co-clock invariant) and **+65 to `lean_entry.py`**. Strategy behavior in the engine core — the exact thing the modular design exists to prevent. 247 lines of divergence + entry-routing breakage.

3. **Ran on the wrong branch, dirty tree.** Everything ran on `feat/340-pyramid`, +247 engine lines diverged from `mainV2`, with a `data._brokenrealdir_120240/` (data-symlink damage). The "S1 baseline" was S1-config on a modified engine — not the champion.

4. **The "champion" has TWO entry slots → it's a mistake, not a champion.** S1's 36 FY entries are bimodal: 16 fill ~09:31 via the phase chain (gap+vol confirm), **20 fill ~15:51 via the engine's default market-on-open** — two competing entry mechanisms. The monsters (HOOD/KGC) enter via the EOD default, bypassing the confirm.

5. **The claimed "2-phase engine (scanner → intraday trading)" was never built.**
   - **Scanner phase is a STUB** (#228: `sample_bct.py` returns a `score>=7` placeholder, no real Ichimoku; the real BCT lives in `kumo-trader/scanner/`).
   - **Intraday trading was never built** — `lean_entry.py:351/517`: the decision fires on a **scheduled DAILY after-close event**. `engine.py:76`: *"a future strategy MAY add a real per-bar filter phase"* — the per-bar loop is explicitly future work. The only "intraday" is the **open-30m window** (`window_bars=6`, then `window_closed`) + a **market-on-open default**.
   - So "the intraday engine" = a daily after-close decision + a 30-min confirm window + an EOD default fill. **A daily engine wearing an intraday label.**

6. **Daily lever-tuning on a daily-clock engine could never express intraday behavior** — which is why every entry-side lever read neutral.

**Net:** the phase *framework* (PHASE_ORDER, FIRE_ sentinels, folder-per-phase, slots) is real and good. The two phases that matter — a real scanner and a real per-bar intraday loop — were never built. We build them now, as modules, engine untouched.

---

## PART 2 — The real engine

### How it ticks (two clocks)

Two clocks over two LEAN subscriptions (daily + 5-min):

**DAILY TICK** (once per day, on the daily bar):
- Runs the **DAY-PHASE chain**: `universe → signal(scanner) → regime → ranking → entry_selection → sizing → stops_initial`.
- Output: the **armed candidate set** — each entry carries `{thesis, entry_zone, invalidation_rule}`.
- Maintains the set across days: add new, **drop on thesis-break**, keep the rest armed. (The persistent thesis / "evaluate previous candidates" — the watchlist lives across days, not a fresh daily scan.)

**5-MIN TICK** (every 5-min bar, in `on_data`):
- Runs the **INTRADAY chain** for each armed candidate: `entry_trigger → intraday_sizing → FIRE_ENTRIES`.
- The **entry_trigger** is a per-bar if-then: *evaluate this 5-min candle in the context of preceding candles, + time-of-day → fire / wait / hold.*
- Fire at the bar the condition is met. Candidates not fired **stay armed** for the next bar until they fire or the thesis breaks. **No window, no time-postponement, no default fill.**
- **Proximity-gated:** a candidate's intraday watch turns ON only when price is near its entry_zone (correctness + perf).
- **Look-ahead-safe:** fire using that bar + preceding only — causal by construction.

### Phase slots have a clock

Each slot is tagged DAY or INTRADAY. **Day modules slot into day-phase slots; intraday modules into intraday-phase slots.** The strategy is a config naming a module(+params) per slot — swap/tune/add without touching the engine.

| Clock | Phase slots | Module kind |
|---|---|---|
| DAY | universe · signal(scanner) · regime · ranking · entry_selection · sizing · stops_initial · trail · exit | day-trading modules |
| INTRADAY (5-min) | entry_trigger · intraday_sizing · (intraday_exit later) | intraday modules |

### LEGACY — DELETE
- The **after-close DAILY decision** that fires entries (`lean_entry.py:351/517`) — entry decision moves to the 5-min tick.
- The **open-30m window** (`gap_vol_confirm` `window_bars`/`window_closed`) — gap becomes an un-windowed per-bar trigger.
- The **market-on-open default + EOD funnel** (the 2nd entry slot / blind-MOO) — deleting it resolves #382 by construction.
- The **stub signal** (`sample_bct.py`, #228) — replaced by the ported real BCT scanner.
- The **engine.py strategy rewrites** (#378/#379 resize/FIRE_TRIMS) — out of the engine; rebuilt as modules only if a scenario needs them.

### KEEP
- PHASE_ORDER + FIRE_ sentinels + folder-per-phase + per-phase behavioral tests.
- The 5-min feed (`Resolution.MINUTE`, `on_data`, `_intraday[sym]`) — reused as the intraday tick source.

---

## PART 3 — Three validation scenarios (one branch, real catalog modules)

Built from the **#254 phase-variant catalog** (real 2–3 impls per slot). The proof is not swapping one slot — it's composing **genuinely different strategies across ~10 day-phase slots**. One branch, engine code identical.

### Scenario A — "Conviction-Core / Cloud-Adherence" (defensive let-run)
| slot | module (#254) |
|---|---|
| universe | DvRankCap |
| signal | **Tier1HighConviction** (George's ++/Tier-1 23-set) |
| regime | **MarketBreadthGate** (>50% S&P >200MA) |
| ranking | ScoreDvRanking |
| entry_selection | **ResistanceProximityFilter** (skip <3% to 52wk-high) |
| sizing | ScoreTierHeatcap |
| stops_initial | **CloudBottomStop** (G3) |
| trail | CloudAdherenceTrail |
| exit | **CloudBreachExit** |

### Scenario B — "Sector-Momentum / Breakout-Risk" (aggressive; a different algo in EVERY slot)
| slot | module (#254) |
|---|---|
| universe | **SectorRotationUniverse** (top-3 sectors by RS) |
| signal | **BctScoreFull** (8-condition) |
| regime | **VixRegime** (VIX 2-tier) |
| ranking | **CompositeRanking** (multi-factor) |
| entry_selection | **RiskRewardFilter** (skip R/R<2:1) |
| entry (intraday) | **BuyStop**-style trigger |
| sizing | **VolAdjustedRisk** ($-risk, VIX-scaled) |
| stops_initial | **AtrStop** (2.5×) |
| trail | **TightenAfterProfit** |
| exit | **MultiMetricConfirmExit** (MACD-turn) |

### Scenario C — "Conviction-Core, tuned" (slightly different from A: param-tweaks + targeted swaps)
| slot | vs A |
|---|---|
| universe | DvRankCap — same algo, **tighter coarse_max param** |
| signal | Tier1HighConviction — **same** |
| regime | MarketBreadthGate — same algo, **>40% param** |
| ranking | ScoreDvRanking — **same** |
| entry_selection | ResistanceProximityFilter — same algo, **2% buffer param** |
| sizing | ScoreTierHeatcap — **same** |
| stops_initial | **SupportAtrStop** — *swapped* from CloudBottomStop |
| trail | CloudAdherenceTrail — **same** |
| exit | **MultiMetricConfirmExit** — *swapped* from CloudBreachExit |

### What this proves (the modularization matrix)
- **A vs B** — different module in *every* slot → the entire day-phase pipeline is swappable; two completely different strategies, one engine.
- **A vs C** — mostly shared, with **param-tweaks** (universe cap, breadth %, resistance buffer) + **two targeted slot swaps** (stop, exit) → fine-grained modularity; change one slot without disturbing neighbors.
- **Reuse** — DvRankCap/Tier1/ScoreTier/CloudAdherenceTrail drop into A+C unchanged; the intraday entry is shared in A+C.
- All three on the **same two-clock engine** — the intraday entry is shared (A/C) or swapped (B's BuyStop), so the **day-phase** variation is the isolated proof.

### The gate
Engine + framework code **byte-identical** across A/B/C — the only diff is the `{slot: module(params)}` config maps. **Any engine/framework edit to make a scenario work = modularization failed.** Each catalog module gets its per-phase behavioral test (fire + decline on dummy inputs). Validate later (multi-year panel); first prove the *mechanism* — three different real strategies from config alone.

Catalog: #254. Relates: #373 (SectorRotation), #328 (learned-signal — a 4th option), #302 (multi-TF regime), #385 (why-intraday), #228 (real signal), #382 (the 2-slot finding), #208/#191 (the framework that stays).

---

## APPENDIX — Per-module behavioral contracts (from #254 catalog, for the orchestrator who can't read GH)

**Day-phase modules to build (A/B/C):**
- **Tier1HighConviction** (signal) — pass a name ONLY if it's in George's ++/Tier-1 23-name set AND clears the score. (Restricts the score-7 pool to high-conviction names.)
- **MarketBreadthGate** (regime) — eligible-to-open only when >THRESHOLD% of S&P constituents are >200MA. Param: 50% (A), 40% (C). Below → no new longs.
- **ResistanceProximityFilter** (entry_selection) — REJECT a candidate if price is within X% of its 52-wk high (chasing into resistance). Param: 3% (A), 2% (C). Prefer 2–10% below resistance.
- **CloudBottomStop** (stops_initial) — initial protective stop at the Ichimoku cloud bottom (the G3 result, the only positive of 20+ stop experiments).
- **CloudBreachExit** (exit) — exit when daily close breaches below the cloud (cloud-adherence model; do NOT exit on Kijun-break alone).
- **SectorRotationUniverse** (universe) — universe = names in the top-3 sectors by sector relative-strength.
- **VixRegime** (regime) — VIX-percentile 2-tier gate; defensive/no-new-longs when VIX percentile high.
- **CompositeRanking** (ranking) — multi-factor entry-priority score (not just dollar-vol).
- **RiskRewardFilter** (entry_selection) — REJECT if (target−entry)/(entry−stop) < 2:1.
- **VolAdjustedRisk** (sizing) — $-risk position sizing, scale DOWN when VIX rising; use a NON-Kijun stop for the $-risk denominator.
- **AtrStop** (stops_initial) — stop at 2.5× ATR below entry (anti-whipsaw).
- **TightenAfterProfit** (trail) — normal Kijun trail; tighten after +10% unrealized.
- **MultiMetricConfirmExit** (exit) — require multi-metric confirmation to exit (e.g. MACD-turn); avoid sole Kijun-break (24% win rate).
- **SupportAtrStop** (stops_initial, C) — stop at max(Kijun, support + ATR×0.5).
- **BuyStop** (intraday entry, B) — per-bar trigger: arm a buy-stop above the breakout/resistance level; fire when price trades through it (on the 5-min clock).

**Reuse (base impls — exist or port as-is):** DvRankCap (universe), BctScoreFull (signal), ScoreDvRanking (ranking), ScoreTierHeatcap (sizing), CloudAdherenceTrail (trail).

Each module: one folder, one behavioral test (fire + decline on dummy inputs). The strategy is a `{slot: module(params)}` config. **Engine byte-identical across A/B/C — that's the gate.**
