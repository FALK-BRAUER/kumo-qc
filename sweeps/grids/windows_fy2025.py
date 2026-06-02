"""DEPRECATED PANEL SHIM (#338 workstream 3) — re-exports the ONE canonical panel.

The old #323 bi-monthly FY2025 panel (+ FY2024 OOS holdout) defined here was the WRONG panel the
grids actually ran (Falk 2026-06-03). The single canonical validation panel is now
`sweeps.windows.SIX_WINDOWS` (the 6 recent quarterly windows, 2025Q1–2026Q1 + Feb-Apr 2026). This
module now RE-EXPORTS that single source so existing grid imports keep working but there is literally
ONE panel everywhere (sweeps, gates, leaderboard). Do NOT add window definitions here — edit
`sweeps/windows.py::SIX_WINDOWS`.

Migration note: the old bi-monthly champion-panel / dvrank results were on the wrong panel and are
historical. The FY2024-OOS holdout concept is retired with this panel (the 6 quarterly ARE the
distribution; any future holdout is a separate Falk decision) — `FY2024_OOS` is kept only as a
deprecated alias for import-compat and is NOT part of the canonical panel or roles.
"""
from __future__ import annotations

from typing import Literal

from sweeps.types import Window
from sweeps.windows import SIX_WINDOWS

# THE single canonical panel (re-export). Was the 6 FY2025 bi-monthly; now the 6 quarterly SIX_WINDOWS.
FY2025_PANEL: tuple[Window, ...] = SIX_WINDOWS

# DEPRECATED: the FY2024 OOS holdout (retired with the new panel; kept for import-compat only).
# FY2024 is NOT locally runnable (560d warmup → 2022 data gap) and is not part of the canonical panel.
FY2024_OOS = Window(name="fy2024_oos", start="2024-01-01", end="2024-12-31")

WindowRole = Literal["panel", "holdout"]

# All canonical windows are panel; no separate holdout in the new scheme.
WINDOW_ROLES: dict[str, WindowRole] = {w.name: "panel" for w in SIX_WINDOWS}


def sweep_windows(*, include_holdout: bool = False) -> tuple[Window, ...]:
    """The ONE canonical panel (= sweeps.windows.SIX_WINDOWS, the 6 quarterly windows). The
    `include_holdout` arg is retained for back-compat but is now a NO-OP — the canonical panel has no
    separate OOS holdout (the FY2024 holdout is retired; a future holdout is a separate Falk decision).
    """
    return SIX_WINDOWS
