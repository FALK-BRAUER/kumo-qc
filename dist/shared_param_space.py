from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParamSpace:

    axes: dict[str, Sequence[object]]

    @property
    def grid_size(self) -> int:
        size = 1
        for values in self.axes.values():
            size *= len(values)
        return size

    @property
    def free_param_count(self) -> int:
        return len(self.axes)


@dataclass(frozen=True, slots=True)
class ComplexityDecl:

    free_params: int
    note: str = ""

    def validate(self, space: ParamSpace) -> None:
        if self.free_params != space.free_param_count:
            raise ValueError(
                f"ComplexityDecl.free_params={self.free_params} != "
                f"space().free_param_count={space.free_param_count} — every swept axis "
                "must be counted in the complexity declaration (no hidden knobs)."
            )
