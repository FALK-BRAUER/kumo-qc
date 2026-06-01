"""#318 — assert_cloud_clean: the cloud-result validity gate (CONVENTIONS §Parity).

completed=True is NOT a clean result — QC marks a crashed partial completed=True/progress=1 with
the error in bt['error']. That is how a crashed -0.611/72-order partial got banked as real last
session. These pin the gate: error≠None fails EVEN when completed (the trap), incomplete fails,
0-orders fails the liveness check, a genuinely-clean run passes.

qc_v2_cloud reads QC creds from the keychain at import — skip cleanly where that is unavailable.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
try:
    import qc_v2_cloud as q
except Exception:  # keychain / network absent (CI without creds)
    q = None

pytestmark = pytest.mark.skipif(q is None, reason="qc_v2_cloud import requires QC keychain creds")


def test_clean_run_passes() -> None:
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {"Total Orders": "14"}})
    assert ok is True and reason == "clean"


def test_completed_but_error_fails_the_trap() -> None:
    # THE #318 trap: completed/progress==1 but a runtime error present → INVALID (this is the
    # exact shape of the crashed -0.611 that got banked as a result).
    ok, reason = q.assert_cloud_clean(
        {"error": "Runtime Error: ... datetime.timedelta", "progress": 1, "statistics": {"Total Orders": "72"}}
    )
    assert ok is False and "runtime error" in reason


def test_stacktrace_also_fails() -> None:
    ok, _ = q.assert_cloud_clean({"error": None, "stacktrace": "boom", "progress": 1, "statistics": {"Total Orders": "5"}})
    assert ok is False


def test_incomplete_progress_fails() -> None:
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 0.5, "statistics": {}})
    assert ok is False and "incomplete" in reason


def test_zero_orders_fails_liveness() -> None:
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {"Total Orders": "0"}})
    assert ok is False and "liveness" in reason


def test_unparseable_order_count_fails_loud() -> None:
    # #277 hardening: an unverifiable liveness field (unparseable) must FAIL, not pass — null/quirk
    # != clean (the silent-zero-champion hole).
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {"Total Orders": "n/a"}})
    assert ok is False and "UNVERIFIABLE" in reason


def test_null_orders_without_reread_fails_loud() -> None:
    # #277: Total Orders missing + no reread → can't verify liveness → FAIL (the hold-confirm
    # smoke hole: poll returned null → the old code skipped the check → a 0-order run passed clean).
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {}})
    assert ok is False and "UNVERIFIABLE" in reason


def test_null_orders_reread_recovers() -> None:
    # null at poll → re-read returns populated stats → verify on the fresh read.
    fresh = {"error": None, "progress": 1, "statistics": {"Total Orders": "14"}}
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {}}, reread=lambda: fresh)
    assert ok is True and reason == "clean"


def test_null_orders_reread_still_null_fails_loud() -> None:
    # null at poll AND null after re-read → still unverifiable → FAIL loud (never pass null-liveness).
    stale = {"error": None, "progress": 1, "statistics": {}}
    ok, reason = q.assert_cloud_clean(stale, reread=lambda: stale)
    assert ok is False and "UNVERIFIABLE" in reason


def test_reread_recovers_zero_orders_still_fails_liveness() -> None:
    # re-read recovers a real 0 → liveness:0 fail (the hold-confirm case: real orders=0).
    fresh = {"error": None, "progress": 1, "statistics": {"Total Orders": "0"}}
    ok, reason = q.assert_cloud_clean({"error": None, "progress": 1, "statistics": {}}, reread=lambda: fresh)
    assert ok is False and "liveness" in reason
