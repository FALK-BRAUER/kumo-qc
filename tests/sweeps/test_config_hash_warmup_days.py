"""#368 — config_hash folds warmup_days only when !=560 (backward-compat: default hashes unmoved)."""
from __future__ import annotations

from sweeps.types import PhaseChoice, SweepConfig

_BASE = (PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),)


def test_default_560_hash_unchanged() -> None:
    c = SweepConfig(choices=_BASE)
    # explicit 560 == default → the fold does NOT move the canonical (archive/dist-pin) hash
    assert SweepConfig(choices=_BASE, warmup_days=560).config_hash == c.config_hash


def test_trimmed_320_distinct_hash() -> None:
    # a trimmed champion gets a DISTINCT hash → no archive collision / stale-serve vs full-warmup
    assert SweepConfig(choices=_BASE, warmup_days=320).config_hash != SweepConfig(choices=_BASE).config_hash
