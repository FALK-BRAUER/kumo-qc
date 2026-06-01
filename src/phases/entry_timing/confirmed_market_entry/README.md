# confirmed_market_entry

The #270/#276b-1 **intraday confirmed-market** entry-timing phase (entry_timing kind, INTRADAY clock).

**What it does:** stamps each CONFIRMED candidate (entry_selection already gated to confirmed-only)
with `order_type="market"` so FIRE_ENTRIES fires it as an intraday market order NOW (at confirm),
not a next-open market-on-open. Pass-through (the engine FIRE_ENTRIES seam places the order); qty
stays 0 until `sizing`.

**What goes here:** the intraday confirmed-market timing impl + tests. NOT the daily/fixture
baseline (that is `../market_on_open_entry/`, MOO — mutually exclusive in a wired config;
entry_timing instances share one clock).

**What does NOT go here:** the confirm decision (entry_selection/bct_intraday_confirm), sizing,
stops (exit_hard), or any LEAN order call (FIRE_ENTRIES owns that).
