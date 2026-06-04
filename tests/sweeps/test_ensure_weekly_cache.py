"""#368 — tests for the pre-sweep weekly-cache build orchestration (idempotent + fail-loud)."""
from __future__ import annotations

import pytest

from sweeps.warmup_cache.ensure import ensure_weekly_cache

FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"


def test_ensure_skips_when_present() -> None:
    calls = []
    ensure_weekly_cache(
        FP, storage_dir="/x", cache_root="/y",
        runner=lambda *a, **k: calls.append(a),  # must NOT be called
        present=lambda _s, _f: True, log=lambda _m: None,
    )
    assert calls == []  # idempotent — no build when present


def test_ensure_builds_when_absent_then_present() -> None:
    ran = []
    # absent first; after the 2-step build, present → returns 'built'
    seq = iter([False, True])
    out = ensure_weekly_cache(
        FP, storage_dir="/x", cache_root="/y",
        runner=lambda argv, **k: ran.append(argv[1].split("/")[-1]),
        present=lambda _s, _f: next(seq), log=lambda _m: None,
    )
    assert out == "built"
    assert ran == ["build_warmup_cache.py", "write_weekly_objectstore.py"]  # the proven chain, in order


def test_ensure_fail_loud_when_build_yields_no_keys() -> None:
    # build runs but the cache is STILL absent → fail loud (never silently 0-trade a trimmed sweep)
    with pytest.raises(RuntimeError, match="produced 0 keys"):
        ensure_weekly_cache(
            FP, storage_dir="/x", cache_root="/y",
            runner=lambda *a, **k: None,
            present=lambda _s, _f: False,  # always absent → build "failed"
            log=lambda _m: None,
        )


def test_ensure_rejects_empty_fp() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        ensure_weekly_cache("", storage_dir="/x", cache_root="/y")
