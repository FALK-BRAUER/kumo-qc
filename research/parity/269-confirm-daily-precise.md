# GH #269 confirm — is `Settings.DailyPreciseEndTime` the entry-fill-grid knob?

**Status: KNOB REFUTED (as the same-day↔next-day grid switch) — but `daily_precise_end_time`
IS a real, high-impact bar-delivery-time knob.** Diagnostic only. No champion / dist change.

- Worktree: `kumo-qc-269confirm` · branch `diag/269-confirm` (off mainV2 `268ab4e`).
- Window: `START_DATE=(2025,1,1)` `END_DATE=(2025,1,17)`, `WARMUP_DAYS=560`. Champion_asis,
  one code path, identical except the single `self.settings.daily_precise_end_time` line.
- Driver: `scripts/confirm_269_daily_precise.py {A|B|C}` → applies the variant edit to
  `src/runtime/lean_entry.py::initialize()` (right after `set_warmup`), rebuilds dist into the
  throwaway `algorithm/v2_champion_asis`, greps the built dist to confirm the edit landed, runs
  `lean backtest`, extracts entry-buy SUBMIT/FILL from `*-order-events.json`.
- Every timestamp below is from a real BT `*-order-events.json` artifact over the data symlink.

## The #269 hypothesis under test
#262 parity gap = a 1-bar ENTRY-FILL-GRID offset: LOCAL fills entries NEXT-day-open (decide on
close T → fill open T+1); CLOUD fills SAME-day-open. Hypothesis: `daily_precise_end_time`
controls WHEN the daily bar reaches on_data → moves the entry MOO fill by one bar (same-day vs
next-day). We never set it in lean_entry → local uses its default.

## 3-variant result

| Variant | `daily_precise_end_time` | 2025-01-02 decision: SUBMIT (UTC) | → FILL (UTC) | Entry fill grid | Sharpe | Net% | DD% | Orders |
|---------|--------------------------|-----------------------------------|--------------|-----------------|--------|------|-----|--------|
| **A** (baseline) | UNSET (default) | 2025-01-02 21:00 (16:00 ET, close) | 2025-01-03 21:00 | **NEXT-day open** | 12.129 | 7.194 | 1.700 | 40 |
| **B** | `True`  | 2025-01-02 21:00 (16:00 ET, close) | 2025-01-03 21:00 | **NEXT-day open** | 12.129 | 7.194 | 1.700 | 40 |
| **C** | `False` | 2025-01-01 05:00 (00:00 ET, midnight) | 2025-01-03 05:00 | NEXT-day open (different schedule/names) | 0.092 | 0.383 | 3.900 | 46 |

(Submit 1735851600 = 2025-01-02 21:00:00 UTC; fill 1735938000 = 2025-01-03 21:00:00 UTC — raw
from the order-events artifact.)

## What moved, what didn't
- **A ≡ B, bit-identical** (same submit/fill times, same symbols, same trio). LEAN's DEFAULT
  for `daily_precise_end_time` is therefore **`True`** — daily bars end at the PRECISE market
  close (16:00 ET / 21:00 UTC), and on_data is delivered AT THE CLOSE. The MOO placed at close-T
  fills at open-T+1. This is local's current behavior.
- **C (`False`) changed a LOT**, but NOT in the hypothesized way:
  - SUBMIT moved from 21:00 UTC (16:00 ET close) to **05:00 UTC (00:00 ET, midnight)** — the
    legacy midnight-stamped daily bar. on_data now fires at midnight, a different point in the
    session calendar.
  - This shifted WHICH bar the engine fires on → entirely DIFFERENT symbols selected (V, TTWO,
    SQ, SPY, QQQ, PLTR, AMZN, GOOGL appear; CEG, TSM, SPOT, MRVL@close gone) and a DIFFERENT
    rebalance schedule (decisions on 01-01, 01-04, 01-09, 01-14, 01-15 vs A/B's 01-02, 01-14).
  - **The entry fill is STILL next-day-open** (e.g. submit 2025-01-01 → fill 2025-01-03;
    submit 2025-01-04 → fill 2025-01-07). In NO variant does a decision fill SAME-day.

## VERDICT
**`daily_precise_end_time` is NOT the same-day↔next-day entry-fill-grid knob.** Toggling it
True/False never produces a same-day open fill. It is the DAILY-BAR-DELIVERY-TIME knob: it moves
on_data delivery between the precise close (16:00 ET, default True) and midnight (00:00 ET,
False). Setting it False does not "advance" the fill to same-day; it shifts the whole decision
clock to midnight, re-selecting different names on a different schedule and crushing the trio
(Sharpe 12.13 → 0.09). The next-day-open MOO fill is invariant across all three.

- **Local's current default = variant A = B = `True`** (precise close, next-day MOO fill).
- The local NEXT-day-open fill is the standard LEAN MOO semantic (order at close-T → fill
  open-T+1), independent of `daily_precise_end_time`. So this setting cannot close the #262 gap.

## Next candidate for the #269 fix
The 1-bar offset is a **market-on-open-order fill-timing / order-submission-timing** question,
not a bar-end-time question. Local already submits the entry MOO at the close of decision-day T
(21:00 UTC) and LEAN fills it at the NEXT session's open. If cloud truly fills "same-day open",
the divergence is in WHEN cloud receives the daily bar relative to its open auction — i.e. the
cloud daily bar arrives BEFORE that day's open (cloud "decides at D open on the D-1 bar"),
whereas local receives the completed daily bar at D's CLOSE. Candidates to test next, in order:
1. **Order submission time vs the open auction** — confirm on a real cloud run whether the
   cloud entry MOO submit timestamp is at the session OPEN (09:30 ET) on the bar AFTER the
   decision bar, vs local's 16:00 ET CLOSE submit. If cloud submits at open it can hit the same
   day's open the local close-submit misses by one bar. (Pull the cloud `*-order-events.json`
   submit/fill timestamps via the v2 driver and diff against variant A here.)
2. **`extended_market_hours` / `fill_forward`** on the equity + universe subscriptions — whether
   cloud sees the open bar before local does.
3. The **scheduled-vs-on_data firing point**: the engine fires inside `on_data`; on cloud the
   daily bar timing relative to the MOO auction window may differ. Confirm cloud's on_data daily
   delivery timestamp (00:00 vs 16:00 vs pre-open) — that is the actual asymmetry to pin.

The honest read: **same code + same midnight-stamped data does NOT yield a same-day fill on
local under ANY `daily_precise_end_time` value.** The fix lives in MOO submission/fill timing,
not in this setting.
