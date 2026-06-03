"""SweepConfig → StrategyConfig → dist bridge (#323 prod wiring — the call-site #214/#323 left).

A SweepConfig (tuple of PhaseChoice{kind, impl_name, params}) carries ONLY the swept phases.
A deployable cloud dist needs the FULL champion stack, so this bridge OVERRIDES the swept kinds
onto the champion_intraday_gapvol BASE config, then build_from_config() emits the dist.

Registry-by-convention (config.py has NO runtime registry — direct class refs): a phase impl
resolves from its path `phases.<kind>.<impl_name>.<impl_name>` → the PascalCase class. Verified
against the real tree (signal/bct_score_full/bct_score_full.py::BctScoreFull, etc.).

FAIL-LOUD on every gap (charter: NO silent no-ops — a silent no-op makes the sweep "think" it
tested an axis it didn't, the exact W5-mirage class of error):
  - entries_cap (sizing hook): NO explicit max-positions param exists yet. A non-None value
    RAISES UnsupportedSweepAxisError — building it would yield 15≡None (a silent no-op + a
    duplicate BT). Round-1 fires entries_cap=None only; the explicit cap is a fast-follow.
  - lower_wick_booster (gap_loud_wick / Rank-3): no phase field yet → RAISES. Not in coarse.
  - any swept param that, AFTER remap, is not a real field of the impl's Params → RAISES
    (a grid-axis/phase-field naming drift can never silently pass).

Logical-axis → phase-field remap (the grid uses sweep-design names, not always the Params
field name): hold's `hold_n_bars` → `window_bars`. Extend REMAP as axes are added.

spy_200ma rides on the regime PhaseChoice but is a SEPARATE phase (SpySma200): the bridge
SPLITS it — spy_200ma toggles the base SpySma200 slot's `enabled`; the vix params go to the
VixPercentile slot.
"""
from __future__ import annotations

import dataclasses
import importlib
from pathlib import Path
from typing import Any, cast

from engine.config import Slot, StrategyConfig

BASE_MODULE = "strategies.champion_intraday_gapvol"

# logical grid-axis name → real phase Params field, keyed by (kind, impl_name)
REMAP: dict[tuple[str, str], dict[str, str]] = {
    ("entry_selection", "bct_intraday_hold_confirm"): {"hold_n_bars": "window_bars"},
}

# swept params that are HOOKS with no backing phase field yet → fail loud unless at their
# off/default value. Maps (kind, impl_name) → {param: off_value}.
UNSUPPORTED_HOOKS: dict[tuple[str, str], dict[str, Any]] = {
    ("sizing", "flat_pct_heatcap"): {"entries_cap": None},
    ("entry_selection", "bct_intraday_gap_vol_confirm"): {"lower_wick_booster": False},
}


# entry_selection sub-phases that are GUARDS (kept on every variant), not the swept algorithm.
ENTRY_GUARDS = frozenset({"preflight_staleness"})

# kind → phases.<pkg> dir, for kinds whose package name differs from the kind (#339). The exit
# family (exit_hard/exit_target/exit_regime/exit_rotation) all live under phases.exit/; without this
# the phases.<kind>.<impl> convention would look in nonexistent phases.exit_hard/ etc.
_KIND_PKG: dict[str, str] = {
    "exit_hard": "exit", "exit_target": "exit", "exit_regime": "exit", "exit_rotation": "exit",
}


class UnsupportedSweepAxisError(RuntimeError):
    """A swept axis has no backing phase param yet — fail loud rather than build a silent no-op."""


def _pascal(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def _resolve_impl(kind: str, impl_name: str) -> type:
    """phases.<pkg>.<impl_name>.<impl_name> → the PascalCase phase class (convention). pkg == kind
    except the exit family, which lives under phases.exit/ (see _KIND_PKG)."""
    pkg = _KIND_PKG.get(kind, kind)
    mod = importlib.import_module(f"phases.{pkg}.{impl_name}.{impl_name}")
    cls = getattr(mod, _pascal(impl_name), None)
    if cls is None:
        raise UnsupportedSweepAxisError(
            f"phase class {_pascal(impl_name)!r} not found in phases.{kind}.{impl_name} "
            f"(registry-by-convention miss)"
        )
    return cast(type, cls)


def _base_slot(base: StrategyConfig, kind: str) -> Slot[object]:
    slot = base.phases.get(kind)
    if isinstance(slot, list):  # list-kinds (regime) handled by the caller, not here
        raise ValueError(f"_base_slot called on list-kind {kind!r}")
    if slot is None:
        raise UnsupportedSweepAxisError(f"base config has no {kind!r} slot to override")
    return slot


def _apply_params(kind: str, impl_name: str, swept: dict[str, Any], base_params: Any) -> Any:
    """Remap logical names, fail loud on unsupported hooks / unknown fields, then either
    dataclasses.replace the base params (same impl) or build fresh (impl swap)."""
    # 1. fail loud on a set hook
    for hook, off in UNSUPPORTED_HOOKS.get((kind, impl_name), {}).items():
        if hook in swept and swept[hook] != off:
            raise UnsupportedSweepAxisError(
                f"{kind}.{impl_name}.{hook}={swept[hook]!r} — no backing phase param yet "
                f"(off={off!r}); building it would be a silent no-op. Fail loud (#323 round gating)."
            )
    # 2. drop hooks now confirmed at their off value, then remap logical → field names
    hooks = UNSUPPORTED_HOOKS.get((kind, impl_name), {})
    remap = REMAP.get((kind, impl_name), {})
    resolved: dict[str, Any] = {}
    for k, v in swept.items():
        if k in hooks:
            continue  # at off value → no-op, intentionally not wired
        resolved[remap.get(k, k)] = v
    # 3. validate every resolved key is a real Params field — naming drift fails loud
    valid = {f.name for f in dataclasses.fields(base_params)}
    bad = set(resolved) - valid
    if bad:
        raise UnsupportedSweepAxisError(
            f"{kind}.{impl_name}: swept params {sorted(bad)} are not fields of {type(base_params).__name__} "
            f"(valid: {sorted(valid)}) — grid-axis/phase-field naming drift; fail loud."
        )
    return dataclasses.replace(base_params, **resolved)


def _override_slot(kind: str, ch: Any, base_slot: Slot[object] | None) -> Slot[object]:
    """The swept Slot: same impl as the base → dataclasses.replace its params; an impl SWAP →
    a fresh impl with its default Params, then override the swept fields."""
    swept = ch.param_dict()
    base_snake = base_slot.impl.__module__.rsplit(".", 1)[-1] if base_slot is not None else None
    if base_slot is not None and ch.impl_name == base_snake:
        params = _apply_params(kind, ch.impl_name, swept, base_slot.params)
        return Slot(impl=base_slot.impl, params=params, enabled=True)
    impl = _resolve_impl(kind, ch.impl_name)
    fresh = impl.Params()  # type: ignore[attr-defined]  # phases declare Params by convention
    # On an impl SWAP, carry the base slot's STRUCTURAL (_HASH_EXCLUDE) fields onto the fresh params —
    # e.g. `resolution` (the entry-execution-chain clock) is BASE-determined, not swept; a fresh impl's
    # default ("daily") would mismatch an intraday FIRE_ENTRIES → the chain-clock guard fails loud
    # (#276b-1). Structural fields don't affect config_hash, so this is parity-safe. (#339: RiskBasedSize
    # swap on the intraday champion.)
    if base_slot is not None:
        excl: frozenset[str] = getattr(type(fresh), "_HASH_EXCLUDE", frozenset())
        base_fields = {f.name for f in dataclasses.fields(cast(Any, base_slot.params))}
        fresh_fields = {f.name for f in dataclasses.fields(fresh)}
        carry = {k: getattr(base_slot.params, k) for k in excl if k in base_fields and k in fresh_fields}
        if carry:
            fresh = dataclasses.replace(fresh, **carry)
    params = _apply_params(kind, ch.impl_name, swept, fresh)
    return Slot(impl=impl, params=params, enabled=True)


def sweep_to_strategy_config(sweep_config: Any, *, base_module: str = BASE_MODULE) -> StrategyConfig:
    """Map a SweepConfig onto the champion base stack → a deployable StrategyConfig.

    Overrides the swept kinds (signal, entry_selection, sizing, regime); every other kind
    (universe, entry_timing, protective_stop, exit_*, diagnostics, …) is the base's, verbatim.
    """
    from build.cloud_package import _load_config  # local import: cloud_package imports engine

    base: StrategyConfig = _load_config(base_module)
    phases: dict[str, Any] = dict(base.phases)  # shallow copy; we replace whole entries

    choices = {c.kind: c for c in sweep_config.choices}

    # --- signal / sizing / protective_stop (single-slot kinds) — #339 adds protective_stop so the
    # STOP LEVEL is sweepable (Kijun floor vs cloud-bottom floor); it's the champion's BINDING exit. ---
    for kind in ("signal", "sizing", "protective_stop"):
        ch = choices.get(kind)
        if ch is None:
            continue
        phases[kind] = _override_slot(kind, ch, _base_slot(base, kind))

    # --- entry_selection (list-kind): PRESERVE guard sub-phases (PreFlightStaleness — the
    # snapshot-staleness tripwire), REPLACE only the ALGORITHM slot with the swept impl. ---
    ech = choices.get("entry_selection")
    if ech is not None:
        base_es = base.phases.get("entry_selection", [])
        base_es = base_es if isinstance(base_es, list) else [base_es]
        guards = [s for s in base_es if s.impl.__module__.rsplit(".", 1)[-1] in ENTRY_GUARDS]
        algos = [s for s in base_es if s.impl.__module__.rsplit(".", 1)[-1] not in ENTRY_GUARDS]
        # fail loud if the base shape changed (>1 algo would be silently dropped → wrong stack)
        if len(algos) != 1:
            raise UnsupportedSweepAxisError(
                f"entry_selection base has {len(algos)} non-guard algo slots (expected exactly 1); "
                f"a base-shape change would silently drop a sub-phase — fail loud."
            )
        phases["entry_selection"] = list(guards) + [_override_slot("entry_selection", ech, algos[0])]

    # --- regime (list-kind): split spy_200ma (SpySma200) from the vix params ---
    rch = choices.get("regime")
    if rch is not None:
        swept = rch.param_dict()
        spy_on = bool(swept.get("spy_200ma", False))
        base_regime = base.phases.get("regime", [])
        base_regime = base_regime if isinstance(base_regime, list) else [base_regime]
        spy_landed = "spy_200ma" not in swept  # nothing to land if the axis isn't swept
        vix_axes = {k for k in swept if k != "spy_200ma"}
        vix_landed = not vix_axes
        new_regime: list[Slot[object]] = []
        for slot in base_regime:
            impl_snake = slot.impl.__module__.rsplit(".", 1)[-1]
            if impl_snake == "spy_200ma":
                new_regime.append(Slot(impl=slot.impl, params=slot.params, enabled=spy_on))
                spy_landed = True
            elif impl_snake == "vix_percentile":
                vix = {REMAP.get(("regime", "vix_percentile"), {}).get(k, k): v
                       for k, v in swept.items() if k != "spy_200ma"}
                # a None threshold (the vix-OFF point) must NOT be written into the float field —
                # keep the base default; enabled=False makes it irrelevant either way.
                if vix.get("vix_percentile_threshold") is None:
                    vix.pop("vix_percentile_threshold", None)
                valid = {f.name for f in dataclasses.fields(cast(Any, slot.params))}
                bad = set(vix) - valid
                if bad:
                    raise UnsupportedSweepAxisError(
                        f"regime.vix_percentile: {sorted(bad)} not fields of {type(slot.params).__name__}"
                    )
                new_regime.append(Slot(impl=slot.impl, params=dataclasses.replace(cast(Any, slot.params), **vix), enabled=True))
                vix_landed = True
            else:
                new_regime.append(slot)
        # fail loud if a swept regime axis never found its target slot (fabricated axis coverage)
        if not spy_landed or not vix_landed:
            missing = ("spy_200ma " if not spy_landed else "") + ("vix_percentile" if not vix_landed else "")
            raise UnsupportedSweepAxisError(
                f"regime swept axis did not land on any base slot: {missing.strip()} — the base "
                f"regime stack lacks the target phase; fail loud (no fabricated axis coverage)."
            )
        phases["regime"] = new_regime

    # --- exit_hard (list-kind, base = [Slot(KijunG3Exits)]): SWAP the exit impl (#339). No choice
    # → base exit verbatim (parity: the champion base keeps KijunG3 → e3b0c44298fc/4c2fc8e40607). ---
    xch = choices.get("exit_hard")
    if xch is not None:
        base_ex = base.phases.get("exit_hard", [])
        base_ex = base_ex if isinstance(base_ex, list) else [base_ex]
        if len(base_ex) != 1:
            raise UnsupportedSweepAxisError(
                f"exit_hard base has {len(base_ex)} slots (expected exactly 1); a base-shape change "
                f"would silently drop/duplicate an exit — fail loud."
            )
        phases["exit_hard"] = [_override_slot("exit_hard", xch, base_ex[0])]

    # --- exit_rotation (NEW kind the base lacks): ADD the rotation slot when a choice provides it
    # (the engine already schedules exit_rotation). No choice → no rotation (base behavior). ---
    roch = choices.get("exit_rotation")
    if roch is not None:
        phases["exit_rotation"] = [_override_slot("exit_rotation", roch, None)]

    # --- exit_target (NEW kind the base lacks, #364 R2 profit-take): ADD when a choice provides it
    # (the engine already schedules exit_target in PHASE_ORDER). No choice → no profit-take (base
    # behavior). Mirrors exit_rotation — without this the swept exit_target choice is SILENTLY
    # DROPPED (the R2 codegen bug: profit_take never landed → cells ran R1-C-only). ---
    tch = choices.get("exit_target")
    if tch is not None:
        phases["exit_target"] = [_override_slot("exit_target", tch, None)]

    return StrategyConfig(
        name=f"sweep-{sweep_config.config_hash}",
        version=base.version,
        phases=phases,
        is_fixture=False,
    )


def build_sweep_dist(sweep_config: Any, *, dist_dir: Path, base_module: str = BASE_MODULE) -> Any:
    """SweepConfig → StrategyConfig → dist (deployable). Returns the BuildResult."""
    from build.cloud_package import build_from_config

    cfg = sweep_to_strategy_config(sweep_config, base_module=base_module)
    return build_from_config(cfg, deployable=True, dist_dir=dist_dir)
