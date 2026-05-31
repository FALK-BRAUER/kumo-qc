# #253 Phase-2 — Score-Aware Sizer Measurement (the X/4 finally BINDS on SIZE)

**Date:** 2026-05-31 · **Branch:** `feat/score-tier-sizer` · **Environment:** LOCAL LEAN
(conformed-coarse FY2025, WARMUP_DAYS=560, RAW, 0% failed data requests). **NO cloud spend.**
Local is an APPROXIMATION (cloud = ground truth); these are own-merits deltas vs the LOCAL
baselines run on the IDENTICAL code path + data, NOT vs the 0.778 adjusted-data champion.

## What this measures

The #253 Phase-1 doc (`253_phase1_entry_measurement.md`, lines 37–39) FLAGGED the exact next step:
> "to make C2 actually bind on the fired set, the gate's X/4 score would need to drive SIZING (the
> methodology's 4/4-full · 3/4-75% · 2/4-50% tiers) — i.e. a methodology SIZER consuming
> `qc._entry_confirm`, which is Phase-2 scope (the baseline `flat_pct_heatcap` ignores the score)."

This is that sizer. `champion_entry_sized` = `champion_entry` stack VERBATIM with sizing swapped
`flat_pct_heatcap` → `ScoreTierHeatcap` (the published X/4 → methodology tiers: 4/4 full · 3/4 75%
· 2/4 50% · <2 no-entry, composed WITH the same committed-cash gross heat-cap). Base
`position_pct=0.10` == champion_entry's flat size, so a 4/4 name sizes IDENTICALLY to flat; the
ONLY behavioral delta is that 3/4 and 2/4 names size DOWN.

## Configs

| Config | config_hash | Sizing |
|---|---|---|
| `champion_asis` | `e573e84b1ce1` | flat_pct_heatcap — the −0.616 BLIND-ENTRY baseline (no entry trigger) |
| `champion_entry` | `999ec7745455` | flat_pct_heatcap — entry-confirm GATE, X/4 published-but-IGNORED |
| `champion_entry_sized` | `90c8fc6103ca` | **score_tier_heatcap — the X/4 BINDS on SIZE (methodology tiers)** |

champion_asis + champion_entry UNCHANGED (their hashes preserved). Only delta vs champion_entry =
the sizer (controlled measurement).

## HEADLINE — Full FY2025

| Config | Sharpe | Net % | Max DD % | Orders |
|---|---|---|---|---|
| champion_asis (blind-entry baseline) | −0.616 | +3.899 | 3.4 | 75 |
| champion_entry (un-sized entry-confirm) | −1.016 | +0.194 | 4.4 | 70 |
| **champion_entry_sized (score-driven sizing)** | **−1.321** | **−2.196** | **4.9** | **93** |
| Δ vs −0.616 baseline | **−0.705** | −6.095 | +1.5 (worse) | +18 |
| Δ vs −1.016 (un-sized entry) | **−0.305** | −2.390 | +0.5 (worse) | +23 |

Artifact: `algorithm/champion_entry_sized_bt/backtests/2026-05-31_19-38-13/`
(STRATEGY_INIT hash `90c8fc6103ca` = champion-entry-sized confirmed in the BT log; Win Rate 21%,
Loss Rate 79%, Avg Win +0.43% / Avg Loss −0.26%).

## VERDICT (own merits) — does the score binding help? NO, it degrades further.

At the methodology-canonical tiers (4/4=1.0, 3/4=0.75, 2/4=0.50, min_score=2, base 0.10),
score-driven sizing makes risk-adjusted return WORSE, not better: Sharpe **−1.321** vs −1.016
(un-sized entry, **−0.305**) and vs −0.616 (baseline, **−0.705**); return goes negative (−2.20%),
drawdown rises to 4.9%. This is a clean NEGATIVE result, reported honestly (NOT spun, NOT
0.778-matched). **The X/4 binding on size does not earn its place at default tiers on this local
data.** champion_asis stays the champion regardless.

### Why it degrades (structural, consistent with the Phase-1 finding)
- The order count RISES (70 → 93): downsizing 3/4 and 2/4 names to 75%/50% frees cash under the
  heat-cap, so MORE marginal names get filled (the cap truncates later). The extra names are the
  lower-conviction (2/4-ish) entries — and they are net-LOSERS (21% win rate). So the tier sizing
  both (a) shrinks the winners' capital share AND (b) admits more marginal losers with the freed
  cash. Both effects push Sharpe down.
- This is the SAME root cause the Phase-1 doc identified from the other side: with C1+C4 mandatory,
  the X/4 distribution is dominated by 2/4–3/4 names whose marginal P&L is negative on this data.
  Sizing by that score amplifies the wrong tilt rather than concentrating into genuine 4/4 edge —
  because the 4/4 edge is not actually present in the FY2025 local sample at these params.

### Levers a Phase-3 sweep could test (NOT run here — own-merits single config measured)
- `min_score=3` (enter only 3/4+) to cut the marginal-loser admission the freed cash enables.
- Steeper tier curve (e.g. 1.0/0.5/0.25) to starve 2/4 names instead of merely halving them.
- These are sweep axes already exposed by `ScoreTierHeatcap.Params.space()` — a discovery run can
  explore them. The canonical-default measurement (this doc) is the honest baseline they improve on.

## Reproduction (NO cloud)

```bash
# build the dist for the score-aware variant (pins to the source commit)
PYTHONPATH=src python build/cloud_package.py strategies.champion_entry_sized
# stage dist into a LEAN project + run FY2025 (dist defaults 2025-01-01..2025-12-31, WARMUP 560)
mkdir -p algorithm/champion_entry_sized_bt && cp dist/*.py algorithm/champion_entry_sized_bt/
DOCKER_HOST=unix:///Users/falk/.docker/run/docker.sock lean backtest algorithm/champion_entry_sized_bt
```

## Caveats / integrity
- LOCAL approximation only; cloud is ground truth (charter). Own-merits delta on the local code
  path + conformed-coarse data, NOT a deployable verdict.
- Every number is from the real LEAN backtest output (no fabrication; the data-integrity rule).
  The `champion_entry_sized_bt` backtest dir holds the source artifact (STRATEGY_INIT hash matches
  the built dist `90c8fc6103ca`).
- champion_asis hash `e573e84b1ce1` UNCHANGED (asserted in `tests/strategies/test_champion_entry_sized.py`).
