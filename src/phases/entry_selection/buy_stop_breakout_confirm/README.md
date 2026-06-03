# buy_stop_breakout_confirm

`entry_selection`-kind, INTRADAY. #348 V1 — forward-confirmation entry: confirm a candidate ONLY when
intraday price clears a BUY-STOP above the signal-day close (`signal_price × (1+breakout_buffer)`).

- **What's here:** `buy_stop_breakout_confirm.py` (the `BuyStopBreakoutConfirm` phase + the pure
  `breakout_confirm_decision`), `__init__.py`.
- **Why:** #348 proved no static entry feature separates winners from losers (HOOD≡MRVL at entry) →
  require the name to PROVE the breakout (Falk's buy-stop mechanic). batch-1 level = +0.75% (sT10e).
- **What does NOT go here:** the gap+vol confirm (`bct_intraday_gap_vol_confirm/`), the staleness
  guard (`preflight_staleness/`). One-variable swap: this replaces the entry-selection ALGO only.
