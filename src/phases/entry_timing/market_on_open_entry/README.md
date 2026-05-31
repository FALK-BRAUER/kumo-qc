# entry_timing/market_on_open_entry

The **BASELINE order mechanics** — market-on-open (the §4 Gate-5 default made EXPLICIT) (#253
Phase-1). Today's implicit engine behavior (FIRE_ENTRIES fires market-on-open) promoted to a
named, catalogued phase — the COPYABLE reference the phase-2 timing variants follow.

- **Holds:** `market_on_open_entry.py` (the phase), its `.Params` (just `enabled` — the baseline),
  an EMPTY `space()` (no sweepable mechanic), `COMPLEXITY` (`free_params=0`).
- **Behavior:** a pass-through that stages every confirmed+sized candidate as market-on-open and
  stamps timing provenance on `intent.module`. The engine's `FIRE_ENTRIES` sentinel does the
  actual MOO placement (a phase never touches LEAN directly) — so the baseline rewrites nothing.
- **Ordering:** runs after `entry_selection`, before `sizing` (a non-baseline variant rewrites
  `intent.price`/`intent.stop` here so sizing reads the entry price).
- **Tests:** `tests/phases/entry_timing/market_on_open_entry/` (stages/none/never-blocks/empty-space).
- **Does NOT:** day-type order-type/price logic (gap-up→limit@Kijun, breakout→buy-stop, …) — those
  are phase-2 entry_timing variants (`BuyStopEntry` #149, `LimitPullbackEntry`), each its own class.
