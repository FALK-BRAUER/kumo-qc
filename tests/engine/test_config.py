"""Behavioral coverage for engine.config — Slot + StrategyConfig dataclasses, and the
config-handling helpers (_slots normalization, _kind_enabled, _config_hash) that operate
on those config types.

#246 [B2]: config.py had NO dedicated test (only exercised indirectly). These assert the
DATA-CARRYING behavior of the config layer: Slot/StrategyConfig defaults, single-Slot vs
list-of-Slots phase values, and the _slots() single->[single] / list->list normalization
+ enabled-rollup + canonical hash that the engine derives from a config.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from engine.base import BasePhase
from engine.config import Slot, StrategyConfig
from engine.engine import _config_hash, _kind_enabled, _slots


class _Phase(BasePhase):
    """Minimal concrete phase class to use as a Slot.impl class-reference."""

    @dataclass(slots=True)
    class Params:
        floor: float = 1.0
        enabled: bool = True


class _OtherPhase(BasePhase):
    @dataclass(slots=True)
    class Params:
        floor: float = 2.0


def _slot(impl: type[BasePhase], floor: float = 1.0, enabled: bool = True) -> Slot[object]:
    """Build a Slot[object] (the invariant type the engine config stores) so the dict/list
    values type-check under mypy --strict — Slot is invariant in P, mirroring engine usage."""
    params: object = impl.Params(floor=floor)  # type: ignore[attr-defined]
    return Slot(impl=impl, params=params, enabled=enabled)


# --------------------------------------------------------------------------- Slot defaults


def test_slot_enabled_defaults_true() -> None:
    """Happy path: a Slot constructed without `enabled` is enabled by default."""
    s: Slot[_Phase.Params] = Slot(impl=_Phase, params=_Phase.Params())
    assert s.enabled is True
    assert s.impl is _Phase
    assert s.params.floor == 1.0


def test_slot_enabled_can_be_disabled() -> None:
    """Edge: explicit enabled=False is carried through (a disabled Slot)."""
    s: Slot[_Phase.Params] = Slot(impl=_Phase, params=_Phase.Params(), enabled=False)
    assert s.enabled is False


def test_slot_is_slots_dataclass() -> None:
    """Slot is dataclass(slots=True): unknown attribute assignment is rejected."""
    s: Slot[_Phase.Params] = Slot(impl=_Phase, params=_Phase.Params())
    with pytest.raises(AttributeError):
        s.not_a_field = 1  # type: ignore[attr-defined]


def test_slot_preserves_params_instance_identity() -> None:
    """The exact params instance handed in is the one stored (no copy/normalize)."""
    p = _Phase.Params(floor=9.0)
    s: Slot[_Phase.Params] = Slot(impl=_Phase, params=p)
    assert s.params is p
    assert s.params.floor == 9.0


# --------------------------------------------------------------- StrategyConfig defaults


def test_strategy_config_phases_defaults_empty() -> None:
    """Null/edge: StrategyConfig with no phases -> empty dict (default_factory), not shared."""
    a = StrategyConfig(name="a", version="1.0.0")
    b = StrategyConfig(name="b", version="2.0.0")
    assert a.phases == {}
    assert b.phases == {}
    a.phases["filter"] = _slot(_Phase)
    # default_factory must give each instance its OWN dict (no shared mutable default).
    assert b.phases == {}


def test_strategy_config_carries_name_and_version() -> None:
    cfg = StrategyConfig(name="champ", version="3.1.4")
    assert cfg.name == "champ"
    assert cfg.version == "3.1.4"


def test_strategy_config_holds_single_slot_value() -> None:
    """A phase kind may map to a SINGLE Slot (the common case: filter/universe/signal)."""
    s = _slot(_Phase)
    cfg = StrategyConfig(name="t", version="1", phases={"filter": s})
    assert cfg.phases["filter"] is s


def test_strategy_config_holds_list_of_slots_value() -> None:
    """A phase kind may map to a LIST of Slots (list-kinds: regime/exit_*/diagnostics)."""
    s1 = _slot(_Phase)
    s2 = _slot(_OtherPhase)
    cfg = StrategyConfig(name="t", version="1", phases={"regime": [s1, s2]})
    assert cfg.phases["regime"] == [s1, s2]


# ------------------------------------------------------------- _slots() normalization


def test_slots_normalizes_single_to_list() -> None:
    """single -> [single]."""
    s = _slot(_Phase)
    out = _slots(s)
    assert out == [s]
    assert isinstance(out, list)


def test_slots_passes_list_through() -> None:
    """list -> same list (identity, no re-wrap)."""
    s1 = _slot(_Phase)
    s2 = _slot(_Phase)
    lst: list[Slot[object]] = [s1, s2]
    out = _slots(lst)
    assert out is lst


def test_slots_handles_empty_list() -> None:
    """Edge: an empty list value normalizes to an empty list (no crash)."""
    assert _slots([]) == []


# --------------------------------------------------------------- _kind_enabled rollup


def test_kind_enabled_true_for_enabled_single() -> None:
    cfg = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, enabled=True)})
    assert _kind_enabled(cfg, "filter") is True


def test_kind_enabled_false_for_disabled_single() -> None:
    """A disabled Slot -> the kind is not enabled."""
    cfg = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, enabled=False)})
    assert _kind_enabled(cfg, "filter") is False


def test_kind_enabled_true_if_any_slot_in_list_enabled() -> None:
    """List-kind: enabled if ANY slot is enabled."""
    cfg = StrategyConfig(
        name="t", version="1",
        phases={"regime": [_slot(_Phase, enabled=False), _slot(_OtherPhase, enabled=True)]},
    )
    assert _kind_enabled(cfg, "regime") is True


def test_kind_enabled_false_if_all_slots_disabled() -> None:
    cfg = StrategyConfig(
        name="t", version="1",
        phases={"regime": [_slot(_Phase, enabled=False), _slot(_OtherPhase, enabled=False)]},
    )
    assert _kind_enabled(cfg, "regime") is False


def test_kind_enabled_false_for_absent_kind() -> None:
    """Null: a kind not present in phases -> False (not KeyError)."""
    cfg = StrategyConfig(name="t", version="1", phases={})
    assert _kind_enabled(cfg, "filter") is False


# ------------------------------------------------------------------ _config_hash


def test_config_hash_is_deterministic() -> None:
    """Same config content -> identical 12-char hex hash."""
    def mk() -> StrategyConfig:
        return StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, floor=1.0)})
    h1, h2 = _config_hash(mk()), _config_hash(mk())
    assert h1 == h2
    assert len(h1) == 12
    int(h1, 16)  # valid hex


def test_config_hash_changes_with_params() -> None:
    """Different params -> different hash (params repr is part of the canonical string)."""
    a = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, floor=1.0)})
    b = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, floor=2.0)})
    assert _config_hash(a) != _config_hash(b)


def test_config_hash_changes_with_enabled_flag() -> None:
    """Toggling a slot's enabled flag changes the hash (enabled is in the canonical string)."""
    a = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, enabled=True)})
    b = StrategyConfig(name="t", version="1", phases={"filter": _slot(_Phase, enabled=False)})
    assert _config_hash(a) != _config_hash(b)


def test_config_hash_invariant_to_kind_insertion_order() -> None:
    """Canonicalization sorts kinds: insertion order must not change the hash."""
    s_f = _slot(_Phase)
    s_u = _slot(_OtherPhase)
    a = StrategyConfig(name="t", version="1", phases={"filter": s_f, "universe": s_u})
    b = StrategyConfig(name="t", version="1", phases={"universe": s_u, "filter": s_f})
    assert _config_hash(a) == _config_hash(b)


def test_config_hash_changes_with_name() -> None:
    a = StrategyConfig(name="alpha", version="1")
    b = StrategyConfig(name="beta", version="1")
    assert _config_hash(a) != _config_hash(b)
