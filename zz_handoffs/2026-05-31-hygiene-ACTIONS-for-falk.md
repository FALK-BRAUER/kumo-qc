# Morning Hygiene Actions — For Falk's Review

**Date:** 2026-05-31  
**Prepared by:** kumo-qc worker (anti-drift hygiene pass)  
**Status:** ACTION DOC — do NOT execute without Falk's explicit approval

---

## CRITICAL: Documentation Commits Need Cherry-Pick

**My non-destructive hygiene work (f973d2f) is stranded on a stale branch.**

- **Commit:** `f973d2f` — `docs(hygiene): recover undocumented BT provenance + add missing READMEs`
- **Current branch:** `feat/bct-7-entry-exit-inference` (stale, HEAD = main@6472ef5)
- **Target:** `mainV2` (c6ae66c, ~84 commits ahead of main)
- **Risk:** If feat/bct-7 is deleted, these READMEs + bt-results.csv rows are lost

**RECOMMENDED FIRST ACTION:**
```bash
git checkout mainV2
git cherry-pick f973d2f
# Resolve any conflicts (should be none — docs only, no code overlap)
git push origin mainV2
```

---

## Action Summary Table

| # | Action | Risk | Recoverable | My Rec | Notes |
|---|--------|------|-------------|--------|-------|
| 1 | Cherry-pick f973d2f to mainV2 | **LOW** | Y (commit exists) | **DO** | Prevents doc loss |
| 2 | Reset main worktree to mainV2 | **LOW** | Y (just checkout) | **DO** | Fixes stale branch |
| 3 | Remove 37 merged feat/* branches | **MEDIUM** | Y (commits in mainV2) | **DO** | Reduces branch sprawl |
| 4 | Remove feat/bct-7-entry-exit-inference | **LOW** | Y (after cherry-pick) | **DO AFTER #1** | Stale, identical to main |
| 5 | Remove worktrees: kqc-adr, kqc-docs, kumo-qc-243 | **LOW** | Y (branches remain) | **REVIEW** | Check if active work |
| 6 | Clean up results/ subdirs (documented) | **MEDIUM** | N (raw BT artifacts) | **DISCUSS** | See detailed analysis |
| 7 | Remove preserve/* branches | **HIGH** | N | **DO NOT** | Safety snapshots |
| 8 | Remove unmerged feat/* branches | **HIGH** | N (experiment code lost) | **DO NOT** | Historical experiments |
| 9 | Purge results/ undocumented BT dirs | **HIGH** | N | **DO NOT** | Now documented in undocumented.md |

---

## Detailed Actions (Safest → Riskiest)

### 1. Cherry-Pick Hygiene Commits to mainV2
```bash
git checkout mainV2
git cherry-pick f973d2f
# Should apply cleanly (docs only, no code)
git push origin mainV2
```
- **What it does:** Moves 5 READMEs + 17 bt-results.csv recovered rows to mainV2
- **What it removes:** Nothing
- **Risk:** LOW — additive only, no deletions
- **Recoverable:** Yes (commit f973d2f exists on feat/bct-7)
- **My recommendation:** **DO THIS FIRST** — prevents documentation loss when feat/bct-7 is cleaned up

---

### 2. Reset Main Worktree to mainV2
```bash
cd /Users/falk/projects/kumo-qc
git checkout mainV2
```
- **What it does:** Switches the main worktree from stale feat/bct-7 to current mainV2
- **What it removes:** Nothing (just changes HEAD)
- **Risk:** LOW — pure checkout, no branch deletion
- **Recoverable:** Yes (branch still exists)
- **My recommendation:** **DO** — main worktree should track mainV2, not a stale feature branch
- **Note:** Do AFTER cherry-pick (#1) to avoid needing to push from feat/bct-7

---

### 3. Remove 37 Merged feat/* Branches
```bash
# These branches are fully merged into mainV2 — their commits exist in mainV2 history
git branch -d feat/228-signal-phase
git branch -d feat/arch2-213-lean-entry
git branch -d feat/arch2-213b-artifact-subscription
git branch -d feat/arch2-213c-indicator-lifecycle
git branch -d feat/arch2-213d-warmup-guard
git branch -d feat/arch2-213e-liquidity-floor-100m
git branch -d feat/arch2-213f-maintained-indicators
git branch -d feat/arch2-213f2-maintained-score
git branch -d feat/arch2-213f3-weekly-monday-seed
git branch -d feat/arch2-236-charter-timeexit
git branch -d feat/arch2-237-drop-forbidden-params
git branch -d feat/arch2-238-live-coarse-universe
git branch -d feat/arch2-3-champion-rewire
git branch -d feat/bct-4-phase2
git branch -d feat/c2-resistance-proximity
git branch -d feat/cloud-static-universe
git branch -d feat/cloud-universe-file
git branch -d feat/cloud-universe-gate-fix
git branch -d feat/dynamic-universe
git branch -d feat/e121-vix-ichimoku-2tier
git branch -d feat/e32-dd-circuit-breaker
git branch -d feat/e32-trailing-dd-cb
git branch -d feat/e38-clean
git branch -d feat/e38-resistance-gate-clean
git branch -d feat/e40b-spy200-regime
git branch -d feat/e41v3-revalidate
git branch -d feat/e48-resistance-proximity-5pct
git branch -d feat/e49-iwm-breadth-canary
git branch -d feat/e49-iwm-breadth-canary-clean
git branch -d feat/e54-tenkan-exit
git branch -d feat/e55-weekly-kijun-exit-v2
git branch -d feat/exp-conviction-sizing
git branch -d feat/f2-iwm-half-size
git branch -d feat/g3-ytd-baseline
git branch -d feat/items-5-6-ladder-earnings
git branch -d feat/weekly-kijun-exit-13
```

- **What it does:** Removes 37 branch references that are already in mainV2 history
- **What it removes:** Branch pointers only — all commits preserved in mainV2
- **Risk:** MEDIUM — if any branch was incorrectly detected as merged, code is recoverable via `git reflog`
- **Recoverable:** Yes (commits in mainV2, reflog retains for 90 days)
- **My recommendation:** **DO** — Reduces `git branch -a` noise from ~200 to ~160. Makes branch discovery usable.
- **Batch command:**
  ```bash
  git branch --merged mainV2 | grep "^\s*feat/" | sed 's/^[* ]*//' | xargs -I {} git branch -d {}
  ```

---

### 4. Remove Stale feat/bct-7-entry-exit-inference Branch
```bash
git branch -d feat/bct-7-entry-exit-inference
```
- **What it does:** Removes the stale branch (identical to main@6472ef5)
- **What it removes:** Branch pointer only
- **Risk:** LOW — identical to main HEAD, but do AFTER cherry-pick (#1)
- **Recoverable:** Yes (commit 6472ef5 still on main)
- **My recommendation:** **DO AFTER #1** — branch serves no purpose, holds no unique commits

---

### 5. Remove Stale Worktrees (Review Required)

#### 5a. /private/tmp/kqc-adr (docs/adr-variant-architecture)
```bash
git worktree remove /private/tmp/kqc-adr
# Keep branch: git branch -d docs/adr-variant-architecture
```
- **What it removes:** Worktree directory + worktree registration
- **Risk:** LOW — branch is tracked on origin, worktree is temporary
- **Recoverable:** Yes (branch exists on origin)
- **My recommendation:** **REVIEW** — Verify ADR work is complete and branch pushed

#### 5b. /private/tmp/kqc-docs (docs/arch2-universe-ranking)
```bash
git worktree remove /private/tmp/kqc-docs
# Keep branch: git branch -d docs/arch2-universe-ranking
```
- **What it removes:** Worktree directory + worktree registration
- **Risk:** LOW — branch tracked on origin
- **Recoverable:** Yes
- **My recommendation:** **REVIEW** — Verify docs work is complete

#### 5c. /Users/falk/projects/kumo-qc-243 (feat/243-emit)
```bash
git worktree remove /Users/falk/projects/kumo-qc-243
# Keep branch: git branch -d feat/243-emit
```
- **What it removes:** Worktree directory
- **Risk:** LOW — branch tracked on origin (9e79b99)
- **Recoverable:** Yes
- **My recommendation:** **REVIEW** — Check if #243 chart-emit work is closed. If so, safe to remove.

---

### 6. Clean Up results/ Subdirectories (Documented BTs)

**Status: NOW DOCUMENTED — see results/undocumented.md and bt-results.csv**

There are ~50 result subdirectories. Two cleanup strategies:

#### Option A: Archive to Compressed Storage (RECOMMENDED)
```bash
# Create archive of raw BT artifacts for recovery if needed
tar czf results-archive-2026-05-31.tar.gz \
  results/buy-stop-20260525/ \
  results/e28-fy2025/ \
  results/e36-fy2025/ \
  results/e36-test/ \
  results/e37-fy2025/ \
  results/e38-fy2025/ \
  results/e40b-phase2/ \
  results/e40e-fy2025/ \
  results/e40e-w1/ \
  results/e40e-w2/ \
  results/e40e-w3/ \
  results/e40e-w4/ \
  results/e40e-w5/ \
  results/e40e-w6/ \
  results/e49-fy2025/ \
  results/e51-fy2025/ \
  results/e78-baseline-fy2025/ \
  results/e78-baseline-W1/ \
  results/e78-baseline-W2/ \
  results/e78-baseline-W3/ \
  results/e78-baseline-W4/ \
  results/e78-baseline-W5/ \
  results/e78-baseline-W6/ \
  results/e78-fy2025/ \
  results/e78-W1/ \
  results/e78-W2/ \
  results/e78-W3/ \
  results/e78-W4/ \
  results/e78-W5/ \
  results/e78-W6/ \
  results/gh119-local/ \
  results/gh42-quick-test/ \
  results/gh79-equity200-baseline/ \
  results/gh79-sp500/ \
  results/spy-gate-20260525/ \
  results/spy-weekly-20260525/ \
  results/throughput-audit/ \
  results/throughput-audit-2020/ \
  results/throughput-audit-2020-v2/ \
  results/throughput-audit-warm0/ \
  results/w1-4gates-20260525/ \
  results/w1-local-20260525/ \
  results/w1-local-20260525-fix/ \
  results/w1-local-20260525-v3/
  
# Then remove the directories
rm -rf results/buy-stop-20260525/ results/e28-fy2025/ ...
```

- **What it removes:** Raw LEAN backtest artifacts (config, log, summary JSON, order-events)
- **Risk:** MEDIUM — artifacts are large but recoverable from archive
- **Recoverable:** Yes (if archived) / No (if rm -rf without archive)
- **My recommendation:** **DISCUSS** — The metrics are now in bt-results.csv and undocumented.md. Raw artifacts are only needed for deep forensics. Recommend archiving first, then removing after 30-day grace period.

#### Option B: Keep but Gitignore (Conservative)
Add to `.gitignore`:
```
results/*/
!results/README.md
!results/undocumented.md
```
- **What it does:** Keeps files on disk but prevents accidental commits
- **Risk:** NONE
- **Recoverable:** N/A
- **My recommendation:** **ALTERNATIVE** — If disk space isn't critical, just gitignore them. They're already not committed (shown as `??` in git status).

---

## DO NOT ACTIONS (Already Flagged by HQ)

### DO NOT 1: Remove preserve/* Branches
```bash
# DO NOT RUN:
# git branch -D preserve/kumo-qc-v10-pre-cleanup-20260530
# ... (18 branches total)
```
- **Why NOT:** These are safety snapshots from the 2026-05-30 pre-cleanup. They exist as recovery points if mainV2 history is ever corrupted.
- **Risk if executed:** HIGH — irreversible loss of recovery points
- **My recommendation:** KEEP — These are insurance, not clutter. Revisit in 90 days.

### DO NOT 2: Remove Unmerged feat/* Branches
```bash
# DO NOT RUN:
# git branch -D feat/e40d-vix25-regime
# git branch -D feat/e43-pyramid-add
# ... (~160 branches)
```
- **Why NOT:** These branches contain experiment code that may be referenced in bt-results.csv analysis. Even "rejected" experiments are valuable for understanding what was tried.
- **Risk if executed:** HIGH — experiment code lost, historical analysis becomes impossible
- **My recommendation:** KEEP — Consider archiving to a separate repo or refs namespace instead.

### DO NOT 3: Purge Undocumented BT Directories
```bash
# DO NOT RUN:
# rm -rf results/e28-fy2025/ results/e36-fy2025/ ...
# WITHOUT ARCHIVING FIRST
```
- **Why NOT:** These are now fully documented in `results/undocumented.md` and `bt-results.csv`. The raw artifacts may still be needed for:
  - Order-level forensics (order-events.json)
  - Cloud parity verification (config files)
  - Re-running with corrected parameters
- **Risk if executed:** HIGH — raw data lost even if summary metrics are saved
- **My recommendation:** ARCHIVE FIRST, then remove after 30 days. Do not purge without backup.

---

## Pre-Flight Checklist (Before Any Destructive Action)

```bash
# Verify cherry-pick landed
git log mainV2 --oneline | grep f973d2f

# Verify no uncommitted work on affected branches
git status

# Create a safety snapshot before mass branch deletion
git branch backup/pre-cleanup-2026-05-31 mainV2

# Verify preserve branches are untouched
git branch | grep preserve/
```

---

## Disk Impact Estimate

| Action | Space Recovered | Notes |
|--------|----------------|-------|
| Remove 37 merged feat branches | ~0 MB | Branch pointers only |
| Remove 3 stale worktrees | ~50-200 MB | Source code, not data |
| Remove results/ subdirs (Option A) | ~2-5 GB | Raw LEAN artifacts, largest gain |
| Total (all safe actions) | ~2-5 GB | Main benefit is results/ cleanup |

---

## Sign-off

**Falk:** Review and approve/reject each action. Worker standing by to execute approved items.

**Completed non-destructive work:**
- [x] results/undocumented.md (38 undocumented BTs indexed)
- [x] bt-results.csv (+17 recovered rows)
- [x] 4 READMEs written (tests/engine/, storage/, logs/, design/)
- [x] Committed: f973d2f on feat/bct-7-entry-exit-inference

**Pending (destructive, awaiting approval):**
- [ ] Cherry-pick f973d2f to mainV2
- [ ] Reset main worktree to mainV2
- [ ] Remove 37 merged feat/* branches
- [ ] Remove stale worktrees
- [ ] Archive + remove results/ subdirs
- [ ] Delete feat/bct-7-entry-exit-inference (after cherry-pick)
