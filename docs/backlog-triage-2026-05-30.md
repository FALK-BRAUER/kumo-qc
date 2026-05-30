# Backlog Triage — 2026-05-30

Snapshot after closing 5 clear-done issues. **93 open** remaining, categorized below for a later go-through.

**Closed this sweep (5):** #207 (cleanup done+verified), #206 (superseded by #207), #125 (parquet rebuild done), #115 (E40d cloud-val FAIL verdict reached), #124 (B0d parity diff done).

**Governing fact:** Two architecture pivots today reset the board.
- **ARCH2 v2 (#208–216)** is the live track — supersedes the v1 engine epic (#187–207) AND the experiment-grind model (#128–185).
- Under v2, experiments stop being standalone tickets and become *phase candidates* enumerable via `sweeps/`. Confirmed-positive ideas become `feat/phase-*` library work; rejected ones are recorded in `results/bt-results.csv` and closed.

Verdicts below sourced from #110 final comments + session handoffs. **Anything marked CLOSE should be verified against bt-results.csv/git before actually closing** — do not close on this doc alone.

---

## A. KEEP — active / forward-looking (do not close)

| # | Title | Why keep |
|---|-------|----------|
| 208 | [EPIC] Structure v2 | Live epic |
| 209 | ARCH2-0 scaffold + docs | HQ in-flight (kumo-qc-arch2) |
| 210 | ARCH2-1 type-safe engine | MINE next (post ARCH2-0) |
| 211 | ARCH2-2 AST build | mine |
| 212 | ARCH2-3 carve | mine |
| 213 | ARCH2-4 tooling/oracle | mine |
| 214 | ARCH2-5 sweeps + results ledger | mine |
| 215 | ARCH2-6 CI gates | mine |
| 216 | ARCH2-7 cutover | mine |
| 2 | Phase 5 paper live deploy | Future milestone — keep |
| 25 | Phase 5 intraday (minute/Tenkan/stop) | Phase-5 feature; deep code-review history; keep for later |
| 152 | Deprecate kumo-prod.db/SQLite/Yahoo | Real cleanup, parquet=truth; partly done, verify |

## B. SUPERSEDED by ARCH2 — close as superseded (v1 engine epic)

#200 (v1 EPIC), #187, #188, #189, #190, #191, #192, #193, #194, #195, #196, #197, #198, #199, #201, #204, #205.
→ All replaced by #208–216. #204/#205 work already built in the arch-a scaffold (intent-flow wired, C1+init-validation done), being re-pointed in #210. Close with "superseded by ARCH2 #208; work carries into #210-216."

## C. FOLD into ARCH2 children — close + reference

| # | Folds into |
|---|-----------|
| 182 unify universe loader | #213 (tooling/oracle, single dist path) |
| 183 local harness emulates cloud | #211 (AST build) + #190-equiv harness |
| 184 amplifying-mechanic parity | #215 (CI gates / G1-G5) |
| 202 G5 DSR/PBO | #215 |
| 203 acceptance contract | #215 (explicitly implements it) |
| 127 bt-results schema normalization | #214 (results/ ledger, one schema) |
| 173 per-experiment docs | CONVENTIONS.md / #209 |
| 174 post-trade analysis reqs | #214 / methodology |
| 175 experiment execution protocol | CONVENTIONS.md / sweeps |
| 176 research plan + phase structure | #208 epic (largely realized) |
| 185 8b50c1a postmortem | Done finding → close (lesson captured in charter) |

## D. EXPERIMENT GRIND — verdict-dependent

### D1. Rejected / dead-end → CLOSE (verify vs bt-results.csv first)
- #128 V1 e40c+e28 (0.393 REJECT)
- #129–140 V2–V13 (best V9 ~0.573, all reject vs champion)
- #141 Pyramid A (0.09 REJECT), #145 Pyramid B (reject)
- #142 $200-risk churn — FINDING (dead end), close as documented
- #153 V14 / #154 V15 multi-ETF (sector batch reject)
- #161 #162 #163 contrarian (deferred/reject)
- #158 #159 #160 $-risk sizing phases (best $500/maxent5=0.392 reject)
- #166 X7 (→X7a 0.49 reject under canonical exits)
- #167 X1, #168 X2, #169 X4 (queued, likely fold to sweeps)
- #170 X6, #171 X8 (DEFERRED)
- #177 F3-v2 circuit breaker, #180 Phase-3e combinatorial (shrunk/superseded)
- #146 R/S level computation (resistance_support.py built — verify done)
- #147 #148 #149 #150 R/S retest variants (phase-3-retest batch)

### D2. Confirmed positives → PRESERVE as v2 phase candidates (do NOT close; convert to feat/phase-*)
- #164 X3 → **X3a weekly-cloud 0.828 KEEP** → phases/regime/weekly_cloud
- #172 Pyramid search → **Pe signal-renewed 1.141 (provisional)** → phases/adds/pe_signal_renewed
- #178 Phase-3c → **Pe-rampup 1.486 (provisional)** → phases/adds/pe_rampup_antikelly
- #179 Phase-3d ladder trims → phases/profit/ladder_trim
- #165 X5 vol-adjusted, #151 structural trailing → evaluate as phase candidates

## E. DATA / FIX / DOC debt
- #10 parallel W1-W6 runner → folds into #214 sweeps/driver
- #81 _seed_weekly timeout fix → verify if still relevant in v2 carve (#212)
- #122 live_bct non-deterministic ordering → fold into v2 or close (live_bct archived)
- #110 FLEET STATE doc → historical record; close or keep as archive note
- #28 VIX percentile gate, #32 4% DD circuit breaker, #33 SUE drift, #57 dynamic MAX_POSITIONS → feature ideas → v2 phase library candidates (regime/circuit_breaker/signal/sizing)

---

## Recommended sequence for the later go-through
1. **B (superseded v1 epic, ~17)** — safe batch close, ARCH2 replaces them.
2. **C (fold, ~11)** — close with reference comment to the ARCH2 child.
3. **D1 (rejected experiments, ~25)** — verify each verdict in bt-results.csv, then batch close "superseded by ARCH2 sweeps model; result recorded."
4. **D2 (~6)** — relabel as `feat/phase-*` candidates for the v2 library; keep open.
5. **E + A** — case-by-case; most A stays open.

Net after full sweep: ~93 → ~20 open (ARCH2 active + Phase-5 + live phase candidates).
