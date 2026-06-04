"""#368 — pre-sweep weekly-cache build orchestration (deterministic, idempotent, fail-loud).

The trimmed-warmup champion (WARMUP_DAYS=320) REQUIRES the weekly-cache (else the 78-week weekly
starves → silent 0-trades). A champion that depends on a HAND-BUILT cache is non-reproducible — a
clean checkout / CI / fresh machine has no cache → silent break. This wires the build INTO the sweep
setup: before any trimmed-warmup sweep, ensure the cache exists, building it deterministically from
the daily data if absent.

Chain (the proven, reproducible-verified path): build_warmup_cache.py (daily zips → per-(sym,date)
scalar table) → write_weekly_objectstore.py (table → per-symbol ObjectStore weekly keys). Both are
deterministic (a rebuild == the prior build byte-identical, #368-verified). IDEMPOTENT: skip if the
cache is already present for the fingerprint. FAIL-LOUD: a build that produces zero keys raises.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")

# the weekly-cache key prefix (mirrors runtime.warmup_weekly_cache.WEEKLY_CACHE_TYPE) — a present
# check globs storage for ANY weekly key under the fingerprint.
_WEEKLY_PREFIX = "weekly_ichimoku"
_MANIFEST_SCHEMA = 1


def weekly_cache_present(storage_dir: Path | str, fp: str) -> bool:
    """True iff at least one weekly-cache key for this data fingerprint exists in storage. The WEAK
    check — proves non-emptiness only (#370: a PARTIAL build also passes it). Kept for the post-build
    fail-loud (0-keys) assertion; the idempotent SKIP uses weekly_cache_complete (coverage-tied)."""
    return any(Path(storage_dir).glob(f"{_WEEKLY_PREFIX}-{fp}-*"))


# ── #370 coverage manifest: the principled completeness invariant ────────────────────────────────
# The idempotent skip must verify the cache covers the REQUESTED (universe, data_fp) set, NOT just
# "a key exists" (a partial build, or a cache built for universe-A used on universe-B, falsely passes).
# The manifest is written ATOMICALLY at the END of a successful full build → its presence is a
# completion marker; its (data_fp, universe_sig) records WHAT was covered.

def _manifest_path(storage_dir: Path | str, fp: str) -> Path:
    return Path(storage_dir) / f"{_WEEKLY_PREFIX}_manifest-{fp}.json"


def universe_signature(daily_dir: Path | str = _DEFAULT_DAILY) -> tuple[str, int]:
    """Deterministic signature of the daily-zip universe: (sha256 of the sorted ticker list, count).
    The runtime can request a weekly scalar for ANY of these symbols, so this is the set the cache
    must cover. Sorted → order-independent; sha256 → stable across machines. Dotfiles (.partial.zip,
    editor temp) are EXCLUDED → machine-independent sig. FAIL-LOUD on 0 tickers (a mis-pathed/empty
    daily_dir must crash, not sign an empty universe that could false-pass — degraded-state-must-crash)."""
    tickers = sorted(p.stem.lower() for p in Path(daily_dir).glob("*.zip")
                     if not p.name.startswith("."))
    if not tickers:
        raise RuntimeError(
            f"universe_signature: 0 daily-zip tickers under {daily_dir} — refuse to sign an empty "
            f"universe (a mis-pathed dir would false-pass completeness). Check the daily data path."
        )
    sig = hashlib.sha256("\n".join(tickers).encode()).hexdigest()
    return sig, len(tickers)


def write_cache_manifest(storage_dir: Path | str, fp: str, *, universe_sig: str,
                         n_universe: int, n_built: int, n_keys: int) -> Path:
    """Write the coverage manifest ATOMICALLY (tmp + os.replace) — a crash mid-write never leaves a
    truthy-but-corrupt manifest. Called by write_weekly_objectstore at the end of a full build."""
    path = _manifest_path(storage_dir, fp)
    payload = {"schema": _MANIFEST_SCHEMA, "data_fp": fp, "universe_sig": universe_sig,
               "n_universe": n_universe, "n_built": n_built, "n_keys": n_keys}
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, sort_keys=True))
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)  # never leave a half-written tmp on a write/replace crash
        raise
    return path


def read_cache_manifest(storage_dir: Path | str, fp: str) -> dict | None:
    """The coverage manifest for fp, or None if absent/unreadable/malformed (→ treated as incomplete)."""
    path = _manifest_path(storage_dir, fp)
    if not path.exists():
        return None
    try:
        m = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return m if isinstance(m, dict) else None  # non-dict JSON (list/str/num) → incomplete, not a crash


def weekly_cache_complete(storage_dir: Path | str, fp: str,
                          daily_dir: Path | str = _DEFAULT_DAILY) -> bool:
    """#370 PRINCIPLED completeness: complete for `fp` iff a manifest exists AND it was built for THIS
    data_fp AND for the SAME universe the runtime will request. A partial build (no manifest), a
    wrong-fp manifest, or a different-universe manifest → NOT complete → (re)build."""
    m = read_cache_manifest(storage_dir, fp)
    if m is None or m.get("schema") != _MANIFEST_SCHEMA or m.get("data_fp") != fp:
        return False
    sig, _n = universe_signature(daily_dir)
    return m.get("universe_sig") == sig


def ensure_weekly_cache(
    fp: str,
    *,
    storage_dir: Path | str,
    cache_root: Path | str,
    daily_dir: Path | str = _DEFAULT_DAILY,
    runner: Callable[..., Any] = subprocess.run,
    complete: Callable[..., bool] = weekly_cache_complete,
    log: Callable[[str], None] = print,
) -> str:
    """Ensure the weekly-cache is COMPLETE for `fp`. IDEMPOTENT skip = the #370 coverage check
    (manifest covers this data_fp + the daily universe), NOT mere non-emptiness — a PARTIAL cache no
    longer falsely passes. DETERMINISTIC build (build_warmup_cache → write_weekly_objectstore, which
    writes the coverage manifest atomically at the end). FAIL-LOUD: a build that yields 0 keys OR
    leaves the cache still-incomplete (no/!covering manifest) raises. Returns 'complete' (skipped) or
    'built'. `runner`/`complete` injectable for tests."""
    if not fp:
        raise ValueError("ensure_weekly_cache: empty data fingerprint")
    if complete(storage_dir, fp, daily_dir):
        log(f"#370 weekly-cache COMPLETE for fp {fp[:12]}… (manifest covers the universe) — skip")
        return "complete"
    log(f"#370 weekly-cache incomplete for fp {fp[:12]}… — building (build_warmup_cache → write_weekly)")
    runner([sys.executable, str(_ROOT / "scripts" / "build_warmup_cache.py"),
            "--out", str(cache_root)], check=True)
    # CRITICAL (#370 code-review): forward --daily-dir so the BUILD signs universe_sig over the SAME
    # universe weekly_cache_complete CHECKS. Without it, build signs _DEFAULT_DAILY while the check
    # signs `daily_dir` → permanent sig mismatch → always-incomplete → fail-loud raises every run on
    # any custom universe. They must sign the identical set.
    runner([sys.executable, str(_ROOT / "scripts" / "write_weekly_objectstore.py"),
            "--fp", fp, "--cache-root", str(cache_root), "--storage", str(storage_dir),
            "--daily-dir", str(daily_dir)], check=True)
    if not weekly_cache_present(storage_dir, fp):
        raise RuntimeError(
            f"#368 weekly-cache build for fp {fp[:12]}… produced 0 keys — fail-loud (a trimmed-warmup "
            f"sweep on an empty cache would silently 0-trade)"
        )
    if not complete(storage_dir, fp, daily_dir):
        raise RuntimeError(
            f"#370 weekly-cache build for fp {fp[:12]}… still INCOMPLETE after build — the coverage "
            f"manifest is missing or does not cover the requested universe. A trimmed-warmup sweep "
            f"would hit a WeeklyCacheGapError on the uncovered (sym,date). Never ship a partial cache."
        )
    log(f"#370 weekly-cache BUILT + COMPLETE for fp {fp[:12]}…")
    return "built"
