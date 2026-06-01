"""#276b-1 — config_hash STRUCTURAL-field exclude (_HASH_EXCLUDE).

A structural field (sizing `resolution` — clock-routing, phase-determined + chain-guard-enforced) is
EXCLUDED from the config_hash: it carries no behavioral identity (the phase sets already differ).
The decisive gates (HQ): champion_asis returns to its EXACT e573e84b1ce1 baseline; a NON-structural
param change STILL moves the hash (no over-exclude); the engine and build hash impls MATCH (the
build pin is asserted == the engine hash — they must not drift, the DRY caveat #297).
"""
from __future__ import annotations

import copy

import pytest

import strategies.champion_asis as ca
import strategies.champion_intraday as ci
from build.cloud_package import _config_hash as build_hash
from engine.engine import _config_hash as engine_hash

_BASELINE = "e573e84b1ce1"


def _sizing_slot(cfg):
    s = cfg.phases["sizing"]
    return s[0] if isinstance(s, list) else s


def test_champion_asis_hash_is_exactly_the_baseline() -> None:
    # THE decisive proof: adding the structural `resolution` knob to the shared sizer must NOT move
    # champion_asis off its gate-3 baseline pin.
    assert engine_hash(ca.CONFIG) == _BASELINE
    assert build_hash(ca.CONFIG) == _BASELINE


def test_engine_and_build_hash_match_dry() -> None:
    # The two _config_hash impls (engine + build/cloud_package) MUST produce identical hashes — the
    # build pin is asserted == the engine pin. Guards the DRY duplication (#297) from drifting.
    for cfg in (ca.CONFIG, ci.CONFIG):
        assert engine_hash(cfg) == build_hash(cfg)


def test_structural_resolution_change_does_not_move_hash() -> None:
    cfg = copy.deepcopy(ca.CONFIG)
    _sizing_slot(cfg).params.resolution = "intraday"
    assert engine_hash(cfg) == _BASELINE
    assert build_hash(cfg) == _BASELINE


def test_nonstructural_param_change_DOES_move_hash() -> None:
    # the exclude must NOT over-exclude: a real behavioral param (position_pct) still changes the hash.
    cfg = copy.deepcopy(ca.CONFIG)
    _sizing_slot(cfg).params.position_pct = 0.11
    assert engine_hash(cfg) != _BASELINE
    assert build_hash(cfg) != _BASELINE


def test_champion_intraday_hash_stable_and_distinct() -> None:
    h = engine_hash(ci.CONFIG)
    assert h != _BASELINE
    assert h == build_hash(ci.CONFIG)
    # resolution-independence: flipping the sizer back to daily (structural) doesn't move it
    cfg = copy.deepcopy(ci.CONFIG)
    _sizing_slot(cfg).params.resolution = "daily"
    assert engine_hash(cfg) == h
