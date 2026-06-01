# portfolio_risk phases

Phase kind `portfolio_risk` — caps/governs AGGREGATE portfolio exposure before entries fire
(runs after sizing, before FIRE_ENTRIES; never blocks the bar, only bounds what fires).

Goes here: impls that enforce a portfolio-level exposure rule (gross cap, sector cap, correlation
cap). Each is a `%`/$-RULE, never a position COUNT cap (the charter-forbidden kind).
Does NOT go here: per-name sizing (→ sizing/), entry selection (→ entry_selection/).

- gross_exposure_cap (#181): the hard %-gross ceiling — the safety floor against over-leverage.
