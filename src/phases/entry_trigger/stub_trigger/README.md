# stub_trigger

`StubEntryTrigger` — the M1 throwaway per-bar entry trigger (intraday clock). Proves the two-clock
plumbing: day-chain arms `qc._armed` → this fires armed-near-zone candidates per 5-min bar. Proximity-
gated + look-ahead-safe. Real triggers (Gap-Momentum / BuyStop / Pullback) are M3/Step-2 modules.
