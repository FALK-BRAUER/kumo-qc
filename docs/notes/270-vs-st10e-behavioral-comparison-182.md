# #182 decision input — behavioral comparison: phase-engine champion #270 vs sT10e

*Built 2026-06-02 for Falk's #182 lineage decision (which becomes main's production baseline).
Neutral framing — the data is presented; the call is Falk's.*

## What this is / is NOT

This is a **behavioral** comparison (how each strategy operates), NOT a head-to-head metric on the
same engine + period. The raw numbers are **not directly comparable**:

- **#270** (`champion_intraday_gapvol`, config_hash `e3b0c44298fc`): kumo-qc **phase-engine**, **local**
  LEAN, FY2025 (+ a 2025→2026-05 realize run). Numbers below are from commits 3d28251 / 8e59e16.
- **sT10e+R-B-v3** (pop_sharpe 1.2273): kumo-**trader sim** lineage, **cloud**, **PROVISIONAL /
  pending #182**, NOT reproduced in the kumo-qc phase engine (lineage drift — see CLAUDE.md / the
  `project_dvrank_dead_axis` + champion-chain notes). Numbers are as documented (s232a chain +
  HQ-cited cloud figures), NOT re-validated here.

So: compare the **behaviors**, treat the raw Sharpe/return as indicative-not-equivalent.

## The comparison

| Dimension | #270 phase-engine champion | sT10e+R-B-v3 (provisional) |
|---|---|---|
| **Exit model** | ONLY a Kijun-breach exit. **No profit-take / trim leg.** | Ladder trims ([15,30]→[20,40] rungs) + reversal exits + rotation + Kijun trail. **Has profit-taking.** |
| **Realized edge (FY)** | **−16.41%** (23 closed = ALL losers; observed FY2025) | positive (part of the +80.91% cloud FY; mostly realized via trims) |
| **Realized win rate** | **0%** (every closed trade a loser over 16mo) | **59.7%** |
| **Trades / FY** | ~32 positions, 23 realized exits | **665** realized trades |
| **Avg hold** | losers cut fast; **winners 16mo+ / never realized** | **~12 days** |
| **Compounding** | **None** — realized capital is net-negative; winners never book, so gains can't be reinvested | **Yes** — 665 realized trades, gains booked + redeployed |
| **Capital efficiency** | **Poor + self-jamming** — 10% flat sizing = ~10 slots; the never-exiting winners lock 9/10 slots → **26,684 cash-exhausted rejections** of qualified candidates over FY2025 → trading throttles to 32 positions/yr (the strategy strangles itself; see below) | **High** — 12d turnover redeploys capital ~continuously |
| **Give-back risk** | **HIGH + structural** — the Kijun trail on a +135% position sits MILES below price (Kijun lags). When a monster trend finally breaches Kijun it realizes FAR below the peak mark. The +135% paper materially **overstates** the eventual realized exit. | **Lower** — ladder trims lock gains at +15/+20/+30/+40% rungs before a full reversal; reversal exit catches tops |
| **Measurability** | **LOW** — value is 100% unrealized paper on a few trends; UNMEASURABLE on any finite window (winners censored at the boundary); even multi-year only books on a lagging-Kijun breach | **HIGH** — 665 realized trades give a directly-measurable, statistically-meaningful realized track |
| **Headline metric** | local FY2025 +11.35% total (ALL paper) / Sharpe 0.54 / DD 17% — but realized −16.4% | cloud FY +80.91% / pop_sharpe 1.2273 / DD n/a (provisional, sim-lineage, unreproduced in phase engine) |

## The core behavioral difference

**#270 cuts losers and lets winners run with NO profit-taking** → it realizes only its losers
(−16.4%) and accumulates never-booked paper winners. Over a 16-month observed run (2025→2026-05),
it realized **zero** winners; the 9 open positions rode to +8% to +135% and never breached Kijun.

**sT10e (and its s232a-chain lineage) lets winners run WITH a profit-take leg** (ladder trims +
reversal exits) → it realizes + compounds, turning over capital every ~12 days with a 59.7% realized
win rate.

A strategy that books **−16.4% realized** and holds the rest as paper that erodes to a lagging Kijun
is a fundamentally different — and harder-to-trust — bet than one that **realizes and compounds** a
measurable edge.

## The portfolio-jam (verified 2026-06-02 — execution is correct, the result is diagnostic)

Falk flagged "only 23 closed trades in a full year looks like a misconfiguration." Investigated:
the execution is **correct and faithful** (champion source `position_pct=0.10` = "fixed-canonical";
built main.py used exactly that; 64 orders reconcile = 55 fills [32 entries + 23 exits] + 9 cancelled
GTC protective-stops; archive captured all 32 positions). The low count is **real and emergent**, not
a bug:

- 10% flat sizing → max ~10 concurrent positions.
- No profit-take → the 9 winners ride all year, **locking 9 of 10 slots**.
- → **26,684 cash-exhausted rejections** of qualified candidates (the signal/universe is healthy —
  plenty qualify; the bottleneck is locked cash). Entries throttle to 32 positions/year.

This **compounds** the no-profit-take problem: #270 doesn't merely fail to *realize* winners — the
10%-sizing × no-profit-take interaction **jams the whole portfolio**, halting new entries as winners
accumulate. (It also explains the panel-vs-continuous trade-count gap: the 6 panels each RESET cash →
74 trades; the one continuous portfolio jams → 32.) A profit-take/trim leg fixes BOTH failure modes
at once — it realizes gains AND frees slots to keep trading.

## HQ's read (to develop, not decide — Falk's call)

#270 **as configured** is not a viable production champion: negative realized edge, capital locked
16mo+, paper edge that structurally erodes to a lagging Kijun on the eventual exit. The forward path
is let-winners-run **WITH a profit-take leg** (the "runner" model: trim enough to compound + measure,
keep a runner for the tail) — i.e. graft sT10e's trim/reversal behavior onto the phase-engine entry.
But that is a strategy-design decision for Falk.

## Open follow-ups (tracked, non-blocking)

- **Quantify the give-back**: estimate each #270 winner's eventual realized exit = its Kijun level at
  reversal (not the peak mark). Needs per-position Kijun in the archive (not currently captured).
- **Observability fix**: #270 positions that drop from the coarse universe appear to mark STALE
  internally (BT statistics Net flat +11.35% while raw marks grew +84→+135%). Tracked separately.
- **exit_reason capture**: local order-events archive logs `exit_reason=None` (behavior inferred from
  order TYPES — unambiguous here, but the tag should be captured). Tracked separately.
