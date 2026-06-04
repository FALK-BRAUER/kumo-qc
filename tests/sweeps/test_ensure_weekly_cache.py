"""#368/#370 — tests for the pre-sweep weekly-cache orchestration: the #370 PRINCIPLED completeness
invariant (coverage manifest tied to data_fp + universe), idempotent skip, and fail-loud build."""
from __future__ import annotations

import pytest

from sweeps.warmup_cache.ensure import (
    ensure_weekly_cache,
    read_cache_manifest,
    universe_signature,
    weekly_cache_complete,
)

FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"
OTHER_FP = "deadbeef" * 8


def _mk_universe(daily: "object", tickers: list[str]) -> None:
    for t in tickers:
        (daily / f"{t}.zip").write_text("x")  # content irrelevant — signature is over the ticker set


# ── universe signature ───────────────────────────────────────────────────────────────────────
def test_universe_signature_deterministic_and_order_independent(tmp_path) -> None:
    d1 = tmp_path / "d1"; d1.mkdir(); _mk_universe(d1, ["aapl", "msft", "nvda"])
    d2 = tmp_path / "d2"; d2.mkdir(); _mk_universe(d2, ["nvda", "aapl", "msft"])  # different create order
    s1, n1 = universe_signature(d1)
    s2, n2 = universe_signature(d2)
    assert s1 == s2 and n1 == n2 == 3            # sorted → order-independent
    _mk_universe(d2, ["extra"])                   # add a ticker → signature changes
    assert universe_signature(d2)[0] != s2


# ── manifest round-trip + completeness ─────────────────────────────────────────────────────────
def test_complete_false_without_manifest(tmp_path) -> None:
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl"])
    storage = tmp_path / "storage"; storage.mkdir()
    # a key exists but NO manifest → the partial-cache case → NOT complete (the #370 bug class)
    (storage / f"weekly_ichimoku-{FP}-AAPL").write_text("{}")
    assert weekly_cache_complete(storage, FP, daily) is False


def test_complete_true_with_matching_manifest(tmp_path) -> None:
    from sweeps.warmup_cache.ensure import write_cache_manifest
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl", "msft"])
    storage = tmp_path / "storage"; storage.mkdir()
    sig, n = universe_signature(daily)
    write_cache_manifest(storage, FP, universe_sig=sig, n_universe=n, n_built=2, n_keys=10)
    assert weekly_cache_complete(storage, FP, daily) is True
    assert read_cache_manifest(storage, FP)["universe_sig"] == sig
    assert not list(storage.glob("*.tmp"))        # atomic write left no tmp


def test_complete_false_on_wrong_fp_or_stale_universe(tmp_path) -> None:
    from sweeps.warmup_cache.ensure import write_cache_manifest
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl"])
    storage = tmp_path / "storage"; storage.mkdir()
    sig, n = universe_signature(daily)
    write_cache_manifest(storage, FP, universe_sig=sig, n_universe=n, n_built=1, n_keys=5)
    assert weekly_cache_complete(storage, OTHER_FP, daily) is False   # manifest is for FP, not OTHER_FP
    _mk_universe(daily, ["nvda"])                                     # universe grew since the build
    assert weekly_cache_complete(storage, FP, daily) is False         # stale universe_sig → rebuild


# ── ensure_weekly_cache orchestration ────────────────────────────────────────────────────────
def test_ensure_skips_when_complete() -> None:
    calls = []
    out = ensure_weekly_cache(
        FP, storage_dir="/x", cache_root="/y", daily_dir="/z",
        runner=lambda *a, **k: calls.append(a),          # must NOT be called
        complete=lambda _s, _f, _d: True, log=lambda _m: None,
    )
    assert out == "complete" and calls == []             # coverage-tied idempotent skip


def test_ensure_builds_when_incomplete(tmp_path) -> None:
    storage = tmp_path / "storage"; storage.mkdir()
    ran = []

    def runner(argv, **k):
        ran.append(argv[1].split("/")[-1])
        if "write_weekly_objectstore.py" in argv[1]:     # the build's 2nd step writes a key
            (storage / f"weekly_ichimoku-{FP}-AAPL").write_text("{}")

    seq = iter([False, True])                            # incomplete first, complete after build
    out = ensure_weekly_cache(
        FP, storage_dir=storage, cache_root="/y", daily_dir="/z",
        runner=runner, complete=lambda _s, _f, _d: next(seq), log=lambda _m: None,
    )
    assert out == "built"
    assert ran == ["build_warmup_cache.py", "write_weekly_objectstore.py"]  # proven chain, in order


def test_ensure_fail_loud_zero_keys(tmp_path) -> None:
    storage = tmp_path / "storage"; storage.mkdir()      # build no-ops → stays empty
    with pytest.raises(RuntimeError, match="produced 0 keys"):
        ensure_weekly_cache(
            FP, storage_dir=storage, cache_root="/y", daily_dir="/z",
            runner=lambda *a, **k: None, complete=lambda _s, _f, _d: False, log=lambda _m: None,
        )


def test_ensure_fail_loud_incomplete_after_build(tmp_path) -> None:
    # build writes a KEY but no covering manifest → present() True but complete() False → fail loud
    storage = tmp_path / "storage"; storage.mkdir()

    def runner(argv, **k):
        if "write_weekly_objectstore.py" in argv[1]:
            (storage / f"weekly_ichimoku-{FP}-AAPL").write_text("{}")   # key, but NO manifest

    with pytest.raises(RuntimeError, match="still INCOMPLETE"):
        ensure_weekly_cache(
            FP, storage_dir=storage, cache_root="/y", daily_dir="/z",
            runner=runner, complete=lambda _s, _f, _d: False, log=lambda _m: None,
        )


def test_ensure_rejects_empty_fp() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        ensure_weekly_cache("", storage_dir="/x", cache_root="/y")
