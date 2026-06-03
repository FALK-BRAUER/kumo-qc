# #339 — #270 cloud-candidate config (recorded 2026-06-03, overnight)

**Status: CANDIDATE recorded, NOT merged.** Merge to mainV2 is STAGED, awaiting (a) Falk's explicit
morning GO and (b) S1's 4-quarter robustness panel passing gates ①(4+/6 positive) ②(no window>50%).
Per the dist-pin rule, the eventual merge must be a **merge-commit** (never squash/rebase) so
`dist/_manifest.json` git_commit provenance doesn't dangle.

All configs flag-ON (`continuous_weekly=True`, the #336 corrected weekly) on the #270 intraday base.
**Headline metric = FLOOR-PROXY** (open winners re-marked at their cloud-bottom trailing stop = the
bankable total), not realized (censored-low) or M2M (censored-high). See `scripts/floor_proxy.py`.

## THE PICK — S1 (risk-normalized capacity), config_hash `65c0cf447168`
```
SweepConfig(choices=(
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard",       "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
), continuous_weekly=True)
```
FY2025: M2M +27.69% · realized −15.2% · **floor-proxy +21.13%** · Sharpe **1.025** (≈ G3's 1.079) ·
36 trades · 17 names open. Diversified, smoother, lower single-name risk. **Recommended cloud-candidate.**

## CONCENTRATED ALTERNATIVE — combined-cloud, config_hash `de53399c8125`
```
SweepConfig(choices=(
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard",       "cloud_adherence_trail", (), 0),
), continuous_weekly=True)   # sizing = base FlatPctHeatcap(0.10)
```
FY2025: M2M +28.98% · realized −16.9% · **floor-proxy +28.15%** · 18 trades · 8 names open.
Higher bankable but HOOD-concentrated (floor +$19.8k single-name) → fragile. Documented-alt only.

## Why these (the #339 arc, all on the corrected-weekly base)
- The binding exit is the **Kijun protective stop + KijunG3 exit_hard** (BCT-3 worst, 24% win) →
  moved BOTH to **cloud-bottom** (CloudProtectiveStop + CloudAdherenceTrail) = G3's winning mechanic.
- Exit-swap-only inert (Kijun stop dominates); rotation **HURT** (−22.8% realized, churns recoverable
  laggards); profit-take **parked** (tail-truncating). **Sizing (capacity) is the live lever.**
- Floor-proxy proved #270's edge is **GENUINE** (+21–28% bankable) — the negative realized is a
  let-winners-run **censoring artifact**, not a negative edge. Fork (a): keep optimizing #270.

## Lineage / canonical-hash invariants (unchanged)
- flag-OFF base → `e3b0c44298fc` (prod, unchanged). flag-ON base → `4c2fc8e40607`.
- New phases (all on `feat/276b-1-intraday`): CloudProtectiveStop, CloudAdherenceTrail, CloudBreachExit,
  MultiMetricConfirmExit, Rotation, RiskBasedSize + the exit_hard/exit_rotation/protective_stop sweep-axis
  unlock + `Window.runnable_locally`.

## Open / pending (Falk-morning)
- S1 4-quarter robustness panel (the crowning gate) — running.
- RUN S2 (RiskBasedSize, `847e70eb93ea`) — built, queued.
- mainV2 merge — staged, awaiting GO + panel.
- 2026 data backfill (Falk-decision, RAM-safe) — pending.
