# 276b-0 two-clock smoke — STOP finding: daily decision clock fires intraday

**Date:** 2026-06-01. **Run:** v2 dist @ src 587f8e1, window 2025-02-01..02-14, Docker LEAN. Exit 0.
**Verdict:** snapshot handoff + intraday subs WORK; but the smoke caught a **pre-existing #275b two-clock bug** (HQ STOP-rule → halt before 276b-1).

## What passed (276b-0 code is sound)
- v2 dist ran (run's `code/lean_entry.py` contains `_capture_candidate_snapshot` — not the legacy monolith).
- SNAPSHOT capture works (keyed by canonical Symbols; hundreds of candidates/day).
- Intraday 5-min subscriptions engage + deliver: AAPL/MSFT/NVDA/COST/SPY (all have minute data 2024-06→2025-02) intraday-subscribed.
- **ZERO DegradedDataError, ZERO Traceback** on the clean path.

## The SURPRISE (STOP-rule trip)
SNAPSHOT lines per date:
```
1   2025-02-03      ← 1/day (correct: daily clock fires once)
1   2025-02-04
390 2025-02-05      ← jumps to 390/day exactly when SPY gets intraday-subscribed
390 2025-02-06 … 02-14
```
ENTRY log (the daily-MOO fixture firing): **778× on 2025-02-07** (vs Total Orders 14 — LEAN bounds actual fills, but the daily FIRE_ENTRIES path re-runs hundreds of times intraday).

## Root cause — `src/runtime/lean_entry.py:790-791` (commit f77a498, #275b — PRE-EXISTING, not 276b-0)
```python
spy_bar = bars.get(self.spy.symbol) ...
if spy_bar is not None or not self._intraday:   # "daily heartbeat = SPY bar present"
    ... run the DAILY decision pipeline (selection/signal/FIRE_ENTRIES) + (276b-0) snapshot capture
```
`self.spy` is the DAILY SPY. But once SPY is also **intraday-subscribed** (it gets selected as a candidate / ETF), the 5-min slices contain a SPY bar → `bars.get(self.spy.symbol)` returns the **intraday** SPY bar → the daily decision clock fires on **every 5-min step** (~390/day), not once after close.

Latent until now: #275b was "log-only, behaviour-unchanged" and its smoke (274-delivery, a minimal AAPL consolidator algo) never selected SPY into the intraday set. 276b-0's SNAPSHOT logging surfaced it.

## Impact (why it blocks 276b-1)
- Violates the core two-clock invariant: **the daily decision clock must fire once/day (after close)**, not on every intraday bar.
- The daily decision pipeline (universe selection + signal + FIRE_ENTRIES) re-runs intraday on partial data — wasteful and a look-ahead/correctness hazard.
- The daily-MOO fixture re-fires entries intraday (778×/day) — and for the **champion** (276b-1 intraday entry) a daily clock that fires intraday is incoherent. Cannot build intraday entry on this.
- On **mainV2 now** (merged via #275b) — needs a fix there, rebased into 276b.

## Proposed fixes (HQ to choose — touches the two-clock core, pre-existing code)
1. **Once-per-date guard (surgical, smallest):** run the daily decision block at most once per calendar date. 276b-0 already tracks `self._last_daily_date` — guard `if date != self._last_daily_date` (and set it before, not after, the block). Dedupes to 1/day regardless of SPY's intraday sub.
2. **Schedule the daily decision (most #270-aligned):** fire the daily scan on a scheduled after-close event (PHASES §20 `after_close_scan` rebalance), NOT on SPY-bar-presence. Bigger change.
3. **Distinguish the bar (narrow):** detect the DAILY SPY bar by period/resolution (daily bar.period == 1 day vs the 5-min intraday bar), so only the true daily bar trips the block.
4. **Exclude the heartbeat symbol from intraday subscription** (don't intraday-sub SPY) — addresses SPY specifically but not other-ETF heartbeats; weakest.

Lean: **#1** (once-per-date guard, reuses `_last_daily_date`) as the immediate fix; #2 as the proper #270 model. HQ + Falk call.

## Status
276b-0 CODE remains correct + green (587f8e1). This finding is a SEPARATE pre-existing #275b defect that must be fixed (likely its own fix-ticket on mainV2, rebased into 276b) BEFORE 276b-1. Smoke did its job — caught a two-clock regression before building the model on top.
