"""Tests for runtime.fingerprints — the single-source hash used at build AND load time."""
from __future__ import annotations

from runtime.fingerprints import membership_hash, order_hash


def test_membership_hash_order_independent_and_dv_independent():
    # dict form ({ticker: dv}) and list form must hash identically (membership only).
    a = {"2025-01-02": {"zzz": 9.0, "aaa": 1.0}}
    b = {"2025-01-02": ["aaa", "zzz"]}          # same members, list form, different order
    c = {"2025-01-02": {"aaa": 5.0, "zzz": 2.0}}  # same members, different DV
    assert membership_hash(a) == membership_hash(b) == membership_hash(c)


def test_membership_hash_changes_on_membership_change():
    a = {"2025-01-02": ["aaa", "zzz"]}
    b = {"2025-01-02": ["aaa", "zzz", "mmm"]}
    assert membership_hash(a) != membership_hash(b)
    assert len(membership_hash(a)) == 64


def test_order_hash_is_order_sensitive():
    assert order_hash({"d": ["a", "b", "c"]}) != order_hash({"d": ["c", "b", "a"]})
    assert order_hash({"d": ["a", "b"]}) == order_hash({"d": ["a", "b"]})
    assert len(order_hash({"d": ["a"]})) == 64


def test_membership_vs_order_distinct():
    # membership ignores order; order does not — the two fingerprints answer different
    # questions (same set? same ranked sequence?).
    u1 = {"d": ["a", "b", "c"]}
    u2 = {"d": ["c", "b", "a"]}
    assert membership_hash(u1) == membership_hash(u2)   # same set
    assert order_hash(u1) != order_hash(u2)             # different order
