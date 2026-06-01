# Phases Spec — kumo-qc Strategy Engine

**Status:** Spec (2026-05-30, Falk; **revised 2026-06-01 for the two-clock intraday execution model, #270**). Linked from [ARCHITECTURE.md](ARCHITECTURE.md).

Defines the per-phase contract for the phase-based strategy engine. 29 phase kinds. Every phase implementation conforms to this spec.

> **#270 two-clock model.** Phases run on one of two clocks (`PHASE_RESOLUTION ∈ {daily, intraday}`). **Daily-clock** phases (universe/signal/regime/ranking) decide WHICH names after close T → the candidate list for T+1. **Intraday-clock** phases (entry_selection/entry_timing/sizing/fire/stops/trail/exits) run on T+1's 5-min bars and decide WHEN to fire. Market-on-open with no confirmation is a retired blind-entry FIXTURE, not a champion; `entry`+`exit` are REQUIRED and the engine fails loud (`DegradedConfigError`) without them. See ARCHITECTURE.md §10 + §4.

---

## 0. Common Phase Interface

Every phase implements `PhaseInterface`:

```python
# src/engine/base.py

class PhaseInterface(ABC):
    PHASE_KIND: str = ""               # class attribute, e.g. "universe", "adds"
    PHASE_RESOLUTION: str = "daily"    # #270: "daily" (decision clock) | "intraday" (execution clock)
    REQUIRES_UPSTREAM: list[str] = []  # phase kinds that must be present
    PROVIDES_DOWNSTREAM: list[str] = []  # what downstream phases consume from this

    @abstractmethod
    def __init__(self, params: dict, logger: ComponentLogger): ...

    @abstractmethod
    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...

    @property
    @abstractmethod
    def version_marker(self) -> str: ...   # e.g. "pe_rampup_antikelly_v1"

    @property
    def enabled(self) -> bool: ...          # from config

    def validate_config(self) -> None: ...  # raise on bad params
```

```python
# src/engine/context.py

class PhaseContext:
    """Shared mutable state across one bar/tick. Engine owns lifecycle.

    #270: a ctx is created per TICK on either clock. `clock` tells a phase which clock it is
    running on; daily-clock phases populate the candidate list + signal snapshot, intraday-clock
    phases read the standing candidates + the current COMPLETED 5-min bar (never a forming bar,
    never T+1's daily bar — look-ahead)."""

    # Read-only inputs
    qc_algo: Any                  # QC algorithm instance (Portfolio, Securities, Time, ...)
    bar_time: datetime
    bar_data: dict                # Slice data
    clock: str                    # #270: "daily" | "intraday"

    # Phase outputs (populated as engine progresses through PHASE_ORDER)
    universe: set[str]            # filled by universe phase
    signal_scores: dict[str, int] # filled by signal phase
    regime_blocked: bool          # set by any regime phase
    regime_block_reason: str
    ranked_candidates: list[Candidate]  # filled by ranking
    entry_intents: list[EntryIntent]    # filled by entry_timing
    sized_orders: list[SizedOrder]      # filled by sizing
    pre_trade_blocks: list[Block]       # eligibility, portfolio_risk, cash
    held_positions: dict[str, Position] # current holdings snapshot
    stop_updates: list[StopUpdate]      # filled by trail
    add_intents: list[AddIntent]        # filled by adds
    trim_intents: list[TrimIntent]      # filled by profit
    exit_intents: list[ExitIntent]      # filled by exit_*

    def apply(self, kind: str, result: PhaseResult) -> None: ...
```

```python
# src/engine/base.py

@dataclass
class PhaseResult:
    decision: Any                # phase-specific payload
    blocked: bool = False        # if regime/cash/eligibility blocks downstream
    reason: str = ""
    facts: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
```

---

## 1. universe.source + universe.filter (kind: `universe`)

**Purpose:** Produce today's eligible ticker set.

**Engine order:** 1st phase. **Clock: daily** (`PHASE_RESOLUTION="daily"`). Runs once per daily decision tick (after close T), producing the candidate list for T+1.

**Input:** `ctx.bar_time`, `ctx.qc_algo` (for ObjectStore / Securities).

**Output:** `ctx.universe: set[str]` — today's eligible tickers.

**Params (per implementation):**
| Impl | Params |
|---|---|
| `polygon_daily` | `min_price: float`, `min_dv: int` (filters applied on top of daily snapshot) |
| `scanner_dynamic` | `rating: str` (`+++`), `state: str` (`BUY`), `min_score: int`, `min_adx: int`, `max_vix: float` |
| `sp500_static` | (no params) |
| `etf_basket` | `tickers: list[str]` |

**Required upstream:** none (first phase).
**Provides downstream:** `ctx.universe`.

**Contract:**
- MUST return `set[str]` (never list, never None — empty set if no candidates).
- MUST be idempotent for same bar.
- MUST emit `UNIVERSE|<impl>|count=<n>|date=<ts>|sample=<first-5>` log entry.

---

## 2. signal (kind: `signal`)

**Purpose:** QUALIFY each universe candidate — *"does this name qualify?"* — by scoring it for
entry quality. This is the **qualify lane only**. Entry TIMING (T-Bounce / MACD / volume
confluence) is a SEPARATE downstream `entry_timing` phase, NOT the signal phase.

**Engine order:** After universe.

**Input:** `ctx.bar_state.ranked_candidates`, `qc._indicators` (maintained Ichimoku/ADX/SMA).

**Output:** qualified candidates emitted as entry-priority-ordered `OrderIntent` stubs on
`ctx.bar_state.sized_orders` (qty=0; the sizing phase sets quantity).

**Catalog (ADR D3):** `phases/signal/library.py` exposes
`SIGNAL_PHASES: tuple[type[BasePhase], ...]` — direct class refs (no string registry) for
sweep discovery. Strategy wiring still uses explicit `Slot(impl=..., params=...)`.

**Impls / Params:**
| Impl | Params | `space()` axes | `COMPLEXITY` |
|---|---|---|---|
| `bct_score_full` | `min_score: int` (default 7), `parabolic_threshold: float` (default 0.25) | `min_score∈(6,7,8)` × `parabolic_threshold∈(0.20,0.25,0.30,0.35)` (grid 12) | `free_params=2` |

**Template patterns (set by `bct_score_full`, #228 — every later phase follows):**
- `Params.space() -> ParamSpace` (ADR D2): typed `{field: Sequence[candidate]}` sweep axes.
  Non-swept wiring toggles (e.g. `enabled`) are excluded.
- `COMPLEXITY: ComplexityDecl` (ADR D5): declared free-param count for the overfitting penalty;
  `ComplexityDecl.validate(space())` enforces `free_params == len(space().axes)` (no hidden knobs).
- Primitives live in `phases/shared/param_space.py`.

**Required upstream:** `universe`.
**Provides downstream:** `sized_orders` (only candidates meeting `score ≥ min_score`, not
parabolic, not already invested/pending).

**Contract:**
- MUST emit only candidates with `score ≥ min_score` AND not parabolic-blocked.
- MUST be golden-mastered to the methodology (the CLAUDE.md BCT Signal Stack 8-condition
  checklist) on identical bars — logic correctness, never champion-number matching. See
  `research/methodology/bct-signal-reconciliation.md`.

---

## 3. regime (kind: `regime`, list-of-phases supported)

**Purpose:** Macro on/off switches. ANY regime block halts entry phases.

**Engine order:** After signal. List iterated; first block wins.

**Input:** `ctx.qc_algo.Securities` (VIX, SPY, etc.), `ctx.bar_time`.

**Output:** Sets `ctx.regime_blocked = True` + `ctx.regime_block_reason` if blocked.

**Params:**
| Impl | Params |
|---|---|
| `vix_threshold` | `max_vix: float` (block if VIX > max) |
| `vix_ichimoku` | (no params, uses Ichimoku state) |
| `vix_percentile` | `percentile: float`, `lookback: int` |
| `spy_200ma` | (no params) |
| `market_breadth` | `min_pct_above_200ma: float` |
| `sector_etf_cloud` | `ticker_to_sector: dict` |
| `credit_risk_off` | `tickers: list[str]` (HYG, LQD, TLT) |

**Required upstream:** none (independent).
**Provides downstream:** block flag.

**Contract:**
- Block = halt entries + adds for this bar. Does NOT exit existing positions (unless `exit_regime` phase enabled).
- MUST emit `BLOCK|regime|<impl>|reason=<text>` on block.

---

## 4. ranking (kind: `ranking`)

**Purpose:** Order signal-passing candidates for entry selection.

**Engine order:** After regime (only runs if not blocked).

**Input:** `ctx.signal_scores` (tickers + scores).

**Output:** `ctx.ranked_candidates: list[Candidate]` — sorted, best first.

**Params:**
| Impl | Params |
|---|---|
| `dollar_volume` | `direction: str` (`desc`/`asc`, default `desc`) |
| `composite_score` | `weights: dict` (e.g. `{"score": 0.4, "adx": 0.3, "dv": 0.3}`) |
| `adx_weighted` | `lookback: int` |

**Required upstream:** `signal`.
**Provides downstream:** ranked candidate list.

**Contract:**
- MUST be deterministic (no random tiebreak).
- Tiebreak MUST be explicit (e.g. dollar-vol desc, then ticker asc).

---

## 5. entry_selection (kind: `entry_selection`) — **REQUIRED, intraday (#270)**

**Purpose:** On T+1's intraday clock, GATE the daily candidates down to those CONFIRMING an entry
intraday (the methodology entry trigger), AND pre-flight-validate them against the daily thesis.
Selection + confirmation, NOT slot logic.

**Clock: intraday** (`PHASE_RESOLUTION="intraday"`). Runs on T+1's completed 5-min bars against
the standing daily candidate list. **REQUIRED phase** (fail-loud gate, #270).

**Engine order:** First intraday-execution phase, before `entry_timing` (PHASE_ORDER), ENTRY_ONLY
(suppressed when the bar is regime/cash-blocked).

**Input:** the daily candidate list + each candidate's daily SNAPSHOT (signal price, daily Kijun);
`ctx.bar_state.sized_orders` (the signal's qty=0 OrderIntent stubs); maintained INTRADAY indicators.

**Output:** the SAME `sized_orders` list, FILTERED in place to confirmed candidates. A per-symbol
confirmation state is published on `qc._entry_confirm[ticker]` (+ `PhaseResult.facts`).

**Two sub-roles (in order):**
1. **Pre-flight staleness gate** (`PreFlightStaleness`, #270 — the FIRST intraday phase). Re-validate
   each candidate against its daily snapshot: if T+1 has gapped away from / below the thesis (price
   vs signal price / daily Kijun beyond tolerance), INVALIDATE it. Don't enter a broken thesis —
   George's gap-up discipline as a phase.
2. **Intraday confirmation** (`BctIntradayConfirm`, #270 — the LOCKED mechanic). Confirm on
   completed 5-min bars: **intraday-Tenkan reclaim + rising volume** (GH#25 §3.2), within the first
   ~2h. Fires only on confirmation; defers across intraday bars until confirmed or the window closes.

**RETIRED:** `BctEntryConfirm` (#253) — the **DAILY** §4 Gate-2 (C1–C4) snapshot gate. It degraded
Sharpe to −1.016 precisely because a once-daily snapshot is not an intraday touch (its own
measurement doc flagged this). Kept only as a fixture/reference, NOT the confirmation mechanic.

Phase-2 variants (planned, own classes): `ResistanceZoneFilter` (#148), `RiskRewardFilter` (#150),
`DojiDelay` (#64).

**Required upstream:** `signal` (the daily candidate list + snapshot).
**Provides downstream:** `sized_orders` (gated, confirmed).

**Contract:**
- NO count caps / fixed slots — the gate is principled (intraday confirmation), not a top-N cap.
- Reads only COMPLETED intraday bars + the daily snapshot; NEVER T+1's daily bar (look-ahead).
- `blocked` is ALWAYS False — entry_selection gates candidates, it never blocks the bar.
- Methodology↔code mapping + golden-master: `research/methodology/` (intraday-confirm reconciliation).

---

## 6. entry_timing (kind: `entry_timing`) — **REQUIRED, intraday (#270)**

**Purpose:** Decide the order mechanics (type + price) for each confirmed candidate, and emit the
typed `OrderIntent` the fire seam executes.

**Clock: intraday.** **REQUIRED phase** (fail-loud gate, #270).

**Engine order:** After `entry_selection`, before `sizing` (so a price-rewriting variant feeds
sizing the entry price). ENTRY_ONLY.

**Input / Output:** `ctx.bar_state.sized_orders`; the phase SETS `intent.order_type` (+ `price`/
`stop`). The actual placement is the engine's `FIRE_ENTRIES` sentinel, which dispatches on
`intent.order_type` (the Command-pattern fire seam) — phases never touch LEAN directly.

**Impls (catalog: `phases/entry_timing/library.py` → `ENTRY_TIMING_PHASES`):**
| Impl | Marker | Params | Role |
|---|---|---|---|
| `ConfirmedMarketEntry` (#270) | `confirmed_market_entry_v1` | (none — baseline) | Once intraday-confirmed, fire `order_type=market` immediately (intraday), NOT next-open MOO |

Phase-2 variants (planned, own classes): `BuyStopEntry` (#149, §4 Gate-5 day-type buy-stop),
`LimitPullbackEntry` (limit @ Tenkan). **RETIRED:** `MarketOnOpenEntry` (#253) — the blind
next-open baseline; market-on-open is now just one `order_type` value, and a confirmation-free MOO
config is a FIXTURE, not a champion.

**Required upstream:** `entry_selection` (confirmed candidates).
**Provides downstream:** `sized_orders` (with `order_type`/`price`/`stop` set).

**Contract:**
- Emits the typed `order_type`; the fire seam (not the phase) calls the QC API. A buy-stop/limit
  variant rewrites `intent.price`/`intent.stop` here.
- `blocked` is ALWAYS False.

---

## 7. sizing (kind: `sizing`)

**Purpose:** Compute share quantity per entry intent.

**Engine order:** After entry_timing.

**Input:** `ctx.entry_intents`, `ctx.qc_algo.Portfolio.TotalPortfolioValue`.

**Output:** `ctx.sized_orders: list[SizedOrder]` — qty per intent.

**Params:**
| Impl | Params |
|---|---|
| `risk_based_fixed` | `risk_dollars: float` (e.g. 200) |
| `risk_based_pct` | `risk_pct: float` (e.g. 0.001 = 0.1% of equity) |
| `atr_normalized` | `atr_mult: float`, `risk_pct: float` |
| `score_tiered` | `tier_map: dict` (e.g. `{7: 200, 8: 300}`) |

**Implemented impls (`SIZING_PHASES` catalog, `phases/sizing/library.py`):**
| Impl | Params | Behavior |
|---|---|---|
| `flat_pct_heatcap` | `position_pct` | Flat `position_pct` per name + committed-cash heat-cap. IGNORES the X/4 score (champion-asis sizer). |
| `score_tier_heatcap` | `position_pct`, `full`, `three_quarter`, `half`, `min_score` | The X/4 entry-confirm score (`qc._entry_confirm[ticker]`) BINDS on size via the methodology tiers — **4/4 → full · 3/4 → 75% · 2/4 → 50% · <`min_score` → no entry** — composed WITH the same committed-cash heat-cap (tier sets the per-name target; heat-cap bounds total gross). A candidate with NO published score is DECLINED (no flat fall-back — a wiring bug must fail visibly). |

**Required upstream:** `entry_timing` (needs stop_hint for risk math). `score_tier_heatcap` also
requires `entry_selection` (the published X/4 score).
**Provides downstream:** sized orders.

**Contract:**
- `flat_pct_heatcap` / `score_tier_heatcap` formula: `qty = floor(target_value / price)` where
  `target_value = position_pct × [tier ×] portfolio_value`, filled until the cash heat-cap is hit.
- (Risk-based impls) Formula: `qty = risk_dollars / (entry_price - stop_price)`.
- MUST round to whole shares (floor).
- MUST skip if computed qty == 0 (log skip).
- CHARTER: exposure governed by the % gross-exposure heat-cap only — NO count caps / fixed slots /
  time exits.

---

## 8. eligibility (kind: `eligibility`)

**Purpose:** Pre-fire checks. Block individual orders.

**Engine order:** After sizing.

**Input:** `ctx.sized_orders`, `ctx.held_positions`.

**Output:** Filters `ctx.sized_orders` in place. Logs blocks.

**Params:**
| Impl | Params |
|---|---|
| `already_held_check` | (no params; skip if position exists) |
| `sector_cap` | `max_per_sector: int`, `sector_map_file: str` |
| `correlation_cap` | `max_correlation: float`, `lookback: int` |

**Required upstream:** `sizing`.
**Provides downstream:** filtered sized orders.

**Contract:**
- BLOCKS are per-order, not per-bar (unlike regime).
- MUST emit `BLOCK|eligibility|<impl>|ticker=<x>|reason=<text>` per block.

---

## 9. portfolio_risk (kind: `portfolio_risk`, list)

**Purpose:** Aggregate exposure ceilings. Block individual orders.

**Engine order:** After eligibility.

**Input:** `ctx.sized_orders`, `ctx.held_positions`, `ctx.qc_algo.Portfolio`.

**Output:** Filters `ctx.sized_orders`. Logs blocks.

**Params:**
| Impl | Params |
|---|---|
| `gross_exposure_cap` | `max_pct: float` (default 100 = no margin) |
| `sector_exposure_cap` | `max_sector_pct: float` |
| `committed_cash_cap` | `max_committed_pct: float` |

**Required upstream:** `eligibility`.
**Provides downstream:** filtered sized orders.

**Contract:**
- MUST account for in-flight committed exposure (not just current holdings).
- Per #181 lesson: order-time check + per-bar check.
- MUST emit `BLOCK|portfolio_risk|<impl>|reason=<text>|metric=<x>`.

---

## 10. cash (kind: `cash`)

**Purpose:** Cash floor + margin policy.

**Engine order:** After portfolio_risk.

**Input:** `ctx.sized_orders`, `ctx.qc_algo.Portfolio.Cash`.

**Output:** Filters or halts.

**Params:**
| Impl | Params |
|---|---|
| `no_margin` | (no params; reject any order that uses margin) |
| `cash_floor` | `min_cash_dollars: float` |
| `idle_deployment` | `target_cash_pct: float` |

**Required upstream:** `portfolio_risk`.
**Provides downstream:** final order list.

**Contract:**
- Engine FIRES orders only after this phase. All filters complete.

---

## 11. stops_initial (kind: `stops_initial`)

**Purpose:** Compute initial stop price for each filled entry.

**Engine order:** Triggered on fill event (not per-bar).

**Input:** `ctx.qc_algo.Securities` (ATR, kijun), filled order.

**Output:** `ctx.held_positions[ticker].stop_price`.

**Params:**
| Impl | Params |
|---|---|
| `atr_initial` | `atr_mult: float` (e.g. 2.5) |
| `kijun_initial` | (no params) |
| `swing_low_initial` | `lookback: int` |

**Contract:**
- MUST set stop at order time (not after price moves).
- MUST emit `STOP_INIT|<ticker>|stop=<x>|method=<impl>`.

---

## 12. trail (kind: `trail`)

**Purpose:** Move stops as price progresses.

**Engine order:** Per-bar, after universe (independent thread).

**Input:** `ctx.held_positions`, `ctx.qc_algo.Securities`.

**Output:** `ctx.stop_updates: list[StopUpdate]`.

**Params:**
| Impl | Params |
|---|---|
| `kijun_trail` | (no params; trail to kijun) |
| `atr_trail` | `atr_mult: float` |
| `breakeven_move` | `trigger_r: float` (move to breakeven after +1R) |
| `chandelier_trail` | `atr_mult: float`, `lookback: int` |

**Required upstream:** position must exist.
**Provides downstream:** stop updates applied immediately.

**Contract:**
- Stops MUST only RATCHET UP (never lower).
- MUST emit `TRAIL|<ticker>|old=<x>|new=<y>|method=<impl>`.

---

## 13. adds (kind: `adds`)

**Purpose:** Pyramid additional lots into existing positions.

**Engine order:** Per-bar, after trail.

**Input:** `ctx.held_positions`, `ctx.signal_scores` (for renewal detection).

**Output:** `ctx.add_intents: list[AddIntent]` → goes through sizing + portfolio_risk + cash before firing.

**Params:**
| Impl | Params |
|---|---|
| `pe_signal_renewed` | `lot_size_dollars: float` (default 200) |
| `pe_rampup_antikelly` | `lot_progression: list[float]` (e.g. [200, 400, 600]) |
| `pe_conviction` | `lot_progression: list[float]` (e.g. [300, 200, 100]) |
| `pe_winscale` | `min_unrealized_pct: float`, `lot_size_dollars: float` |

**Required upstream:** `signal` (for renewal trigger).
**Provides downstream:** add intents → sized → risk-checked → fired.

**Contract:**
- Adds MUST flow through same sizing + portfolio_risk + cash phases as entries.
- MUST emit `ADD_INTENT|<ticker>|lot=<#>|size=<$>|method=<impl>`.


---

## 14. profit (kind: `profit`)

**Purpose:** Partial profit-taking. Trim qty without exit.

**Engine order:** Per-bar, after adds.

**Input:** `ctx.held_positions`.

**Output:** `ctx.trim_intents: list[TrimIntent]`.

**Params:**
| Impl | Params |
|---|---|
| `ladder_trim` | `rungs_pct: list[float]` (e.g. [10, 20]), `trim_fraction: float` (e.g. 0.33) |
| `atr_target` | `atr_mult: float`, `trim_fraction: float` |
| `r_multiple` | `r_targets: list[float]` (e.g. [2.0, 4.0]), `trim_fraction: float` |

**Contract:**
- MUST never trim to zero (use exit phases for full closes).
- Each rung fires AT MOST ONCE per position.
- MUST emit `TRIM|<ticker>|qty=<n>|price=<x>|rung=<%>`.

---

## 15. exit_hard (kind: `exit_hard`, list) — **REQUIRED (an exit phase MUST be wired), intraday-capable (#270)**

**Purpose:** Forced exits on signal/stop/regime conditions. `exit` is a REQUIRED kind (fail-loud
gate, #270) — at least one exit phase MUST be wired or the engine refuses to start.

**Clock (#270):** exits run on the **intraday** clock so a stop fires *intrabar* on the break, via
a `stop_market` `OrderIntent` (GH#25 §3.3) — NOT a next-open MOO. The stop LEVEL is computed from
the daily structure (Kijun/cloud), but the TRIGGER is intraday price crossing it. (A daily-close
exit is the legacy behaviour and the symptom that overnight-gapped: retired in favour of the
intraday stop.) Exit-side phases run regardless of a regime/cash block.

**Engine order:** Per intraday bar, before adds (exits take precedence over re-engagement).

**Input:** `ctx.held_positions`, `ctx.qc_algo.Securities`, the maintained daily stop level.

**Output:** `ctx.exit_intents: list[ExitIntent]` (with `order_type=stop_market`, `stop=<level>`)
→ fired via the seam.

**Params:**
| Impl | Params |
|---|---|
| `kijun_g3` | (champion exit; stop level = daily Kijun / G3 cloud-bottom, fired intraday stop-market) |
| `cloud_breach` | (no params; stop level = daily cloud bottom) |
| `weekly_kijun` | (no params; weekly close below weekly kijun) |
| `kumo_flip` | (no params; exit if Senkou A < Senkou B) |
| `sector_etf_break` | `sector_etf_map: dict` |

**Contract:**
- Exit intents fire IMMEDIATELY via the seam (no further phase processing). The stop LEVEL derives
  from daily structure; the TRIGGER is an intraday completed-bar cross (look-ahead-safe).
- MUST emit `EXIT|<ticker>|reason=<impl>|pnl=<$>`.

---

## 16. exit_target (kind: `exit_target`)

**Purpose:** Profit-target exits (close full position at target).

**Params:**
| Impl | Params |
|---|---|
| `cup_rim` | `lookback: int` |
| `swing_high` | `lookback: int` |
| `r_multiple` | `r_target: float` |

(Same contract as exit_hard.)

---

## 17. exit_regime (kind: `exit_regime`)

**Purpose:** Forced exits on regime change.

**Params:**
| Impl | Params |
|---|---|
| `vix_spike_exit` | `vix_threshold: float` |
| `breadth_collapse_exit` | `min_pct_above_200ma: float` |
| `spy_break_exit` | (no params) |

---

## 18. exit_rotation (kind: `exit_rotation`)

**Purpose:** Sell worst-ranked holding to make room for better-ranked candidate.

**Engine order:** Last in exit chain.

**Input:** `ctx.held_positions`, `ctx.ranked_candidates`.

**Output:** Exit intent for worst position + entry intent for replacement.

**Params:**
| Impl | Params |
|---|---|
| `sell_worst_buy_best` | `min_score_delta: int` (only rotate if new candidate is much better) |

---

## 19. reentry (kind: `reentry`)

**Purpose:** Rules for re-entering after a stop-out.

**Engine order:** Filters entry_intents before sizing.

**Params:**
| Impl | Params |
|---|---|
| `cooldown_buy_stop` | `cooldown_days: int` (e.g. 30), `require_buy_stop: bool` |

**Contract:**
- MUST emit `BLOCK|reentry|<ticker>|reason=cooldown|days_remaining=<n>`.

---

## 20. rebalance (kind: `rebalance`) — two-clock scheduler (#270)

**Purpose:** Engine tick scheduler — drives BOTH clocks.

**Engine order:** Wraps the cycle. Schedules the **daily decision** as an after-close event
(`on_daily_bar` → candidates for T+1) and routes **intraday** 5-min bars to `on_intraday_bar`
(execution) on T+1.

**Params:**
| Impl | Params |
|---|---|
| `after_close_scan` (#270) | `scan_time: str` (after-close, e.g. "16:05") → daily decision; intraday execution on the 5-min clock next session |
| `daily_close` | `time: str` — legacy single-clock (fixture only; not a champion scheduler) |
| `weekly_friday` | `time: str` |
| `signal_driven` | (no params; fire on any signal change) |

**Contract:**
- Exactly ONE rebalance module per strategy; for a champion it MUST drive both clocks
  (after-close scan + intraday execution). A single-daily-clock scheduler is a fixture only.
- `on_daily_bar` produces candidates + the signal snapshot; `on_intraday_bar` executes on
  completed 5-min bars (look-ahead-safe).

---

## 21. diagnostics (kind: `diagnostics`, list)

**Purpose:** Logging, parity checks, version markers. No trading impact.

**Engine order:** End of cycle.

**Params:**
| Impl | Params |
|---|---|
| `parity_logger` | `frequency: str` (e.g. "daily") |
| `version_marker` | (no params; logs all phase version markers at init) |
| `signal_dump` | `frequency: str` |

**Contract:**
- NEVER mutates ctx.
- NEVER fires orders.
- Logs only.

---

## 22. circuit_breaker (kind: `circuit_breaker`)

**Purpose:** Halt-on-anomaly. Last line of defense.

**Params:**
| Impl | Params |
|---|---|
| `dd_reset` | `max_dd_pct: float`, `reset_after_days: int` |
| `error_rate` | `max_errors_per_bar: int` |

**Contract:**
- MUST have explicit reset condition (no dead-latches, per F3 lesson).
- MUST log every halt with detailed reason.

---

## Engine PHASE_ORDER (canonical, two-clock #270)

One ordered list; each phase tagged with its clock. The engine PRECOMPUTES the daily-subset and
the intraday-subset at config-build (not a per-tick filter) and replays them via `on_daily_bar` /
`on_intraday_bar`. `[D]` = daily decision clock, `[I]` = intraday execution clock.

```python
PHASE_ORDER = [
    "rebalance",          # [D] scheduled after-close tick
    "universe",           # [D] daily ticker set
    "signal",             # [D] score per ticker → candidate list + signal snapshot for T+1
    "regime",             # [D] macro blocks (list)
    "ranking",            # [D] order candidates
    # ───── daily decision ends (candidates for T+1) ─────
    "entry_selection",    # [I] pre-flight staleness gate + intraday-Tenkan/volume confirm
    "entry_timing",       # [I] order_type + price (confirmed → market; day-type → stop/limit)
    "sizing",             # [I] quantity
    "reentry",            # [I] cooldown filter
    "eligibility",        # [I] per-order checks
    "portfolio_risk",     # [I] aggregate exposure (list)
    "cash",               # [I] cash policy
    # → FIRE_ENTRIES (seam dispatches on order_type)
    "stops_initial",      # [I] set stops on fills
    "trail",              # [I] ratchet stops
    "exit_hard",          # [I] forced exits → intraday stop-market (list)
    "exit_target",        # [I] profit targets
    "exit_regime",        # [I] regime-forced exits
    "exit_rotation",      # [I] rotate worst → best
    # → FIRE_EXITS (seam: stop_market intrabar)
    "adds",               # [I] pyramid intents
    # → adds flow through sizing + risk + cash again
    "profit",             # [I] partial trims
    "diagnostics",        # [D]+[I] logging (list, runs both clocks)
    "circuit_breaker",    # [D]+[I] halt checks
]
```

---

## Phase Dependency Matrix

| Phase | Requires Upstream | Provides Downstream |
|---|---|---|
| universe | (none) | ctx.universe |
| signal | universe | ctx.signal_scores |
| regime | (none — independent) | ctx.regime_blocked |
| ranking | signal | ctx.ranked_candidates |
| entry_selection | ranking | ctx.entry_candidates |
| entry_timing | entry_selection | ctx.entry_intents (with stop_hint) |
| sizing | entry_timing | ctx.sized_orders |
| reentry | (filters entry_intents) | filtered intents |
| eligibility | sizing | filtered orders |
| portfolio_risk | eligibility | filtered orders |
| cash | portfolio_risk | final orders |
| stops_initial | order fill | position.stop_price |
| trail | held_positions | stop_updates |
| exit_hard | held_positions | exit_intents |
| exit_target | held_positions | exit_intents |
| exit_regime | held_positions, regime | exit_intents |
| exit_rotation | held_positions, ranked_candidates | exit + entry intents |
| adds | signal, held_positions | add_intents (→ sizing → risk → cash) |
| profit | held_positions | trim_intents |
| rebalance | (engine wrapper) | scheduler tick |
| diagnostics | all ctx state | logs only |
| circuit_breaker | engine state | halt flag |

---

## Engine validation at init

Engine MUST verify on `__init__`:

1. **Required phases present (#270 fail-loud gate)** — `REQUIRED_PHASES = (universe, signal, sizing, entry, exit)`. `entry` (entry_selection + entry_timing) and `exit` are now REQUIRED. A config that would FIRE entries with no wired entry-confirm phase, or fire exits with no wired exit phase, raises `DegradedConfigError` (no implicit market-on-open default). A blind-MOO/placeholder-entry config is a FIXTURE and is rejected as a champion.
2. **No conflicting adds** — only one adds module enabled at a time.
3. **No count caps** — assert no params like `max_positions: <int>`, `max_lots: <int>`, `max_entries_per_day: <int>`.
4. **No time exits** — assert no params like `max_hold_days`, `exit_if_flat_after_days`.
5. **Explicit exposure** — if adds enabled, gross_exposure_cap MUST be enabled.
6. **All required upstream present** — for each enabled phase, check its REQUIRES_UPSTREAM.
7. **Clock coherence (#270)** — every phase declares `PHASE_RESOLUTION ∈ {daily, intraday}`; the daily/intraday subsets are precomputed; an intraday phase in a config with no intraday data subscription → `DegradedConfigError`.
8. **Version markers + clocks logged** — emit all marker strings + each phase's `PHASE_RESOLUTION` on init for deploy verification.

Failure = engine refuses to start. NO silent fallback. (This is #261's fail-loud-on-degraded-data extended to the phase-stack config — the gate that would have crashed the phantom daily-MOO champion instead of silently trading it.)
