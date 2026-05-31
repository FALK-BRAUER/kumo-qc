# phases/entry_timing/

The **entry_timing** phase kind: decide the ORDER MECHANICS (type + price) for each confirmed
candidate. Answers *"how do we place the order?"* — market-on-open / buy-stop / limit-pullback.
Runs after `entry_selection`, before `sizing`.

- **Holds:** one subdir per impl (`<impl>/<impl>.py` + `README.md`), plus `library.py` — the
  `ENTRY_TIMING_PHASES` catalog (typed tuple of DIRECT CLASS REFS for sweep discovery; ADR D3).
- **Members:** `market_on_open_entry` (the baseline MOO mechanics — #253 Phase-1 reference).
  Phase-2 variants (own classes): `BuyStopEntry` #149, `LimitPullbackEntry`.
- **Contract:** reads/writes `sized_orders` (a non-baseline variant rewrites `intent.price`/`stop`);
  the engine's `FIRE_ENTRIES` sentinel does the actual order placement; `blocked` always False.
  Declares `PHASE_KIND="entry_timing"`, a `version_marker`, `Params.space()`, and `COMPLEXITY`.
- **Does NOT:** candidate selection/confirmation (`entry_selection`), sizing, or qualify scoring.
