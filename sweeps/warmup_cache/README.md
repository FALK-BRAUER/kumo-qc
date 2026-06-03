# sweeps/warmup_cache — the #332 param-free indicator cache

What's here: the warmup-cache that kills the ~38-120s/cell 560-day warmup (the dominant per-cell
cost — measured 2026-06-02; Docker overhead is only 2.5s by contrast). A param-free table
`{(ticker, date): the 14 BCT scalars}` the strategy reads INSTEAD of replaying 560 days of indicator
warmup. One cache serves the whole grid (the scalars don't depend on cap/gap/vol — those filter
AFTER scoring).

What goes here: `lean_indicators.py` (LEAN-faithful Ichimoku/ADX/SMA ports, byte-parity-gated against
LEAN's own golden test data + a reference cell), the table builder, the lookup, and the consumption
hook. What does NOT: any reimplementation that hasn't passed the byte-identical parity gate (the
parity trap — a cache that changes the trades is worse than no cache).

Status (#332): feasibility GO (the 8-condition score is a pure function of 14 per-date scalars).
Build in progress — Ichimoku port + golden-CSV parity FIRST.
