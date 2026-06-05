# reserve_heatcap

`ReserveHeatcap` — `FlatPctHeatcap` + a base-entry gross budget (#340-reserve lever).

**What goes here:** the sizing-phase variant that reserves `(1 - base_entry_gross_budget)` of portfolio
value as cash only the pyramid adds may consume (charter-compliant cash-reserve, not a slot cap).

**What does not:** the base sizing logic (lives in `../flat_pct_heatcap/`; this subclass only adds the
param so the champion's `FlatPctHeatcap.Params` — and its pinned config_hash — stay byte-identical).
