# #276a Build Plan — fire-seam + #290 GTC protective stop + #181 gross-cap (SAFETY-CRITICAL) — CHECKPOINT

**Status:** the SAFETY-CRITICAL split-unit of #276 (real order firing + the catastrophic stop).
HQ gates it with a HARD independent mutation-review. Reference-researched (all order-API facts
below CONFIRMED from ~/reference/Lean @ 96a670a9 — do NOT re-guess). Checkpointed for a FRESH
careful build (the #275b fresh-context discipline, applied harder — this is the real-money path).
worktree: kumo-qc-276a, branch feat/276a-fire-seam-gtc-grosscap, off mainV2 c55fdc1.

## CONFIRMED reference facts (don't re-research)
- **Order APIs** (Algorithm/QCAlgorithm.Trading.cs): `market_order(sym, qty)`,
  `stop_market_order(sym, qty, stop_price)`, `market_on_open_order(sym, qty)`. snake_case in Python.
- **GTC is the DEFAULT TimeInForce** (Common/Orders/OrderProperties.cs:42 — `TimeInForce.GoodTilCanceled`).
  So `stop_market_order` rests until triggered/cancelled by default = EXACTLY the #290 catastrophic
  floor (fires intrabar on the level cross even on gap/outage/halt). No TIF override needed.
- **OrderIntent** (src/engine/context.py:14) already has `ticker, qty, price, stop, module,
  risk_dollars` — a defaulted `order_type` + `protective_stop` field is additive-safe (7 construction
  sites, all keyword — defaults won't break them).
- **The fire seam** (src/engine/engine.py `_fire`): FIRE_ENTRIES/EXITS/ADDS/TRIMS currently hardwire
  `qc.market_on_open_order`. #274 forecast the order_type dispatch; #276a implements it.
- **No portfolio_risk phase exists** — only the charter invariant (`validate_invariants`, engine.py:113:
  adds-without-portfolio_risk → CharterViolation). #181 BUILDS the phase.

## The 3 components

### 1. OrderIntent.order_type + the fire-seam dispatch
- Add `order_type: str = "market_on_open"` (back-compat default → existing configs/fixtures
  UNCHANGED) + `protective_stop: float = 0.0` to OrderIntent.
- `_fire` dispatches on `intent.order_type`: "market_on_open" → market_on_open_order (today's
  behavior); "market" → market_order (intraday confirmed entry, #276b); "stop_market" →
  stop_market_order(sym, qty, intent.stop) (intraday exit, #276b).
- BEHAVIOR-UNCHANGED for the asis fixture: default order_type = market_on_open → identical fires.

### 2. #290 GTC protective stop (the catastrophic floor)
- On FIRE_ENTRIES, AFTER the entry order, if `intent.protective_stop > 0`: place a resting
  `stop_market_order(sym, -qty, intent.protective_stop)` (GTC by default → rests until hit/cancelled).
  This is the dumb safety net UNDER the runtime Kijun exit (#276b's exit_hard). BOTH required.
- Track the protective-stop ticket in _position_meta so it's CANCELLED when the runtime exit fills
  (avoid a double-sell / orphan resting stop). ← the lifecycle detail to get right (cancel-on-exit).
- The protective level is set by sizing/entry_timing (a % below entry, or the daily Kijun — the
  sizer/#276b decides; #276a just FIRES + tracks + cancels it).
- FAIL-LOUD: a config that fires entries but sets no protective_stop on a CHAMPION → consider a
  gate (champion must protect). (Decide with HQ: warn vs raise; lean raise for a champion.)

### 3. #181 gross-exposure control (portfolio_risk phase)
- New phase `src/phases/portfolio_risk/gross_exposure_cap/` (PHASE_KIND="portfolio_risk", daily-clock):
  blocks/trims entries that would push total gross exposure beyond `gross_exposure_cap` (% of equity,
  NOT a count cap — charter-distinct). Reads portfolio value + pending sized_orders.
- Wire the catalog (PORTFOLIO_RISK_PHASES), space(), COMPLEXITY per the ADR templates.
- The charter invariant (adds → portfolio_risk) already enforced; this provides the phase it needs.

## Tests (per component: behavioral + fail-loud + outage, mutation-bite; HQ mutation-reviews HARD)
- order_type dispatch: each type → the right QC call (fake qc records calls); default = MOO
  (behavior-unchanged control).
- GTC protective stop: placed on entry with protective_stop>0; NOT placed when 0; CANCELLED when
  the runtime exit fills (no orphan); the resting stop fires on a gap the runtime exit misses
  (the catastrophic-floor proof — simulate price gapping through the stop).
- gross-cap: blocks the entry that breaches the cap; passes under; adds-without-cap → CharterViolation
  (the existing invariant, re-asserted); the % is a real exposure calc not a count.
- SG: no behavior change on the asis fixture (default order_type); the cap is a % rule (no count cap).

## Constraints
- config_hash: the asis fixture UNCHANGED (default order_type = MOO → byte-identical). The gross-cap
  phase is opt-in (champion_intraday wires it at #276c). 2-commit dance for dist. Explicit git add.
- This MERGES only after GATE-0 runs clean on the RESTORED substrate (HQ: GATE-0 = the merge-gate;
  the worker is rebuilding daily+coarse fresh into /Users/falk/projects/kumo-qc/data now).
- GATE-0 trio-invariance is RELATIVE (the 3 fixtures agree on the FRESH substrate = behavior-neutral
  split), NOT the old absolute −0.139 (re-baselines on the fresh tree).
- Read ~/reference/Lean for any further order/cancel API detail (cancel via the OrderTicket / 
  qc.transactions). No if-cloud, RAW, single path.

## After #276a → #276b (intraday entry-confirm + pre-flight staleness + stop-market exit phases) →
#276c (champion_intraday assembly) → #277 (re-baseline local≈cloud on the fresh substrate, the TRUE
baseline; cloud-observable via chart-emit numeric series + the #285 /chart/read fix).

## HQ's review criteria (build TO these — independent mutation-review gates the PR)
1. **Cancel-on-exit (THE hardest-hunted bug):** the resting GTC protective stop is CANCELLED on
   EVERY runtime-exit fill path — no orphan double-sell. Track the OrderTicket in _position_meta,
   cancel it in the FIRE_EXITS path (and any other close path). Test: exit fills → stop cancelled.
2. **FIRE seam isolation:** ONLY FIRE_* touches the broker API; phases emit OrderIntent only;
   order_type honored (stop_market/market/limit/market_on_open).
3. **Gross-cap (#181):** caps gross exposure (% rule); mutation-bite on the cap.
4. **Each of the 3 components mutation-verified to BITE** (break the invariant → a test goes RED).
5. **config_hash + provenance dance airtight from the start** (2-commit, dist pins SRC not the dist
   commit — note: HQ+derxu3fo resolving a pin off-by-one on #296; build #276a's dance clean: commit
   src FIRST, rebuild dist at that HEAD, commit dist-only; NEVER --amend across the dance boundary —
   the banked hard rule from the #274/#275b mishaps).

## Resume sequence
fresh context → read THIS plan → build #276a to the 5 criteria → own PR → HQ hard mutation-review →
GATE-0 (RELATIVE trio-invariance on the FRESH substrate, once 6fmes4tp's daily+coarse rebuild lands)
gates the merge.
