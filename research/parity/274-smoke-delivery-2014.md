# #274 SMOKE-BT — intraday 5-min delivery parity (cloud vs local) — CLEAN

**Question (the first risk gate):** does QC cloud deliver 5-min bars at the same wall-time as
local-Docker LEAN? (The intraday analogue of the #268 daily-delivery bug that produced the
phantom 1-bar entry-fill offset.)

**Method:** a minimal 5-min-consolidator algo on AAPL (the 2014 LEAN sample, present + identical
both sides — date/ticker-agnostic for a delivery-mechanism check). Each consolidated bar logs/plots
`offset_sec = algo-clock-at-delivery − bar.end_time` (0 ⇒ delivered exactly at bar close).
Window 2014-06-05..06. Local: Docker lean-CLI (engine v2.5.0.0). Cloud: QC bt 095a3f2378a000c67dd0e012a4295d6d.

**Result — bit-identical, both engines:**

| | bars | offset_sec (all) | delivery |
|---|---|---|---|
| LOCAL (Docker) | 156 | 0.0 | algo_time == bar_end, every bar (e.g. bar[09:30,09:35) delivered AT 09:35) |
| CLOUD (QC) | 156 | 0.0 | identical — 156 pts all offset 0.0 |

**Verdict: the #268 daily-delivery divergence has NO intraday analogue.** Cloud and local deliver
5-min bars on the identical clock (exactly at bar close). Confirmed empirically (both runs) AND by
the LEAN source (~/reference/Lean @ 96a670a9): `LeanData.UseStrictEndTime` returns FALSE for
`increment <= Time.OneHour` (Common/Util/LeanData.cs:1518) → the strict-end-time logic that caused
#268 is DAILY-ONLY by construction; sub-daily `TradeBar.EndTime = Time + Period` unconditionally
(TradeBar.cs:109). The intraday execution clock is safe to build the two-clock split on.

**Note:** cloud `/backtests/chart/read` requires a `count` + a time-range (`start`/`end` unix) to
return the full series — without them it returns 1 point (the #243 flaky-endpoint cause; now solved).
