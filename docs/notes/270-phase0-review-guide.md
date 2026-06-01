# #271 Phase-0 Docs — Reviewer's Guide (for Falk)

Branch `docs/270-phase0-intraday-arch`. **Docs only, no code, no build.** This is the gate before Phase-1.

## What to eyeball (the 5 load-bearing decisions)
1. **Two-clock engine** — daily decision clock (`on_daily_bar`: universe/signal/regime/ranking → candidates after close T) + intraday execution clock (`on_intraday_bar`: confirm/size/fire/stop/exit on T+1's 5-min bars). One resolution-tagged `PHASE_ORDER`, subsets PRECOMPUTED at config-build (not per-tick filtered). → ARCHITECTURE.md §1.9, §4, §10; PHASES.md PHASE_ORDER.
2. **OrderIntent fire seam** — phases emit `OrderIntent{order_type}`; only FIRE_* calls the QC API. Retires hardwired market-on-open. → ARCHITECTURE.md §4; PHASES.md §6, §15.
3. **Fail-loud REQUIRED_PHASES incl. entry+exit** — `REQUIRED_PHASES=(universe,signal,sizing,entry,exit)`; no implicit execution default → `DegradedConfigError`. champion_asis → retired FIXTURE. → ARCHITECTURE.md §1.10, §12; CONVENTIONS.md; PHASES.md init-validation.
4. **GH#25 intraday-Tenkan LOCKED / #253 daily Gate-2 RETIRED** — confirm mechanic = intraday-Tenkan reclaim + volume on completed 5-min bars + a pre-flight staleness gate (gap-up discipline). → ARCHITECTURE.md §10; PHASES.md §5; GH25 spec header.
5. **#262/#268 MOO-parity RETIRED** — the 1-bar offset was a symptom of the blind-open model; parity recast onto the intraday clock. → ARCHITECTURE.md §10; CONVENTIONS.md Parity.

## Per-doc changes
- **ARCHITECTURE.md** — +principles 9/10/11 (two-clock, fail-loud phase stack, look-ahead); §4 engine rewritten (two entry points, precomputed subsets, staleness gate, fire seam, DegradedConfigError); +§10 execution model (full); +§11 test strategy (SG1–7 + per-phase behavioral/fail-loud/outage + mutation-bite + G-DATA); +§12 failure strategy (taxonomy: DegradedDataError + new DegradedConfigError, no silent execution default, both-clocks-symmetric, degradation-observable).
- **PHASES.md** — PHASE_RESOLUTION on interface + ctx.clock; §1 universe daily-clock; §5 entry_selection REQUIRED+intraday (pre-flight + intraday-Tenkan; daily Gate-2 retired); §6 entry_timing REQUIRED+intraday (order_type seam; MOO retired); §15 exit_hard intraday stop-market; two-clock PHASE_ORDER ([D]/[I]); §20 rebalance two-clock scheduler; init-validation REQUIRED_PHASES + clock coherence.
- **CONVENTIONS.md** — fail-loud phase stack + champion-vs-fixture; parity #262/#268 retired; dist-tracks champion_intraday (asis=fixture); worktree isolation + explicit-git-add; look-ahead-completed-bars-only.
- **GH25_intraday_design_spec.md** — Design→APPROVED; v2-engine reconciliation mapping; permissive-on-insufficient-data → fail-loud.
- **CLAUDE.md** — execution-model section; 8-condition score = daily SIGNAL only, entry/exit intraday.

## Not in scope (deliberately)
No code, no new phase impls, no engine changes — those are Phases 1–5. The docs describe the TARGET; the build follows on your approval. champion_asis is untouched (still the fixture); dist unchanged.

## Late additions (HQ + Falk, post-first-review — all docs-only)
- **CONVENTIONS "Execution environment"** — kills the Docker confusion: local LEAN = `lean` CLI in the `quantconnect/lean` Docker image (engine **v2.5.0.0**) with LOCAL data providers (local PROVIDERS, Docker ENGINE — NOT "no Docker"). + the **dual execution model**: Docker lean-CLI = FAITHFUL runtime (tests/validation/parity/cloud-confirm); direct-LEAN = SWEEP runtime (speed), NOT set up yet, gated by a one-time **direct≈Docker reconciliation** (a new parity surface, cross-ref #214) before sweep results are trusted. + the v2.5.0.0 reference-clone pin (cloud version to be confirmed from a cloud log, not assumed equal).
- **ARCHITECTURE §11.1 SG8 — NO FILLS ON THE DAILY CLOCK** (Falk, explicit, now standalone): the daily clock decides only, fires zero orders; any daily-clock fill → fail-loud. The structural guarantee the blind-daily-MOO model can't creep back.

## Gemini review changes (APPROVE-WITH-CHANGES, folded in — docs-only)
- **SG9 NO STATE BLEED** (ARCHITECTURE §11.1) — intraday confirmation/pending-intent state cleared at session end; T+1 starts clean on T's candidates; a stale unconfirmed entry must not fire a day late. Test in #278.
- **PHASES.md data-flow contradiction FIXED** (§2) — signal now QUALIFIES → `ctx.signal_scores` only (does NOT rank, does NOT emit intents); canonical handoff signal→ranking→entry_selection→entry_timing→sizing made explicit + matrix-consistent. Noted that the retired `champion_asis` bct_score_full COLLAPSED signal+ranking+intent (the fixture shortcut), and the intraday champion restores the clean separation.
- **Known build risks** (ARCHITECTURE §13) — dynamic subscription+consolidator LIFECYCLE = highest risk (seed-on-subscribe, explicit-remove-or-leak, churn) → #275; intraday state mgmt → #274/#276; fill-fidelity higher BT-vs-live divergence → flag at #277 re-baseline.

## On approval
PR `docs/270-phase0-intraday-arch` → HQ gate → merge → Phase 1 (#272 fail-loud gate, #273 worktree isolation, #274 two-clock split + smoke BT). #279 closeout sweeps the whole codebase for coherence after Phase 5.
