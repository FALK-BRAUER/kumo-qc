"""kumo-qc strategy configs.

CHAMPION = the SINGLE production champion (the config the dist is built from + deployed via live_bct).
Build/deploy tooling MUST target CHAMPION (not a hardcoded module name) so 'which config is THE
champion' can't drift (the build_champion_asis-targets-the-retired-fixture bug, #386 trace).

Layout: the champion lives at strategies/<champion>.py; A/B/C scenario blueprints in
strategies/blueprints/; retired fixtures in strategies/archive/ (archiving pending — the dead siblings
champion_asis/champion_entry/_sized still sit at top level; they move once their ~10 test imports are
repointed).
"""
from __future__ import annotations

CHAMPION: str = "strategies.champion_intraday_gapvol"


def assert_champion() -> str:
    """Single-champion guard: load CHAMPION, assert it is a real (is_fixture=False) deployable config,
    return its module path. Raises if CHAMPION is missing or a fixture. The pin that stops build/deploy
    from drifting off the designated champion."""
    import importlib

    mod = importlib.import_module(CHAMPION)
    cfg = getattr(mod, "CONFIG", None)
    if cfg is None:
        raise ValueError(f"CHAMPION {CHAMPION} has no CONFIG")
    if getattr(cfg, "is_fixture", False):
        raise ValueError(f"CHAMPION {CHAMPION} is_fixture=True — a fixture cannot be the champion (#272/#386)")
    return CHAMPION
