"""Sizing phase: ReserveHeatcap — FlatPctHeatcap + a base-entry gross BUDGET (the #340-reserve lever).

Kind: sizing (inherited)  ·  Marker: reserve_heatcap_v1

WHY a subclass (not a param on FlatPctHeatcap.Params): the engine config_hash canonicalises the sizer
Params (FlatPctHeatcap.Params has `_HASH_EXCLUDE` → its inner-join includes every non-structural field).
Adding `base_entry_gross_budget` to the BASE Params would shift the champion hash off its e573e84b1ce1
baseline (test_config_hash_exclude pins it) even at the default. Putting the field on THIS subclass
Params keeps FlatPctHeatcap.Params byte-identical → champion hash unchanged; only configs that actually
opt into the reserve (the #340-reserve cells) get a distinct hash (distinct impl name + distinct Params).

MECHANIC (the #340-C starvation fix): base entries fill only until invested gross reaches
`base_entry_gross_budget × portfolio_value`; the remaining (1 - budget) is RESERVED cash that only the
pyramid adds (StagedRiskPyramid, bounded by GrossExposureCap at 1.0) may consume → re-concentrate the
freed cash into the ≥+5% provers WITHOUT breadth eating the cash first. Charter-compliant: a cash-reserve
(dollar amount from portfolio value, subtracted in the SAME single cash inequality), NOT a count/slot cap
— exposure stays cash-governed, single code path. The reserve arithmetic lives in FlatPctHeatcap.evaluate
(reads the budget via getattr, default 1.0) so this subclass only supplies the param.
"""
from __future__ import annotations

from dataclasses import dataclass

from phases.shared.param_space import ComplexityDecl, ParamSpace
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap


class ReserveHeatcap(FlatPctHeatcap):
    # base_entry_gross_budget is a real behavioural axis → free param (resolution stays structural).
    COMPLEXITY = ComplexityDecl(
        free_params=1,
        note="base_entry_gross_budget (reserve fraction); position_pct fixed-canonical, resolution structural.",
    )

    @dataclass(slots=True)
    class Params(FlatPctHeatcap.Params):
        # (1 - budget) of portfolio value is held back as cash only the pyramid adds may use. 1.0 = no
        # reserve = behaviour-identical to FlatPctHeatcap (but a DISTINCT hash — distinct impl + Params).
        base_entry_gross_budget: float = 1.0

        @classmethod
        def space(cls) -> ParamSpace:
            return ParamSpace(axes={"base_entry_gross_budget": (0.50, 0.70, 1.0)})

    @property
    def version_marker(self) -> str:
        return "reserve_heatcap_v1"
