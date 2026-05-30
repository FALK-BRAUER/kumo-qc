"""Tests for runtime.lean_entry — the #182 site. The pure loader is hard-tested here.

The two anti-#182 failure modes:
  1. missing key            -> UniverseLoadError (never fall through to trade-everything)
  2. present-but-DIFFERENT-bytes under the same key -> UniverseFingerprintError (cloud
     ObjectStore bytes != local -> scream, don't silently diverge)
plus the happy path (state assigned) and active_set_hash determinism.
"""
from __future__ import annotations

import json

import pytest

from engine.base import UniverseFingerprintError, UniverseLoadError
from runtime.fingerprints import membership_hash, order_hash
from runtime.lean_entry import active_set_hash, load_universe

# Small synthetic artifacts (as build_filter / build_universe would emit, incl. a meta block).
ELIGIBLE = {
    "2025-01-02": {"aaa": 2.0e7, "zzz": 1.0e8},
    "2025-01-03": {"mmm": 5.0e7},
    "_filter_meta": {"min_price": 10.0},
}
UNIVERSE = {
    "2025-01-02": ["zzz", "aaa"],   # rank order (DV desc)
    "2025-01-03": ["mmm"],
    "_universe_meta": {"coarse_max": 9999},
}
# Pinned fps = hash of the date-keyed entries only (meta stripped), via the shared module.
_ELIG_DATED = {k: v for k, v in ELIGIBLE.items() if not k.startswith("_")}
_UNI_DATED = {k: v for k, v in UNIVERSE.items() if not k.startswith("_")}
MEMBERSHIP_FP = membership_hash(_ELIG_DATED)
ORDER_FP = order_hash(_UNI_DATED)


class FakeObjectStore:
    def __init__(self, blobs: dict[str, str]) -> None:
        self._blobs = blobs

    def contains_key(self, key: str) -> bool:
        return key in self._blobs

    def read(self, key: str) -> str:
        return self._blobs[key]


class FakeQC:
    def __init__(self, blobs: dict[str, str]) -> None:
        self.object_store = FakeObjectStore(blobs)


def _blobs(eligible=ELIGIBLE, universe=UNIVERSE) -> dict[str, str]:
    return {"elig.json": json.dumps(eligible), "uni.json": json.dumps(universe)}


def _load(qc) -> None:
    load_universe(
        qc,
        eligible_key="elig.json",
        universe_key="uni.json",
        expected_membership_fp=MEMBERSHIP_FP,
        expected_order_fp=ORDER_FP,
    )


def test_happy_path_assigns_state_meta_stripped():
    qc = FakeQC(_blobs())
    _load(qc)
    assert qc._eligible == _ELIG_DATED          # meta stripped
    assert qc._universe == _UNI_DATED
    assert "_filter_meta" not in qc._eligible
    assert qc._universe["2025-01-02"] == ["zzz", "aaa"]  # rank order preserved


def test_missing_eligible_key_fails_loud():
    qc = FakeQC({"uni.json": json.dumps(UNIVERSE)})  # no elig.json
    with pytest.raises(UniverseLoadError, match="missing"):
        _load(qc)


def test_missing_universe_key_fails_loud():
    qc = FakeQC({"elig.json": json.dumps(ELIGIBLE)})  # no uni.json
    with pytest.raises(UniverseLoadError, match="missing"):
        _load(qc)


def test_tampered_eligible_bytes_fail_fingerprint():
    # THE anti-#182 test: same key, DIFFERENT bytes (an extra eligible ticker) -> the
    # recomputed membership fp != pinned -> raise. Cloud-bytes != local-bytes is caught.
    tampered = {**ELIGIBLE, "2025-01-02": {"aaa": 2.0e7, "zzz": 1.0e8, "EXTRA": 9.0e9}}
    qc = FakeQC(_blobs(eligible=tampered))
    with pytest.raises(UniverseFingerprintError, match="membership"):
        _load(qc)


def test_tampered_universe_order_fails_fingerprint():
    # Same members, DIFFERENT rank order -> membership fp still matches but order fp differs
    # -> raise. Proves the order fingerprint catches a rank divergence the membership misses.
    reordered = {**UNIVERSE, "2025-01-02": ["aaa", "zzz"]}  # was ["zzz","aaa"]
    qc = FakeQC(_blobs(universe=reordered))
    with pytest.raises(UniverseFingerprintError, match="order"):
        _load(qc)


def test_nondict_json_fails_loud():
    qc = FakeQC({"elig.json": json.dumps([1, 2, 3]), "uni.json": json.dumps(UNIVERSE)})
    with pytest.raises(UniverseLoadError):
        _load(qc)


def test_no_state_assigned_on_failure():
    # Fail-loud must leave qc clean — no half-loaded _eligible without _universe.
    qc = FakeQC({"elig.json": json.dumps(ELIGIBLE)})  # uni missing -> raises after elig read
    with pytest.raises(UniverseLoadError):
        _load(qc)
    assert not hasattr(qc, "_universe")
    # _eligible must not be assigned either — assignment happens only after BOTH verify.
    assert not hasattr(qc, "_eligible")


def test_active_set_hash_deterministic_order_independent():
    c1, h1 = active_set_hash(["GOOG", "AAPL", "MSFT"])
    c2, h2 = active_set_hash(["MSFT", "GOOG", "AAPL"])  # different order, same set
    assert (c1, h1) == (c2, h2)
    assert c1 == 3 and len(h1) == 64


def test_active_set_hash_changes_on_membership():
    _, h1 = active_set_hash(["AAPL", "MSFT"])
    _, h2 = active_set_hash(["AAPL", "MSFT", "NVDA"])
    assert h1 != h2
