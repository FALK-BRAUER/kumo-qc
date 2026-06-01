# bct_intraday_hold_confirm

The #276b-1 **above-Tenkan-hold** intraday entry-confirm VARIANT (entry_selection, INTRADAY) — an
EXPERIMENT (run-to-learn). Confirms on close > intraday Tenkan (a LEVEL hold) + rising-vol, with NO
reclaim-cross requirement — so a gap-up already above Tenkan can confirm (the reclaim-cross sibling
fires ~0 on gap-ups: no_reclaim_cross-dominated). Mutually exclusive with BctIntradayConfirm.

What goes here: the hold-confirm impl + pure core + tests. Does NOT modify the proven reclaim-cross
phase (`../bct_intraday_confirm/`). The "right" mechanic for George's gap-ups is a methodology
question (#270/#277); this is evidence for that pass.
