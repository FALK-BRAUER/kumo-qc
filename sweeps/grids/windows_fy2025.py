"""The #323 window panel — FY2025 bi-monthly + FY2024 OOS holdout.

The #323 sweep evaluates EVERY config across these windows; the windows-AND-FY consistency is
the robustness gate (a config that wins on one window but breaks elsewhere is fragile by
construction). Defined HERE (a sweep-design artifact, owned by this grid) rather than mutating
the shared `sweeps/windows.py` SIX_WINDOWS calendar panel (which the #214 driver scaffold owns)
— so the two evolve independently and this refinement does not collide with that scaffold.

Roles (per design A.4):
  - PANEL  : the 6 FY2025 bi-monthly windows — the headline robustness distribution.
  - HOLDOUT: FY2024 OOS — UNTOUCHED during search, the final out-of-sample validation; the
    concentration guard (gates.WindowReturns.is_oos) requires it positive.

W5 (sep-oct) is the window the order-density analysis flagged as the "winner" a fragile config
leans on — the concentration guard rejects any config whose positive blend is W5-carried.
"""
from __future__ import annotations

from typing import Literal

from sweeps.types import Window

# The 6 FY2025 bi-monthly panel windows (the headline robustness distribution).
W1_JAN_FEB = Window(name="w1_2025_jan_feb", start="2025-01-01", end="2025-02-28")
W2_MAR_APR = Window(name="w2_2025_mar_apr", start="2025-03-01", end="2025-04-30")
W3_MAY_JUN = Window(name="w3_2025_may_jun", start="2025-05-01", end="2025-06-30")
W4_JUL_AUG = Window(name="w4_2025_jul_aug", start="2025-07-01", end="2025-08-31")
W5_SEP_OCT = Window(name="w5_2025_sep_oct", start="2025-09-01", end="2025-10-31")
W6_NOV_DEC = Window(name="w6_2025_nov_dec", start="2025-11-01", end="2025-12-31")

FY2025_PANEL: tuple[Window, ...] = (
    W1_JAN_FEB,
    W2_MAR_APR,
    W3_MAY_JUN,
    W4_JUL_AUG,
    W5_SEP_OCT,
    W6_NOV_DEC,
)

# FY2024 out-of-sample holdout — untouched during search, final validation only.
FY2024_OOS = Window(name="fy2024_oos", start="2024-01-01", end="2024-12-31")

WindowRole = Literal["panel", "holdout"]

WINDOW_ROLES: dict[str, WindowRole] = {
    **{w.name: "panel" for w in FY2025_PANEL},
    FY2024_OOS.name: "holdout",
}
"""Role of each #323 window: the 6 FY2025 bi-monthly are `panel`; FY2024 is the `holdout`."""


def sweep_windows(*, include_holdout: bool = False) -> tuple[Window, ...]:
    """The windows a #323 sweep ROUND runs.

    `include_holdout=False` (default) returns the 6 FY2025 panel windows ONLY — the holdout is
    NEVER read into the selector during a search round (the design's holdout-isolation rule).
    `include_holdout=True` (final-validation phase only) appends FY2024 OOS.
    """
    if include_holdout:
        return (*FY2025_PANEL, FY2024_OOS)
    return FY2025_PANEL
