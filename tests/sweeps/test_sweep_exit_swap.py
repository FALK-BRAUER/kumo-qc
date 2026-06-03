"""#339 — the sweep exit-swap config-model extension + its parity gate.

sweep_to_strategy_config now swaps exit_hard (and adds exit_rotation) in addition to signal/entry/
sizing/regime — the reusable unlock for ALL exit/trail/rotation experiments. The HARD invariant: a
SweepConfig with NO exit choice leaves the champion's exit (KijunG3Exits) verbatim AND hashes
unchanged (e3b0c44298fc flag-OFF / 4c2fc8e40607 flag-ON) — the extension must not perturb the base.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "build")]

from build.sweep_build import _resolve_impl, sweep_to_strategy_config  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig  # noqa: E402


def _exit_slots(sc):
    ex = sc.phases["exit_hard"]
    return ex if isinstance(ex, list) else [ex]


def test_resolver_finds_exit_family_under_phases_exit():
    # exit kinds live under phases.exit/ (dir != kind) — the _KIND_PKG map resolves them.
    assert _resolve_impl("exit_hard", "kijun_g3_exits").__name__ == "KijunG3Exits"
    assert _resolve_impl("exit_hard", "cloud_adherence_trail").__name__ == "CloudAdherenceTrail"


def test_no_exit_choice_keeps_base_exit_and_hash():
    # PARITY: base (no exit choice) → KijunG3 verbatim + canonical hash unchanged.
    base = SweepConfig(choices=())
    assert base.config_hash == "e3b0c44298fc"
    sc = sweep_to_strategy_config(base)
    assert _exit_slots(sc)[0].impl.__name__ == "KijunG3Exits"
    # flag-ON (no exit choice) still keeps KijunG3 + its own identity.
    on = SweepConfig(choices=(), continuous_weekly=True)
    assert on.config_hash == "4c2fc8e40607"
    assert _exit_slots(sweep_to_strategy_config(on))[0].impl.__name__ == "KijunG3Exits"


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
