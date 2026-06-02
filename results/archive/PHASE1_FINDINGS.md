# #303 phase-1 FIRST-CUT — winners-vs-losers on the traded substrate (2026-06-02)

A first-cut mine on the committed 8-regime traded set (`scripts/mine_phase1_traded.py`,
survivorship-aware). NOT the lab's rigorous version — hzgffl24 owns that + the untraded
counterfactual (Falk-gated). But the phase-1 question (which context separates winning from losing
trades) is answerable on the committed traded data NOW, so here's the head-start.

**Valid subset: FY2021-2025, 119 labeled trades, 31% winners** (FY2018-2020 EXCLUDED — see data gap).

## Finding 1 — George's 8 conditions DO NOT separate winners from losers (validates copy→learn)
Every BCT condition's hit-rate is near-identical between winners and losers (Δ ≤ 6pp, most 0-2pp),
and `decision_score` is **7.32 for BOTH** winners and losers. The 8-condition screen is
**table-stakes, not predictive** — every trade already passed it (score≥7), so it can't explain
which of those trades won. **This is the empirical case for the pivot: perfectly replicating
George's screen would not pick better trades.** The signal must come from context the screen ignores.

## Finding 2 — `decision_rank` (DV/liquidity rank) IS a real separator (the candidate edge)
Winners median rank **219** vs losers **527**. By rank-tercile:
| tercile | win-rate | mean_ret |
|---|---|---|
| top-DV (most liquid) | **48%** | **+12.9%** |
| mid | 28% | −1.9% |
| low-DV (least liquid) | 23% | −0.2% |
The most-liquid third wins ~2× as often and returns +12.9% vs ~flat. **A learnable edge the BCT
screen ignores** — the mine's first concrete hypothesis for a learned predictor: weight toward
top-DV-rank candidates. (Caveat: rank correlates with other things; the rigorous mine controls for them.)

## Finding 3 — the gap-magnitude mechanism does NOT cleanly reproduce at trade level
The 8-regime aggregate suggested volatility/gap-dependence. At the trade level (valid subset) it's
weak: win-rate rises slightly with gap (29%→31%→39%) but mean_ret does NOT (+5.5%→+5.0%→+0.1% — the
biggest gaps mean-revert toward flat). So "bigger gap = better trade" is NOT the mechanism. The
regime effect is real (FY2021/24 won, FY2023 grind-bear lost) but it isn't a simple gap-size rule.
**Confirms HQ's don't-over-read caveat: the aggregate suggested, the trade-level did not validate
the simple mechanism.** The rigorous mine must find the real conditioning.

## ⚠️ DATA GAP — FY2018-2020 are entry-context-only (NOT outcome-usable)
Censored m2m coverage: FY2018 0/6, FY2019 0/8, FY2020 0/16 — local daily 2018-2020 is absent, so
open-at-end winners have no mark → if included they show an artificial ~0% win-rate (survivorship:
winners dropped, losers kept). So those 3 regimes are usable for ENTRY-CONTEXT distributions but
NOT winner/loser outcomes. **To make them outcome-usable: source 2018-2020 daily for the m2m mark,
OR re-run with an end-date extended past the open positions' exits so they close (realized).** Until
then, outcome analysis is FY2021-2025 only (119 trades). Flagged for the substrate's consumers.
