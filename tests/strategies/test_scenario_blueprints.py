"""#386 scenario blueprint composition gates."""
from __future__ import annotations

from typing import Any

from engine.config import Slot
from engine.engine import FIRE_ENTRIES, StrategyEngine
from strategies.blueprints import scenario_a, scenario_b, scenario_c, scenario_c_wide_entry


class FakeQC:
    """Minimal QC stand-in for engine construction."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def Log(self, msg: str) -> None:
        self.lines.append(msg)

    def log(self, msg: str) -> None:
        self.lines.append(msg)


def _kind_names(order: list[Any]) -> list[str]:
    return [item for item in order if isinstance(item, str)]


def _slot_impls(value: Any) -> tuple[type[Any], ...]:
    slots = value if isinstance(value, list) else [value]
    return tuple(slot.impl for slot in slots if isinstance(slot, Slot))


def test_scenario_blueprints_compose_and_route_two_clock() -> None:
    for module in (scenario_a, scenario_b, scenario_c, scenario_c_wide_entry):
        eng = StrategyEngine(config=module.CONFIG, qc=FakeQC())
        daily = _kind_names(eng._daily_order)
        intraday = _kind_names(eng._intraday_order)

        assert "universe" in daily
        assert "signal" in daily
        assert "entry_selection" in daily
        assert "arm" in daily
        assert "entry_trigger" in intraday
        assert "intraday_sizing" in intraday
        assert FIRE_ENTRIES in eng._intraday_order
        assert "sizing" not in eng.phases
        assert "intraday_sizing" in eng.phases


def test_scenario_b_uses_distinct_catalog_stack() -> None:
    a = scenario_a.CONFIG.phases
    b = scenario_b.CONFIG.phases

    for kind in ("universe", "signal", "regime", "ranking", "entry_selection",
                 "entry_trigger", "intraday_sizing", "stops_initial", "exit_hard"):
        assert _slot_impls(a[kind]) != _slot_impls(b[kind])


def test_scenario_c_wide_entry_is_param_variant_only() -> None:
    c = scenario_c.CONFIG.phases
    wide = scenario_c_wide_entry.CONFIG.phases

    assert set(c) == set(wide)
    for kind in c:
        assert _slot_impls(c[kind]) == _slot_impls(wide[kind])

    trigger = wide["entry_trigger"]
    base_trigger = c["entry_trigger"]
    assert isinstance(trigger, Slot)
    assert isinstance(base_trigger, Slot)
    assert trigger.params.near_pct != base_trigger.params.near_pct
