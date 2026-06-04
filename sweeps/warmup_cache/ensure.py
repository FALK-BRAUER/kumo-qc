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

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[2]

# the weekly-cache key prefix (mirrors runtime.warmup_weekly_cache.WEEKLY_CACHE_TYPE) — a present
# check globs storage for ANY weekly key under the fingerprint.
_WEEKLY_PREFIX = "weekly_ichimoku"


def weekly_cache_present(storage_dir: Path | str, fp: str) -> bool:
    """True iff at least one weekly-cache key for this data fingerprint exists in storage (the
    cache was built). Used for the idempotent skip."""
    return any(Path(storage_dir).glob(f"{_WEEKLY_PREFIX}-{fp}-*"))


def ensure_weekly_cache(
    fp: str,
    *,
    storage_dir: Path | str,
    cache_root: Path | str,
    runner: Callable[..., Any] = subprocess.run,
    present: Callable[[Path | str, str], bool] = weekly_cache_present,
    log: Callable[[str], None] = print,
) -> str:
    """Ensure the weekly-cache exists for `fp`. IDEMPOTENT (skip if present) + DETERMINISTIC build
    (build_warmup_cache → write_weekly_objectstore) + FAIL-LOUD (a build yielding 0 keys raises).
    Returns 'present' (skipped) or 'built'. `runner`/`present` are injectable for tests."""
    if not fp:
        raise ValueError("ensure_weekly_cache: empty data fingerprint")
    if present(storage_dir, fp):
        log(f"#368 weekly-cache present for fp {fp[:12]}… — skip (idempotent)")
        return "present"
    log(f"#368 weekly-cache absent for fp {fp[:12]}… — building (build_warmup_cache → write_weekly)")
    runner([sys.executable, str(_ROOT / "scripts" / "build_warmup_cache.py"),
            "--out", str(cache_root)], check=True)
    runner([sys.executable, str(_ROOT / "scripts" / "write_weekly_objectstore.py"),
            "--fp", fp, "--cache-root", str(cache_root), "--storage", str(storage_dir)], check=True)
    if not present(storage_dir, fp):
        raise RuntimeError(
            f"#368 weekly-cache build for fp {fp[:12]}… produced 0 keys — fail-loud (a trimmed-warmup "
            f"sweep on an empty cache would silently 0-trade)"
        )
    log(f"#368 weekly-cache BUILT for fp {fp[:12]}…")
    return "built"
