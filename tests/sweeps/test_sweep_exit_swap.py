"""#339 — the sweep exit-swap config-model extension + its parity gate.

sweep_to_strategy_config swaps exit_hard (and adds exit_rotation) in addition to signal/entry/
sizing/regime — the reusable unlock for ALL exit/trail/rotation experiments. The HARD invariant: a
SweepConfig with NO exit choice resolves to the champion base exit verbatim AND hashes unchanged
(e3b0c44298fc flag-OFF / 4c2fc8e40607 flag-ON) — the extension must not perturb the base. Post-#339
S1 promotion the champion base exit is CloudAdherenceTrail (was KijunG3); the identity hashes are
unaffected because they hash choices, not the resolved base.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "build")]

from build.sweep_build import UnsupportedSweepAxisError, _resolve_impl, sweep_to_strategy_config  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig  # noqa: E402


def _exit_slots(sc):
    ex = sc.phases["exit_hard"]
    return ex if isinstance(ex, list) else [ex]


def test_resolver_finds_exit_family_under_phases_exit():
    # exit kinds live under phases.exit/ (dir != kind) — the _KIND_PKG map resolves them.
    assert _resolve_impl("exit_hard", "kijun_g3_exits").__name__ == "KijunG3Exits"
    assert _resolve_impl("exit_hard", "cloud_adherence_trail").__name__ == "CloudAdherenceTrail"
    assert _resolve_impl("exit_hard", "mfe_intraday_exit").__name__ == "MfeIntradayExit"


def test_no_exit_choice_resolves_to_champion_base_exit_and_hash():
    # #339 S1 PROMOTION: the champion base IS the no-override resolution (sweep_build.BASE_MODULE =
    # champion_intraday_gapvol). The champion now wires the S1 winner CloudAdherenceTrail, so a
    # SweepConfig with NO exit choice resolves to CloudAdherenceTrail (NOT the pre-S1 KijunG3).
    # The SweepConfig identity hashes are UNAFFECTED — they hash choices, not the resolved base.
    base = SweepConfig(choices=())
    assert base.config_hash == "e3b0c44298fc"
    sc = sweep_to_strategy_config(base)
    assert _exit_slots(sc)[0].impl.__name__ == "CloudAdherenceTrail"
    # flag-ON (no exit choice) resolves to the same champion base + keeps its own identity hash.
    on = SweepConfig(choices=(), continuous_weekly=True)
    assert on.config_hash == "4c2fc8e40607"
    assert _exit_slots(sweep_to_strategy_config(on))[0].impl.__name__ == "CloudAdherenceTrail"


def test_exit_hard_swap_replaces_impl():
    ch = PhaseChoice(kind="exit_hard", impl_name="cloud_adherence_trail", params=(), free_params=0)
    sc = sweep_to_strategy_config(SweepConfig(choices=(ch,), continuous_weekly=True))
    slots = _exit_slots(sc)
    assert len(slots) == 1  # swap, not append
    assert slots[0].impl.__name__ == "CloudAdherenceTrail"


def test_exit_swap_gets_distinct_identity():
    # a different exit = a different strategy = a different config_hash (own archive).
    ch = PhaseChoice(kind="exit_hard", impl_name="cloud_adherence_trail", params=(), free_params=0)
    swapped = SweepConfig(choices=(ch,), continuous_weekly=True)
    assert swapped.config_hash not in ("e3b0c44298fc", "4c2fc8e40607")


def test_multiple_exit_hard_choices_compose_as_exit_list():
    scratch = PhaseChoice(kind="exit_hard", impl_name="scratch_flat_exit", params=(), free_params=0)
    mfe = PhaseChoice(kind="exit_hard", impl_name="mfe_intraday_exit", params=(), free_params=0)
    sc = sweep_to_strategy_config(
        SweepConfig(
            choices=(
                PhaseChoice(kind="trail", impl_name="position_path_tracker", params=(), free_params=0),
                scratch,
                mfe,
            ),
            continuous_weekly=True,
        )
    )

    slots = _exit_slots(sc)
    assert [slot.impl.__name__ for slot in slots] == ["ScratchFlatExit", "MfeIntradayExit"]
    assert {slot.impl.PHASE_RESOLUTION for slot in slots} == {"intraday"}


def test_duplicate_single_slot_choice_fails_loud():
    a = PhaseChoice(kind="ranking", impl_name="george_industry_attention", params=(), free_params=0)
    b = PhaseChoice(kind="ranking", impl_name="george_industry_attention", params=(), free_params=0)

    with pytest.raises(UnsupportedSweepAxisError, match="single-slot"):
        sweep_to_strategy_config(
            SweepConfig(choices=(a, b), continuous_weekly=True),
            base_module="strategies.champion_george_context",
        )
