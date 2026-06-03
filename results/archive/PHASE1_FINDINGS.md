# #303 phase-1 FIRST-CUT — winners-vs-losers on the traded substrate (2026-06-02)

A first-cut mine on the committed 8-regime traded set (`scripts/mine_phase1_traded.py`,
survivorship-aware). NOT the lab's rigorous version — hzgffl24 owns that + the untraded
counterfactual (Falk-gated). But the phase-1 question (which context separates winning from losing
trades) is answerable on the committed traded data NOW, so here's the head-start.

**Valid subset: FY2021-2025, 119 labeled trades, 31% winners** (FY2018-2020 EXCLUDED — see data gap).

## Finding 1 — the 8 conditions do not FURTHER-separate winners WITHIN the traded set
Every BCT condition's hit-rate is near-identical between winners and losers (Δ ≤ 6pp, most 0-2pp),
and `decision_score` is **7.32 for BOTH** winners and losers. **Precise claim (HQ):** all traded
names already passed score≥7, so they're similar on the conditions → the condition-variance washes
out *within the traded set*. This does NOT mean the screen is worthless — the screen's value is in
**SELECTION** (getting names into the candidate pool vs the 6k universe), which is the
**untraded-counterfactual question (phase-2, Falk-gated)**, not tested here. Consistent with the
validated BCT thesis (alpha in the screen; further curation modest). The actionable phase-1 read:
**the further-edge must be learned ELSEWHERE than the 8 conditions** — they don't rank within the pool.

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
NOT winner/loser outcomes. **Fix HELD (not rushed)** — the naive end-date-extend POLLUTES the regime (new entries fire in the
extension window) and a yahoo/fmp price-fetch mixes vendors vs the QC entry_px. The CLEAN version
(HQ, for hzgffl24's rigorous pass or a deliberate data-acquisition): **extend end_date BUT DISABLE
new entries in the extension window** → the open tail closes to realized outcomes without adding
polluting entries, no vendor-mix. Until then, outcome analysis is FY2021-2025 only (119 trades).
Flagged for the substrate's consumers.

## Finding 4 — single loss mode (the protective stop); the 1%/88% split is PROVISIONAL illustration
ALL 78 valid-subset closed trades exit via `stop_market` (mean ret −9.2%) — there is ONE realized
loss mechanism, the ~−9% protective stop. **Framing discipline (HQ): do NOT headline the
"closed 1% win / censored 88% win" split — it is PARTLY STRUCTURAL + PROVISIONAL.** "Closed" is
stopped-by-definition; "censored" wins are *unrealized* end-of-window M2M marks, not realized. So
1%/88% illustrates the fat-tailed shape (capped losses ride/uncapped winners) but is NOT a
defensible magnitude until the rigorous lab mine supplies realized counterfactual outcomes. The
DURABLE claim is Finding 5 (the rank separation), not this split. The qualitative read stands: the
edge reduces to **which entries avoid the stop and ride**; the magnitude is provisional.

## Finding 5 — decision_rank robustly predicts ride-vs-stop, ACROSS regimes
Censored-winners median rank **252** vs closed-losers **534** (the same rank signal as Finding 2,
via the exit-path lens). And it holds WITHIN each testable regime (top-half vs bottom-half DV):
| regime | top-DV win / ret | bot-DV win / ret | Δ |
|---|---|---|---|
| FY2021 | 67% / +20.5% | 33% / −2.0% | +33pp |
| FY2022 | 40% / +11.6% | 27% / −0.1% | +13pp |
| FY2023 (grind-bear) | 19% / −7.2% | 12% / −0.1% | +6pp |
| FY2024 | 62% / +18.0% | 33% / +0.3% | +29pp |
Top-DV beats bottom-DV in **4/4** regimes — even in losing FY2023. **Not a pooled artifact; a
regime-robust learnable edge.** This is the mine's strongest concrete predictor-hypothesis:
liquidity/DV-rank conditioning on top of (not replacing) the BCT screen.

## Synthesis for the learned signal (#322)
The BCT screen selects the CANDIDATE POOL (necessary, score≥7) but does not RANK within it. The
learnable edge sits in the ranking: **prefer high-DV/liquidity-rank candidates** (they ride to
winners ~2× more, robustly across regimes), and the protective stop caps the losers at ~−9%. The
learned predictor (#322 OracleSignal) should weight DV-rank; the rigorous mine (hzgffl24) confirms
+ finds any additional conditioning the first-cut missed, and the untraded counterfactual tests
whether the edge generalizes beyond the names actually traded.

---

## ⚠️ OUT-OF-WINDOW RESULT (2026-06-02) — the DV-rank edge did NOT generalize

The synthesis above (DV-rank = "regime-robust learnable edge", 4/4 in-sample mining regimes) was
tested OUT-OF-WINDOW through the actual sweep machine (#214) — the #322 OracleSignal DvRankPredictor
as a real strategy phase, run on the 6 FY2025 bi-monthly panels (the same engine + gates as a
champion validation). Board: `results/sweeps/dvrank_grid/leaderboard_local.csv` (commit 4e5b072).

**It failed.** cap250 (the DV-rank booster) ranks BELOW uncapped (the baseline, all score≥7):

| config | composite | sharpe_mean | ret_mean | gate ① (4+/6 pos) | gate ② (<50% single-window) |
|--------|-----------|-------------|----------|-------------------|------------------------------|
| uncapped (baseline) | **+0.0953** | 0.979 | 3.10% | FAIL (3/6) | FAIL (w5 ~50%) |
| cap250 (DV booster) | −0.0983 | 0.967 | 4.66% | FAIL (3/6) | FAIL (w5 ~82%) |

**Two learns:**
1. **DV-rank is a DEAD AXIS out-of-window.** The cap250 booster amplifies the one good window (w5
   Sep-Oct +22.8% vs baseline +14.5%) AND the variance (sharpe_std 3.10 vs 2.30) → lower stability
   → lower composite. Separable in in-sample MINING (top-vs-bottom DV, 4/4 regimes) ≠ robust as a
   windowed-BT RANKING signal. **In-sample separability did not survive out-of-window selection.**
2. **The base is also weak.** Even the BASELINE fails ①② (3/6 positive, w5-carried). This DV-rank
   candidate's FY2025 edge is single-window-carried — a BASE problem, not just a booster problem.
   Do NOT swap another booster onto a weak base.

**Methodology lesson:** an in-sample mining edge (top-decile beats bottom-decile across regimes) is a
NECESSARY but NOT SUFFICIENT signal. It must be re-tested as a real phase through the windowed sweep
before it can be claimed as a strategy edge. The mine generates HYPOTHESES; the sweep VALIDATES them.
The DV-rank hypothesis was generated (strong) and validated (failed) — the pipeline working correctly.
