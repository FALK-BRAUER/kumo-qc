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


# ── #370 code-review fixes ───────────────────────────────────────────────────────────────────
def test_universe_signature_fail_loud_on_empty(tmp_path) -> None:
    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(RuntimeError, match="0 daily-zip tickers"):  # mis-pathed/empty must CRASH
        universe_signature(empty)


def test_universe_signature_excludes_dotfiles(tmp_path) -> None:
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl", "msft"])
    (daily / ".partial.zip").write_text("x")          # editor temp / partial download
    sig_with_dotfile, n = universe_signature(daily)
    clean = tmp_path / "clean"; clean.mkdir(); _mk_universe(clean, ["aapl", "msft"])
    assert universe_signature(clean) == (sig_with_dotfile, n) == universe_signature(clean)
    assert n == 2                                     # the dotfile is NOT counted


def test_read_manifest_non_dict_returns_none(tmp_path) -> None:
    from sweeps.warmup_cache.ensure import _manifest_path
    storage = tmp_path / "storage"; storage.mkdir()
    _manifest_path(storage, FP).write_text("[1, 2, 3]")   # valid JSON, but a list not a dict
    assert read_cache_manifest(storage, FP) is None       # malformed → incomplete, not a crash


def test_ensure_build_check_signature_agreement_custom_universe(tmp_path) -> None:
    """THE gap the stubbed-`complete` tests missed: with the REAL weekly_cache_complete + a faithful
    build that signs over the FORWARDED --daily-dir, build_sig == check_sig → 'built'. Catches the
    --daily-dir non-forwarding CRITICAL (build would sign the default, check the custom → never agree)."""
    from sweeps.warmup_cache.ensure import write_cache_manifest
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl", "msft", "nvda"])
    storage = tmp_path / "storage"; storage.mkdir()

    def faithful_runner(argv, **k):
        if "write_weekly_objectstore.py" in argv[1]:
            dd = argv[argv.index("--daily-dir") + 1]          # ensure MUST have forwarded it
            fp = argv[argv.index("--fp") + 1]
            sig, n = universe_signature(dd)                   # sign over the forwarded dir (real behavior)
            (storage / f"weekly_ichimoku-{fp}-AAPL").write_text("{}")
            write_cache_manifest(storage, fp, universe_sig=sig, n_universe=n, n_built=1, n_keys=1)

    out = ensure_weekly_cache(FP, storage_dir=storage, cache_root="/y", daily_dir=daily,
                              runner=faithful_runner, log=lambda _m: None)  # REAL complete (not stubbed)
    assert out == "built"


def test_ensure_catches_daily_dir_divergence(tmp_path) -> None:
    """Proves the integration test has TEETH: a build that signs the WRONG universe (the bug — ignoring
    the forwarded --daily-dir) → check mismatch → fail-loud. (If the fix regresses, THIS fires.)"""
    from sweeps.warmup_cache.ensure import write_cache_manifest
    daily = tmp_path / "daily"; daily.mkdir(); _mk_universe(daily, ["aapl", "msft"])
    other = tmp_path / "other"; other.mkdir(); _mk_universe(other, ["zzzz"])   # different universe
    storage = tmp_path / "storage"; storage.mkdir()

    def buggy_runner(argv, **k):
        if "write_weekly_objectstore.py" in argv[1]:
            fp = argv[argv.index("--fp") + 1]
            sig, n = universe_signature(other)                # signs the WRONG universe (non-forward bug)
            (storage / f"weekly_ichimoku-{fp}-AAPL").write_text("{}")
            write_cache_manifest(storage, fp, universe_sig=sig, n_universe=n, n_built=1, n_keys=1)

    with pytest.raises(RuntimeError, match="still INCOMPLETE"):
        ensure_weekly_cache(FP, storage_dir=storage, cache_root="/y", daily_dir=daily,
                            runner=buggy_runner, log=lambda _m: None)
