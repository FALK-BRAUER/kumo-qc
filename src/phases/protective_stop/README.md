# protective_stop

The pre-FIRE **protective-stop** phase kind (#276b-1/#290) — sets `intent.protective_stop` on the
final surviving sized entries so FIRE_ENTRIES places + ticket-tracks the broker-side GTC
catastrophic floor (the #276a cancel-replace + GUARD-3 lifecycle then manage it).

**What goes here:** protective-floor impls (the level set on the entry intent, pre-FIRE). Current:
`kijun_protective_stop/` (daily-Kijun structural floor). Epic-2 floor variants (ATR-mult, swing-low)
append as sibling impls (ADR D1: different algorithm = new class).

**What does NOT go here:** the runtime exit (exit_hard/kijun_g3 — the bar-by-bar managed exit,
distinct from this broker-side floor), order_type (entry_timing), qty (sizing), or any LEAN order
call (FIRE_ENTRIES owns placement + ticket-tracking).

**Placement:** PHASE_ORDER runs it after sizing/portfolio_risk/cash, right before FIRE_ENTRIES — so
the floor is computed only for intents that actually survive to fire, and is set PRE-FIRE (a
post-FIRE stop_market would orphan the position / bypass the ticket machinery).
