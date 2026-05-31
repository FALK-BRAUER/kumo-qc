"""Tests for the shared sweep/overfitting primitives (phases.shared.param_space, #228 template)."""
from __future__ import annotations

import pytest

from phases.shared.param_space import ComplexityDecl, ParamSpace


def test_grid_size_is_product_of_axis_lengths() -> None:
    space = ParamSpace(axes={"a": (1, 2, 3), "b": (0.1, 0.2)})
    assert space.grid_size == 6
    assert space.free_param_count == 2


def test_empty_space_has_grid_size_one_and_zero_free_params() -> None:
    space = ParamSpace(axes={})
    assert space.grid_size == 1
    assert space.free_param_count == 0


def test_complexity_validate_passes_when_counts_match() -> None:
    space = ParamSpace(axes={"a": (1, 2), "b": (3, 4)})
    ComplexityDecl(free_params=2).validate(space)  # no raise


def test_complexity_validate_fails_on_hidden_knob() -> None:
    space = ParamSpace(axes={"a": (1, 2), "b": (3, 4)})
    with pytest.raises(ValueError, match="no hidden knobs"):
        ComplexityDecl(free_params=1).validate(space)  # understated -> a hidden swept knob
