# FOR_FALK — overnight run 2026-06-02 (branch feat/276b-1-intraday)

Falk — what shipped while you slept, why, and what's waiting on you. All committed + pushed
(branch tip below). Nothing merged to main; champion still NOT merged (your call).

## What shipped (4 clean commits, all pushed)

1. **Run-class protocol** (`6ae4290`) — you caught real slack: the substrate runs were reported
   with Sharpe/Ret/DD like *validation grades*, but they're *substrate-generation* (mine fuel,
   full-year-OK, metrics-not-grades). Now every run DECLARES `run_class` (validation |
   substrate-generation) in result.json; CONVENTIONS + archive README document the distinction;
   the 5 prior regimes retro-flagged. No redo of the runs (as you said).

2. **FY2020 COVID-crash, 6th regime** (`38aafa5`) — +24.5%/Sharpe 0.881, 19 closed + 8 censored.
   Later extended with **FY2018 correction** (`7b6f41a`, −10.4% — sharp-correction-without-recovery)
   and **FY2019 bull** (`70470bc`, −4.2% — gap-edge underperforms a steady grind-up). The
   **8-regime** learn-substrate (FY2018-2025: correction/crash/grind-bear/recovery/bull/OOS) is now
   COMPLETE + durable (committed off-machine — QC purges backtests in hours). Key mine signal across
   regimes: the gap+confirm edge WINS in crash-recovery (gaps to catch) but LOSES in
   correction-without-recovery + steady-bull (no gaps) — it's volatility/gap-dependent, not a
   steady-trend strategy. FY2020 funnel shows
   the crash regime-gate blocked 62 days (protected through COVID, caught the recovery gaps) — a
   genuine regime signal for the mine vs FY2023's choppy −11.8%.
   - Caught a sharp lesson: QC purges `runtimeStatistics` (the funnel channel) in **~25min** — much
     faster than orders (hours). Fixed: funnel is now captured INLINE at run-time (fail-loud on
     empty, never faked). Documented in CONVENTIONS.

3. **Cloud-tag validator table** (`18c9307`) — the turnkey cloud-side of the #303 (c) cross-check
   (per-trade decision_score + cond_0..7 + outcome across all regimes), so the lab's 5-min-vs-cloud
   honesty-check is one join when the mine runs.

4. **FIX3 symbol-key migration** (`7b0d967`) — behavior-neutral hardening (HQ-approved gap-filler
   while the mine's gated). Unified all 15 symbol-resolution sites onto one `canonical_symbol_key`
   (extracted to `src/engine/symbol_key.py`), killing the recurring case-bug class (the open-coded
   `.value` UPPERCASE vs `.value.lower()` seams). PROVEN behavior-neutral two ways: config_hash
   UNCHANGED + orders BYTE-IDENTICAL (pre/post cloud BT, 46 orders Q4 2025). suite 1152 green.

## The pivot (your call, mid-session): COPY → LEARN
Stop replicating George's BCT screen; LEARN which conditions/context predict good trades. The
8-regime substrate is the learn-fuel. The sweep is HELD. The mine (#303) ingests the substrate.

## ⭐ THE LEARN RESULT — phase-1 first-cut on the traded set (`b622e59`, PHASE1_FINDINGS.md)
You asked "why idle" — you were right, there was unblocked goal-work I'd mis-scoped. Mined the
committed traded substrate (no lab-paste needed). The headline:
- **George's 8 conditions do NOT separate winners from losers** (score 7.32 on BOTH sides) — the
  empirical case for copy→learn. Replicating the screen perfectly would NOT pick better trades.
- **The outcome is exit-path-binary:** losers all stop out (~−9%, one loss mode); winners ride
  uncapped (closed 1% win vs censored-open 88% win). The edge = "which names don't stop out."
- **decision_rank (DV/liquidity) predicts the riders, robustly:** top-DV beats bottom-DV win-rate
  in 4/4 testable regimes (+6 to +33pp). **The first learnable edge — weight high-DV-rank.**
- **#322 hypothesis ready:** BCT screen picks the pool; the learned signal RANKS within it by DV.
hzgffl24's rigorous mine + the untraded counterfactual (your paste) confirm + extend this.

## What's WAITING ON YOU (the one real gate)
**Paste the hzgffl24 lab-resume.** The #303 phase-1 mine (winners-vs-losers on the 6-regime traded
set) is STAGED, gate-free, SAFE — it reads the committed substrate, no backfill, no 160GB RAM risk
(only phase-2's 5-min scoring hits that gate). hzgffl24 is self-gated on your literal paste (post-OOM
conservative). Your one paste fires the mine. HQ (fintrack) has the one-liner for you.

Decisions HQ made under delegated authority (you can veto):
- **Untraded counterfactual = (c)**: the lab scores it from its own 5-min substrate (one consistent
  vendor — the local-daily generator is DEAD, over-counts ~6×), validated against the cloud-tags.
- **RAM gate** relaxed to HQ-level (phase-2 engineering task, not your checkpoint).

## When the mine fires
I pivot to: the cloud-tag cross-check (validator data ready) + the #322 OracleSignal learned-signal
wiring (deferred as speculative until the mine's output shape is known).

Branch tip: `7b0d967` · suite 1152 passing · worktree kumo-qc-276b1.
