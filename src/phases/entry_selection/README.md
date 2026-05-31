# phases/entry_selection/

The **entry_selection** phase kind: GATE the qualified+ranked candidates down to those CONFIRMING
an entry. Answers *"of the names that qualify, which should we actually attempt to enter NOW?"* —
the methodology entry trigger / confirmation gates. Runs between `ranking` and `entry_timing`.

- **Holds:** one subdir per impl (`<impl>/<impl>.py` + `README.md`), plus `library.py` — the
  `ENTRY_SELECTION_PHASES` catalog (typed tuple of DIRECT CLASS REFS for sweep discovery; ADR D3).
- **Members:** `bct_entry_confirm` (the §4 Gate-2 X/4 confirmation gate — #253 Phase-1 reference).
  Phase-2 variants (own classes): `ResistanceZoneFilter` #148, `RiskRewardFilter` #150, `DojiDelay` #64.
- **Contract:** reads `sized_orders` (signal stubs), filters in place to confirmed candidates,
  `blocked` always False (gates candidates, never blocks the bar); declares
  `PHASE_KIND="entry_selection"`, a `version_marker`, `Params.space()`, and `COMPLEXITY`.
- **Does NOT:** order mechanics (that is `entry_timing`), sizing, or qualify scoring (`signal`).
