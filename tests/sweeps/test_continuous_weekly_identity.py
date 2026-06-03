"""#336/#338 — config-identity parity gate for the CONTINUOUS_WEEKLY fix.

The fix is a DIFFERENT strategy (different decisions on the corrected weekly) → it gets its own
config_hash + archive. The hard invariant: folding the flag into the identity must NOT move the
legacy/canonical hash — an all-default (flag-OFF) config must STILL hash to e3b0c44298fc, so every
canonical archive/test/dist-pin key stays put. The flag enters the hash ONLY when non-default (ON).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from sweeps.types import SweepConfig  # noqa: E402

_CANONICAL = "e3b0c44298fc"  # the pure-base champion (flag-OFF) — must never move


def test_flag_off_hash_unchanged() -> None:
    """flag-OFF (default) hashes EXACTLY as the legacy world — the canonical key is preserved."""
    assert SweepConfig(choices=()).config_hash == _CANONICAL
    assert SweepConfig(choices=(), continuous_weekly=False).config_hash == _CANONICAL


def test_flag_on_hash_distinct() -> None:
    """flag-ON gets a DISTINCT identity → its own archive (no conflation with flag-OFF)."""
    off = SweepConfig(choices=())
    on = SweepConfig(choices=(), continuous_weekly=True)
    assert on.config_hash != off.config_hash
    assert on.config_hash != _CANONICAL


def test_flag_on_hash_deterministic() -> None:
    """The flag-ON identity is stable (deterministic digest, not run-dependent)."""
    a = SweepConfig(choices=(), continuous_weekly=True).config_hash
    b = SweepConfig(choices=(), continuous_weekly=True).config_hash
    assert a == b
