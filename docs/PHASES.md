# Phases Spec — kumo-qc Strategy Engine

**Status:** Spec (2026-05-30, Falk). Linked from [ARCHITECTURE.md](ARCHITECTURE.md).

Defines the per-phase contract for the phase-based strategy engine. 29 phase kinds. Every phase implementation conforms to this spec.

---

## 0. Common Phase Interface

Every phase implements `PhaseInterface`:

```python
# src/engine/base.py

class PhaseInterface(ABC):
    PHASE_KIND: str = ""               # class attribute, e.g. "universe", "adds"
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
    """Shared mutable state across one bar/tick. Engine owns lifecycle."""

    # Read-only inputs
    qc_algo: Any                  # QC algorithm instance (Portfolio, Securities, Time, ...)
    bar_time: datetime
    bar_data: dict                # Slice data

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

**Engine order:** 1st phase. Runs once per bar (daily).

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

**Purpose:** Score each universe ticker for entry quality.

**Engine order:** After universe.

**Input:** `ctx.universe`, `ctx.qc_algo.Securities` (indicators).

**Output:** `ctx.signal_scores: dict[str, int]` — ticker → score.

**Params:**
| Impl | Params |
|---|---|
| `bct_score` | `min_score: int` (filter threshold, default 7) |
| `bct_relaxed` | `min_score: int` (default 6) |
| `composite_breakout` | `lookback: int`, `min_breakout_pct: float` |

**Required upstream:** `universe`.
**Provides downstream:** `ctx.signal_scores` (only tickers meeting `min_score`).

**Contract:**
- MUST return only tickers with score ≥ min_score.
- MUST emit per-ticker dump on request (diagnostics phase consumes this).

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

## 5. entry_selection (kind: `entry_selection`)

**Purpose:** Pick which ranked candidates to actually attempt entry on (top-N, slot logic).

**Engine order:** After ranking.

**Input:** `ctx.ranked_candidates`.

**Output:** `ctx.entry_candidates: list[Candidate]` — subset chosen for entry.

**Params:**
| Impl | Params |
|---|---|
| `take_all` | (no params; pass through all) |
| `top_n_by_rank` | `n: int` |
| `score_threshold` | `min_score: int` (e.g. only 8/8) |

**Required upstream:** `ranking`.
**Provides downstream:** entry-eligible candidate list.

**Contract:**
- NO count caps with hardcoded values. Use risk-based or score-based logic.
- If using `top_n_by_rank`, n MUST come from config (parameterized).

---

## 6. entry_timing (kind: `entry_timing`)

**Purpose:** Decide order type + price for each entry candidate.

**Engine order:** After entry_selection.

**Input:** `ctx.entry_candidates`, `ctx.qc_algo.Securities`.

**Output:** `ctx.entry_intents: list[EntryIntent]` — order specs (ticker, type, price).

**Params:**
| Impl | Params |
|---|---|
| `buy_stop_kijun` | `offset_pct: float` (above kijun, e.g. 0.75) |
| `market_open` | (no params; market order at open) |
| `limit_pullback` | `pullback_pct: float` (limit below prior close) |
| `daytype_aware` | `gap_threshold_pct: float`, `wait_minutes: int` |

**Required upstream:** `entry_selection`.
**Provides downstream:** entry intent list.

**Contract:**
- MUST set stop price hint for downstream sizing phase.
- MUST emit `ENTRY_INTENT|<ticker>|type=<x>|price=<y>|stop_hint=<z>` log.

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

**Required upstream:** `entry_timing` (needs stop_hint for risk math).
**Provides downstream:** sized orders.

**Contract:**
- Formula: `qty = risk_dollars / (entry_price - stop_price)`.
- MUST round to whole shares (floor).
- MUST skip if computed qty == 0 (log skip).

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
| `pe_signal_renewed` | `lot_size_dollars: float` (default 200), `max_adds: int` or None |
| `pe_rampup_antikelly` | `lot_progression: list[float]` (e.g. [200, 400, 600]) |
| `pe_conviction` | `lot_progression: list[float]` (e.g. [300, 200, 100]) |
| `pe_winscale` | `min_unrealized_pct: float`, `lot_size_dollars: float` |

**Required upstream:** `signal` (for renewal trigger).
**Provides downstream:** add intents → sized → risk-checked → fired.

**Contract:**
- Adds MUST flow through same sizing + portfolio_risk + cash phases as entries.
- MUST emit `ADD_INTENT|<ticker>|lot=<#>|size=<$>|method=<impl>`.
- `max_adds` is the ONLY count-cap exception (per-position, not portfolio-level).

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

## 15. exit_hard (kind: `exit_hard`, list)

**Purpose:** Forced exits on signal/stop/regime conditions.

**Engine order:** Per-bar, before adds (exits take precedence over re-engagement).

**Input:** `ctx.held_positions`, `ctx.qc_algo.Securities`.

**Output:** `ctx.exit_intents: list[ExitIntent]` → fired immediately.

**Params:**
| Impl | Params |
|---|---|
| `cloud_breach` | (no params; exit if daily price below cloud) |
| `weekly_kijun` | (no params; exit if weekly close below weekly kijun) |
| `kumo_flip` | (no params; exit if Senkou A < Senkou B) |
| `sector_etf_break` | `sector_etf_map: dict` |

**Contract:**
- Exit intents fire IMMEDIATELY (no further phase processing).
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

## 20. rebalance (kind: `rebalance`)

**Purpose:** Engine tick scheduler.

**Engine order:** Wraps the entire on_data cycle.

**Params:**
| Impl | Params |
|---|---|
| `daily_close` | `time: str` (e.g. "16:05") |
| `weekly_friday` | `time: str` |
| `signal_driven` | (no params; fire on any signal change) |

**Contract:**
- Exactly ONE rebalance module per strategy.
- Engine.on_data() runs only when scheduler fires.

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

## Engine PHASE_ORDER (canonical)

```python
PHASE_ORDER = [
    "rebalance",          # scheduler tick
    "universe",           # daily ticker set
    "signal",             # score per ticker
    "regime",             # macro blocks (list)
    "ranking",            # order candidates
    "entry_selection",    # pick top-N
    "entry_timing",       # order type + price
    "sizing",             # quantity
    "reentry",            # cooldown filter
    "eligibility",        # per-order checks
    "portfolio_risk",     # aggregate exposure (list)
    "cash",               # cash policy
    # → orders fire here
    "stops_initial",      # set stops on fills
    "trail",              # ratchet stops
    "exit_hard",          # forced exits (list)
    "exit_target",        # profit targets
    "exit_regime",        # regime-forced exits
    "exit_rotation",      # rotate worst → best
    "adds",               # pyramid intents
    # → adds flow through sizing + risk + cash again
    "profit",             # partial trims
    "diagnostics",        # logging (list)
    "circuit_breaker",    # halt checks
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

1. **Required phases present** — at least one universe, signal, ranking, entry_timing, sizing, cash, rebalance.
2. **No conflicting adds** — only one adds module enabled at a time.
3. **No count caps** — assert no params like `max_positions: <int>`, `max_lots: <int>`, `max_entries_per_day: <int>`.
4. **No time exits** — assert no params like `max_hold_days`, `exit_if_flat_after_days`.
5. **Explicit exposure** — if adds enabled, gross_exposure_cap MUST be enabled.
6. **All required upstream present** — for each enabled phase, check its REQUIRES_UPSTREAM.
7. **Version markers logged** — emit all marker strings on init for deploy verification.

Failure = engine refuses to start. NO silent fallback.
