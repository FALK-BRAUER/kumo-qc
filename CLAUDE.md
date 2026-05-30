# CLAUDE.md — kumo-qc

## What This Is
QuantConnect-based trading engine implementing George's Blue Cloud Trading (BCT) Ichimoku methodology at scale.
Replaces the brittle kumo-trader agent/ monolith with QC's managed infrastructure.

QC handles: engine, universe (6,000 names), IBKR connection, data, scheduling, VPS.
We own: BCT signal logic (~400 lines Python), cockpit adapter (Next.js reading QC REST API).

## Architecture
- **Strategy code:** Python, QuantConnect LEAN algorithm framework
- **Universe:** Coarse filter (6k → ~200 by liquidity/price) → BCT fine scoring (→ 5-10 signals)
- **Execution:** QC live trading node → IBKR paper (DUK434934) or live (U18777181 — manual approval gate)
- **Cockpit:** Next.js UI reads QC REST API (positions, orders, P&L) — adapts kumo-trader UI patterns
- **Credentials:** QC User ID + API Token via macOS keychain (never hardcoded)

## IBKR Accounts
| Account | ID | Purpose | Who touches it |
|---|---|---|---|
| **Live** | U18777181 | Falk's manual trades only | Falk via TWS/app |
| **Paper** | DUK434934 | Automated QC paper loop only | QC live node (port 4002) |

Rules:
- Automated QC algorithms → NEVER target U18777181. Paper loop = DUK434934.
- Falk placing manual orders → U18777181 is correct and expected.

## BCT Signal Stack
8-condition Blue Flag checklist:
1. Weekly price above cloud (Span A)
2. Weekly Tenkan > Kijun
3. Weekly Chikou > price 26 bars ago
4. Weekly cloud GREEN (Span A > Span B)
5. Daily price above cloud
6. Daily price above Tenkan
7. ADX rising + +DI > -DI + ADX ≥ 20 (period 9, Wilder's EWM)
8. Price above 200-day MA

Rating: +++ = 8/8, ++ = 6-7/8, + = 4-5/8

## QC Tier
Researcher ($84/month) — sufficient for solo live trading with up to 2 live nodes.
API credentials: User ID + API Token from QC account settings → macOS keychain.

## Key Rules
- Never commit API keys, account numbers, or passwords
- QC API token → keychain only, never in code or config files
- Conventional Commits format
- Strategy logic in algorithm/ directory
- Cockpit adapter in ui/ directory (Next.js, same stack as kumo-trader)

## Project Phases
| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ | QC account setup + API credentials + local LEAN CLI |
| 2 | ✅ | BCT signal port — 8-condition checklist in QC Python (bct_signal.py) |
| 3 | ✅ | Universe filter — coarse (6k→200) + fine (BCT score ≥7 → 5-10) |
| 4 | ✅ | Backtest validation — 74.2% recall / 100% precision vs scanner; ADX 71% match (data feed delta, not bug) |
| 5 | 🔲 | Paper live trading — gate.py unlock → deploy.py → DUK434934 (Falk decision) |
| 6 | ✅ | Cockpit adapter — Next.js reads QC REST API (server-only auth, 4 route handlers) |
| 7 | ✅ | Live trading gate — gate.py + live-gate QC parameter + DU account prefix check |

## QC Project IDs
| Project | ID | Purpose |
|---------|----|---------|
| performance_bct | 32033824 | All experiment BTs — signals + orders + returns (QC name: "algorithm/performance_bct") |
| minimal_bct | 32099988 | ObjectStore data uploads target (QC name: "algorithm/minimal_bct") |
| live_bct | not deployed | Awaiting Falk gate.py unlock |

Note: project 32034565 does NOT exist. Was incorrectly documented. All cloud BTs run on 32033824.

## E40d Cloud Parity (GH#116)
- **Local:** 1.442 Sharpe / 196 orders / +42.4% / 9.5% DD (commit a03e7a9, raw prices)
- **Cloud:** 1.315 Sharpe / 274 orders / +39.4% / 11.8% DD (ObjectStore polygon-326, QC adjusted prices)
- **Delta:** -0.127 Sharpe — within ±0.3 tolerance. **PASS.**
- **Structural divergence:** QC cloud uses different data vendor than local LEAN data files. Order count differs (274 vs 196) because cloud loads full 326-ticker polygon union (no per-day filter). Sharpe is the primary parity metric.
- **ObjectStore key:** `polygon_universe_equity200_fy2025.json` must be present in project 32033824 ObjectStore. Currently populated (2026-05-29). If cleared, re-upload via QC web interface or object/set API. File: `algorithm/performance_bct/polygon_universe_equity200_fy2025.json`.

## Credentials (keychain only)
```
security find-generic-password -s "qc-user-id" -a "kumo-qc" -w     → QC user ID
security find-generic-password -s "qc-api-token" -a "kumo-qc" -w   → QC API token
security find-generic-password -s "kumo-qc" -a "qc-live-gate" -w   → UNLOCKED or absent
```

UI credentials: set in `ui/.env.local` (gitignored):
```
QC_USER_ID=...
QC_API_TOKEN=...
QC_PROJECT_ID=32033824
```

## Worktree Regime — Experiment Isolation

Each experiment runs in its own git worktree. Never switch branches on the main tree.

**Setup:**
```bash
# Main branch always at /Users/falk/projects/kumo-qc-main
git worktree add /Users/falk/projects/kumo-qc-main main

# New experiment
git worktree add /Users/falk/projects/kumo-qc-<exp-id> -b feat/<exp-id>

# REQUIRED after creating worktree — symlink LEAN data so local BT works:
rm -rf /Users/falk/projects/kumo-qc-<exp-id>/data
ln -s /Users/falk/projects/kumo-qc/data /Users/falk/projects/kumo-qc-<exp-id>/data
```

**Why the data symlink:** worktrees share the git index but not ignored files. `data/` is gitignored (LEAN binary data). Without the symlink, `lean backtest` finds an empty `data/` dir and all data requests fail silently (100% failure rate, 0 data points, 0.67s BT).

**Workflow:**
1. Create worktree for the experiment branch
2. Do all work inside that worktree directory
3. If **ACCEPTED** → PR to main, merge, remove worktree
4. If **REJECTED** → record in bt-results.csv on main (cherry-pick or direct), remove worktree, leave branch as record

**bt-results.csv lives on main.** Commit results there, not on the experiment branch.

**Remove worktree when done:**
```bash
git worktree remove /Users/falk/projects/kumo-qc-<exp-id>
# branch stays in git history; worktree dir is deleted
```

**Why:** eliminates wrong-branch commits from context compaction. Each directory = one branch, unambiguous.

**Existing worktrees:** `git worktree list` to see all.

### ENFORCEMENT (mandatory — added 2026-05-29 after shared-tree incident)

The 2026-05-29 P0 incident proved the regime above is ignored without enforcement: 3 workers ran BTs + edited `main.py` in the shared main tree simultaneously → duplicate cloud pushes, contradictory results, and a **fabricated diff** (a worker reported cloud orders it never actually fetched). Root cause: workers don't read this section at session start, and orchestrators dispatched BT work without requiring isolation.

**Three-layer enforcement — all mandatory:**

1. **Preflight gate (worker side).** Before ANY local backtest or `main.py` edit, the worker MUST run:
   ```bash
   bash scripts/worker-preflight.sh <worker_id>
   ```
   It exits 1 (abort) if the worker is in the shared main tree, with the exact worktree-creation commands. Exit 0 only inside an isolated worktree.

2. **Dispatch template (orchestrator side).** Every BT/main.py task dispatch MUST embed the worktree setup and require an ack. Use `docs/worker-dispatch-protocol.md`. No BT task is dispatched without it; no worker starts BT work until it has replied "PREFLIGHT OK in worktree <path>".

3. **Data-integrity rule (worker side).** Any reported result (orders, fills, diffs, Sharpe) MUST come from a real artifact — a backtest output dir, an order-events file, or a verified API response. NEVER infer/assume parity or fill in expected values. If a fetch returns empty, report "no data retrieved", never fabricate. Orchestrators spot-check critical findings against ground truth (e.g. QC API `/backtests/orders/read`).

---

## Commit + Push Policy

**Commit:** after every logical unit of work. Never batch unrelated changes.

**Pre-commit checklist (mandatory):**
1. `git status` — scan for unexpected files (data/, .env.local, *.json.bak, node_modules/)
2. Confirm `.gitignore` covers any new file types before staging
3. No secrets, tokens, or account numbers in diff

**Push:** push immediately after every clean commit. This repo's disaster (2026-05-23) happened because 26 local commits were never pushed — directory deletion wiped everything. Push is the backup.

**Push command:** `git push origin main` from kumo-qc/

**Never push if:**
- `git diff --stat HEAD~1 | grep data/` is non-empty
- Any `.env*` file appears in the diff
- `git log origin/main..HEAD` shows commits with 100+ file additions (check the diff first)

**Conventional Commits format:**
- `feat(scope):` new capability
- `fix(scope):` bug fix
- `chore:` config, gitignore, tooling
- `refactor(scope):` restructure without behavior change

## Worker Regime — State Management

Workers on kumo-qc maintain state in two places. Both are mandatory, not optional.

### 1. Handoff files (local)

Every worker session writes a handoff before closing. Location: `zz_handoffs/YYYY-MM-DD-<feature>.md`.

Required sections:
- **Current task** — specific subtask in flight + last action + next action
- **What we did** — concrete changes (file:line or function name, not prose)
- **Decisions** — the WHY behind each architectural choice
- **Current state** — working / partial / broken
- **What's left** — ordered list, specific enough to resume cold
- **Context** — gotchas, constraints, non-obvious deps
- **Files changed** — from `git diff --stat`

Rule: if `git status` shows changes and you haven't written or updated the handoff in the last commit, the session is not done.

### 2. GitHub Issues (remote, persistent)

Each discrete work item gets a GitHub issue in `FALK-BRAUER/kumo-qc`. Workers must:

1. **Open an issue** when starting a new work item (if one doesn't exist)
2. **Add a progress comment** when partially done (what's done, what's left)
3. **Close the issue** (with `Closes #N` in the commit message) when complete

Issue format:
```
Title: <one-line description>
Body:
## Goal
[What this achieves]

## Acceptance Criteria
- [ ] specific verifiable outcome
- [ ] specific verifiable outcome

## Context
[Non-obvious constraints, links to relevant code]
```

Labels used: `phase-2-backtest`, `phase-5-live`, `cockpit`, `worker-regime`, `p0`, `p1`, `p2`

### Regime summary

| State | Where it lives | When to update |
|-------|---------------|----------------|
| In-progress notes | GitHub issue comment | After each meaningful action |
| Session summary | `zz_handoffs/` file | Before every session close |
| Completed work | Git commit (pushed) | Immediately after clean commit |
| Pending work | GitHub issue open | Until merged + closed |

**Why both?** Handoffs are fast to write mid-session. GitHub issues survive worker crashes, directory deletions, and agent context resets. The May 23 disaster proved that local-only state = single point of failure.

### Destructive action policy

Workers **MUST NOT** run any of the following without explicit written authorization from fintrack (Claude Code commander):
- `rm -rf` on any directory
- `git reset --hard` beyond the current working tree
- `git push --force`
- Dropping/truncating database tables
- Deleting branches

When in doubt: write a handoff, open a GitHub issue, and stop. Do NOT improvise a cleanup. The May 23 incident: Worker B deleted the entire kumo-qc directory following an orchestrator's "archive or delete" instruction. Orchestrators do not have destructive authority — only fintrack does.

## Cloud/Local Parity — Architectural Rule (charter, 2026-05-30)

**Single code path for cloud and local. No environment branches in strategy logic. Local is a HARNESS that emulates cloud — not the other way around.**

### What this means

- **NEVER** write `if cloud: X else: local: Y` branches in strategy code. Every such branch is a bug waiting to detonate.
- Cloud (LEAN container, ObjectStore, scheduler, fill model) is the CANONICAL environment — the strategy will trade there.
- Local backtesting MUST run the SAME code path on the SAME data flow as cloud. Local = cheap iteration, cloud = paid validation, IDENTICAL results.
- If cloud behavior is hard to reproduce locally (ObjectStore, scheduling, subscription manager, normalization), the fix is to **EMULATE cloud locally** (mock ObjectStore, replay LEAN scheduling, identical data normalization) — NOT to add a workaround that makes cloud behave like local.

### What is FORBIDDEN

- Loading data from disk locally + ObjectStore on cloud (different code paths, different state).
- Disabling a cloud filter because "it gives ~zero valid candidates on cloud" — that's a bug to fix, not a branch to add.
- Hardcoding cloud behavior to match local convenience.
- Accepting ±0.3 Sharpe parity on a non-amplifying baseline (e.g. E40d) as proof of parity. **Parity must be proven on the strategy that exercises the amplifying mechanic (pyramid, leverage, momentum sizing).**

### Concrete lesson — 8b50c1a regression (2026-05-28)

The local code path stored `self._polygon_universe` (date-keyed dict) and filtered candidates to today's snapshot per day (~50-100 names). The cloud code path loaded the same JSON from ObjectStore but DID NOT assign `self._polygon_universe`, leaving the daily filter inert → cloud saw all 326 unique tickers every day.

Diagnosis at the time (commit 8b50c1a): "Cloud causes ~zero valid candidates (date key mismatch or schedule timing). Cloud path should not set _polygon_universe."

Workaround chosen: **disable the filter on cloud**, accept 1.315 (cloud) vs 1.442 (local) Sharpe on E40d as "within ±0.3."

What this hid: **selection divergence**. Cloud and local picked completely different stocks from day 1 (different selection logic → different trades → different P&L). E40d tolerated it. Pe pyramid (added later) amplified it from 1.141 local → -0.055 cloud.

### Required architecture going forward

1. **One Initialize() universe path** — same loader, same assignment, same daily filter, regardless of where it executes.
2. **Local harness must spin up ObjectStore mock** — store the polygon JSON in a local ObjectStore-equivalent so the cloud code path runs verbatim locally.
3. **Cloud/local parity test on EVERY pyramid/leverage/amplifying variant before claiming a result.** Baseline parity is insufficient.
4. **Any "if cloud" branch in algorithm/ requires explicit CLAUDE.md update + justification + parity test on amplifying mechanic before merge.**
5. **Diff protocol applies when parity breaks** — first-divergence point, concurrent positions, cash trajectory, pyramid adds, fill-level — before interpretation (see #173 Local vs Cloud Divergence Diagnosis Protocol).

### Charter principle

*Workarounds for cloud/local divergence that look acceptable at ±0.3 Sharpe on a non-amplifying strategy will EXPLODE under amplifying mechanics. Parity must be proven on the strategy that exercises the amplification, not just on the baseline. Single code path always. Local emulates cloud, not the other way around.*

## Git as Source of Truth for Cloud Code (charter, 2026-05-30)

All code deployed to QC cloud projects MUST exist in git first.

- Cloud-deployed files (.py modules, main.py, helpers) → authored in git → committed → pushed to cloud via API (`scripts/qc_pe_cloud.py` reads from a git-tracked worktree) or `lean cloud push`.
- NEVER author files directly on QC via `/files/update` without a corresponding git commit first.
- Cloud project = deployment target, NOT an authoring environment.
- Risk if violated: cloud project cleared = code lost; code review impossible without an API pull; re-deploys overwrite cloud.

**Worktree branches ARE git-tracked → they count as source of truth.** Verify a file exists in ANY branch (`git log --all -- path`) before raising a "cloud-only / not in git" alarm — searching only the `main` worktree will miss work that legitimately lives on a feature branch under the worktree regime.

Note (2026-05-30): pyramid_engine.py + resistance_support.py were briefly suspected "cloud-only" during Phase 3c — VERIFIED FALSE. Both are committed on `feat/p3b-pyramid-search` (e12ec42) and earlier feat branches; the alarm came from grepping the `main` tree only. They land on `main` when the pyramid work graduates. The deploy already reads from the git-tracked worktree, so cloud code traces to a commit. Rule formalized to prevent the confusion recurring.
