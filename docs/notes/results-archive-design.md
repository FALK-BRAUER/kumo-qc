# Results Archive — design (the learn-the-methodology data substrate)

*2026-06-02 — the copy→learn pivot foundation. SURFACE FOR GEMINI before building.*

## Problem

We lose every run's detail. `results/bt-results.csv` is 11 aggregate rows (trio + provenance) — ZERO
trades, ZERO context. And **cloud BTs PURGE** (the fired-set mine died on "Backtest not found"),
**ChartEmit 'Universe' returns 0 series**, **cloud logs are API-unretrievable**, **ObjectStore export
is blocked**. So the actual trades + the conditions the entry saw evaporate. You cannot learn which
conditions predict good trades without recording the trades + their context. This is fatal for the
learn pivot AND it's why the 78-order funnel is currently unprovable.

## The one durable channel that survives

Audit of QC retrieval (what's actually pullable AT RUN-TIME, before purge):
- `/backtests/read` → statistics + closedTrades summary. ✅ retrievable; ✗ no per-trade strategy context.
- `/backtests/orders/read` → **per-order fills, AND each order carries a `tag` string.** ✅ retrievable
  (proven: pulled the 78-order feed). **The order `tag` is the durable per-entry context channel.**
- `/backtests/chart/read` → custom chart series. Retrievable BUT 'Universe' came back empty → ChartEmit
  is unreliable/misconfigured (must debug); numeric-only, 4000-pt cap. Use only for per-day FUNNEL counts
  if fixable; NOT the per-trade channel.
- logs / ObjectStore → ✗ dead. Do not rely on them.

**Decision: per-trade context rides on the ORDER TAG.** At entry, the strategy tags the order with a
compact context blob; the snapshotter pulls `/orders/read` at run-time and parses the tags into the
durable archive. This survives purge (snapshot grabs it while the BT is alive) and needs no log/chart/OS.

## Two halves

### A. Snapshot-before-purge (the durable writer)
After EVERY BT completes (local or cloud), and BEFORE returning to any purge window, write a durable
per-run artifact:
```
results/archive/<config_hash>/<window_name>/
  result.json    # full StrategyConfig (serialized) + config_hash + commit + data_fingerprint +
                 # objective_version + ALL QC statistics (the trio + everything) + run provenance (bt_id, ts, env)
  trades.jsonl   # one line per closed trade. THE LEARN-SUBSTRATE (feeds the #303 feature-mine →
                 # OracleSignal #322; see fintrack research/learn-methodology-approach.md). Each row:
                 #   OUTCOME: pnl, ret, R_multiple, exit_reason, duration_bars, MFE, MAE  ← R + MFE/MAE
                 #            are what the mine regresses context against (winners-vs-losers separation)
                 #   FILLS: symbol, entry_dt, entry_px, exit_dt, exit_px, qty, side  ← from /orders/read
                 #   CONTEXT (parsed from the entry order tag — the conditions the entry SAW):
                 #     - the 8 BCT conditions INDIVIDUALLY (8 booleans, NOT just score≥7) — so the mine
                 #       learns WHICH of George's conditions predict R, not "score passed". This is the core.
                 #     - gap_pct, vol_ratio, intraday_tenkan_dist, scanner_rank, sector_rank,
                 #       regime{spy_above_200ma, vix, spy_ret}, signal_score
```
- Keep `results/bt-results.csv` as the human INDEX (one summary row per run, unchanged).
- Optional later: a `results/results.db` sqlite mirror for querying (the lab/analysis queries it). JSONL
  first (git-trackable, simple, append-only); sqlite is a view built from the JSONL.
- **Fail-loud**: a degraded/crashed run (assert_cloud_clean fail) is NOT archived as a result (or is
  archived with `degraded=true` and excluded from learning) — never a silent partial.

Wiring: `#214 RunResult` already holds per-trade returns in-memory. EXTEND it to carry the full
`TradeRecord` (already extensible/frozen) + context, and add a `persist_run(run_result, config, dest)`
that both adapters (LocalLeanRun, CloudLeanRun) call after assert_cloud_clean passes. The cloud adapter's
`run_backtest` already re-reads stats (#326); add an `/orders/read` pull there → trades+tags.

### B. Per-trade context emission (the strategy side — the LEARN fuel)
QC closedTrades lacks the entry conditions, so the STRATEGY must emit them. At the moment an entry order
is submitted (lean_entry intraday fire path), build a compact context blob and set it as the order TAG:
```
tag = "g=3.4;sc=8;cb=11111111;v=1.6;spy200=1;vix=17.2;rank=12;tdist=0.8"
   gap_pct, signal_score, conditions_bitmask(8 bits), vol_ratio, spy_above_200ma, vix, scanner_rank, intraday_tenkan_dist
```
All of these are KNOWN at fire time: gap_pct + vol_ratio from the gapvol confirm; signal_score +
conditions_bitmask from BctScoreFull (the per-condition booleans — needs the signal phase to expose the
8-bit mask, a small addition); regime from the regime phases; scanner_rank from _ranked_today; tenkan_dist
from the intraday snapshot. Keep the tag < ~200 chars (QC tag limit).

MFE/MAE (max favourable/adverse excursion over the hold) are NOT in the entry tag — they need the
in-trade path. Capture at EXIT: the strategy tracks per-open-position running max/min unrealised and
writes them to the EXIT order tag (or the snapshotter derives them from the held-period bars). This is
the trade-QUALITY signal the mine needs beyond final R (a winner that never drew down ≠ a winner that
round-tripped).

WHY individual conditions (not the score): the learn pivot replaces `BctScoreFull score≥7` with a
DATA-DERIVED predictor (research/learn-methodology-approach.md) — the mine asks "which of the 8 + which
context predict high R", likely a fewer/weighted/regime-conditional subset. That mine is impossible if
the archive only stored the aggregate score. The 8 booleans are the non-negotiable core of the substrate.

### C. Funnel instrumentation (answers the 78-sparsity, durably)
Per-day attrition counts (signal-winners → preflight-pass → confirm-eligible → confirmed) are AGGREGATE,
not per-trade — the order tag can't carry the non-fired counts. Two complementary measurements:
1. **LOCAL signal-count run (immediate, no cloud, no intraday needed):** the daily 8-cond signal needs only
   DAILY data (weekly/daily ichimoku + ADX + 200ma + score over the 200-name universe — all locally
   present). A daily-only diagnostic harness logs per-day `n(score>=min_score)`. This DIRECTLY settles
   "~90/day vs ~5-10/day" — the legit-vs-bug discriminator at the dominant (signal) stage. The confirm
   stage (gap>=3%) is already estimated (~5-6/day gap across 200 names from the universe-gap mine).
2. **Cloud funnel series (durable, needs ChartEmit fixed):** debug why ChartEmit 'Universe' = 0 series,
   then emit per-day funnel counters as chart series (n_signal, n_preflight, n_confirm_eligible, n_fired)
   → snapshot via /chart/read into result.json. This is the durable cloud funnel record.

## Build order (proposed)
1. (B) signal phase exposes the 8-condition bitmask + score; (B) lean_entry tags entry orders with the
   context blob. + tests.
2. (A) `results/archive` writer: persist_run() + RunResult/TradeRecord extension + the /orders/read tag
   parser. + tests (fixture order docs with tags → trades.jsonl).
3. Wire both adapters to call persist_run after assert_cloud_clean. Keep bt-results.csv index.
4. (C1) LOCAL signal-count harness → run → the funnel attrition number (settles the 78). (C2) debug
   ChartEmit → durable cloud funnel series.
5. One instrumented cloud run of the current base → the FULL archive artifact (config+trades+context) +
   the funnel → DEFINITIVELY answer legit-vs-bug + seed the learn substrate.

## Open questions for Gemini
- Order-tag as the per-trade-context channel: is the QC tag length/retrieval reliable enough, or prefer
  a per-entry chart point? (logs/OS are out.)
- JSONL-first vs sqlite-first for the durable store.
- Should a degraded run be archived (degraded=true, excluded from learning) or refused entirely?
- The funnel: is the LOCAL signal-count run a sufficient legit-vs-bug discriminator, or must we fix
  ChartEmit for the full cloud funnel before trusting the rate?
```
