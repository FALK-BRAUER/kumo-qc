# gross_exposure_cap (#181)

The hard gross-exposure ceiling: drops new entries whose combined value would push total gross
exposure (held + committed) past `max_gross_pct × equity`. The SAFETY floor that prevents a
bug/over-eager sizing from over-leveraging (the Pe 1.44x scar). A %-rule (not a count cap),
parameterized; #302 (regime hierarchy) may modulate `max_gross_pct` later. Never blocks the bar.
