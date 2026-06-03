# bct_intraday_confirm

The #270/#276b-1 **intraday entry-confirm** phase (entry_selection kind, INTRADAY clock).

**What it does:** on the 5-min clock, fires an entry confirmation for a standing daily candidate
when a COMPLETED bar's close CROSSES UP through the intraday Tenkan (the EVENT, not a level check)
AND that bar's volume expands over the window-mean baseline (× `vol_mult`). Windowed (~24 bars /
2h) with per-candidate deferral until confirm or window-close (SG5).

**What goes here:** the intraday-confirm phase impl + its pure `confirm_decision` core + behavioral
tests. NOT the daily entry-confirm (that is `../bct_entry_confirm/`, MACD-based, #253 — the two are
mutually exclusive in a wired config; entry_selection instances share one clock).

**What does NOT go here:** candidate injection (lean_entry), pre-flight staleness
(`../preflight_staleness/`), entry firing (entry_timing + FIRE_ENTRIES), stops (exit_hard).
