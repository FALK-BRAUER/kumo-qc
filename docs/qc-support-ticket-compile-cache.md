# QuantConnect Support Ticket — Compile Cache Invalidation Bug

**Submitted by:** Falk Brauer (User ID: 499707, Project: 32034565)
**Date:** 2026-05-27 (updated with new evidence)
**Severity:** High — blocks production deployment

---

## Issue Summary

QC cloud compile API returns new `compileId` but compiles **cached/stale code** instead of latest repository code. Deleted files and removed imports persist across multiple compile attempts despite new `compileId`s.

## Affected Backtest IDs

1. `9f77b64789df273e7d49328ec0c15180` — Runtime Error at 1% (2026-05-26)
2. `aa8a4d0f1cb2d47bf89a349234d566c2` — Runtime Error at 1% (2026-05-26)
3. `7fe2cf0394e3eb0587963fbe2f10d6c3` — Runtime Error at 1% (2026-05-26)
4. `b75362746fbff72d66f588f19dabcddb` — Runtime Error at 1% (2026-05-27)
5. `20d4d712c19167c87b16f99ab2bb736f` — Runtime Error at 1% (2026-05-27) **NEW — dummy file workaround also failed**

## Affected Compile IDs

1. `876021d1dc4f614bfbe7395b2deeef4b-593d12539e6c8e9cc8d999162d91f637` (2026-05-26)
2. `afd462b69bb3f37af911ae945bfd66ff-593d12539e6c8e9cc8d999162d91f637` (2026-05-27) **NEW**

## Expected Behavior

When a new `compile/create` API call is made and returns a new `compileId`, the compile should use the **latest code from the linked GitHub repository** (main branch, commit `8048c29`).

## Actual Behavior

New `compileId` is returned (`876021d1dc4f614bfbe7395b2deeef4b-593d12539e6c8e9cc8d999162d91f637`), but the compiled code references:
- `from bct_signal import score_symbol_native` at **line 26** (deleted in commit `637bd19`)
- `from universe_filter import BCTUniverseFilter` (deleted in commit `8538dc5`)

Current `main.py` line 26 is `from AlgorithmImports import *` — the compile is using **stale cached code from earlier commits**.

## Evidence

### 1. Local repository state (commit 8048c29):
- `algorithm/performance_bct/bct_signal.py` — **DELETED** (removed in 637bd19, 2026-05-24)
- `algorithm/performance_bct/universe_filter.py` — **DELETED** (removed in 8538dc5, 2026-05-25)
- `algorithm/performance_bct/main.py` — **fully self-contained**, no external imports (confirmed by `grep "bct_signal"` returning NOTHING)

### 2. QC compile API response:
```
CompileId: 876021d1dc4f614bfbe7395b2deeef4b-593d12539e6c8e9cc8d999162d91f637
State: InQueue
Success: True
```

### 3. QC backtest error (all three BTs):
```
AlgorithmPythonWrapper(): No module named 'bct_signal'
at <module>
    from bct_signal import score_symbol_native
in main.py: line 26
```

### 4. Current main.py line 26 (commit 8048c29):
```python
from AlgorithmImports import *  # noqa: F401,F403
```

**The error references OLD code that no longer exists in the repository.**

### 5. New evidence (2026-05-27):
- Commit `8048c29` pushed to main — fully self-contained main.py, zero external imports
- New compileId `afd462b69bb3f37af911ae945bfd66ff-593d12539e6c8e9cc8d999162d91f637` generated
- BT `b75362746fbff72d66f588f19dabcddb` submitted
- **SAME ERROR:** `No module named 'bct_signal'` at line 26
- **This proves the bug is NOT fixed by new commits or new compileIds — the cache is fundamentally broken**

## Steps to Reproduce

1. Delete file `bct_signal.py` from project and remove its import from `main.py`
2. Push to linked GitHub repository (commit 8538dc5, then 8048c29)
3. Call `compile/create` API for project 32034565
4. Receive **new** `compileId` (different from previous)
5. Submit backtest using new `compileId`
6. Backtest fails with import error for deleted file
7. Repeat with newer commit — same error persists across ALL new compileIds

## Hypothesis

The QC compile cache is keyed by something other than `compileId` (possibly project-level snapshot or cached Docker layer), and cache invalidation is not triggered when:
- Files are deleted from the repository
- New compileIds are generated
- New commits are pushed

The cache appears to be **project-level persistent**, surviving across multiple days and multiple compileIds.

## Request

1. **Clear compile cache** for project 32034565
2. **Investigate cache invalidation logic** — deleted files should invalidate cached compiles
3. **Provide workaround** for forcing fresh compile (e.g., cache-busting parameter)

## Local Validation (Authoritative)

Local LEAN backtest with same code: **Sharpe 1.036, Return +30.05%, ~240 orders** — confirms code is correct, issue is purely QC cloud caching. Local is now the authoritative validation environment until QC fixes this bug.

---

**Project ID:** 32034565
**Repository:** github.com/FALK-BRAUER/kumo-qc
**Branch:** main (commit 8048c29)
**Previous commits also affected:** 8538dc5, c88335d, 637bd19
**Contact:** flk.brauer@googlemail.com
