"""#276b entry-sweep vol_mult=1.25 tol=0.1 (gap_threshold=0.03=optimum)."""
from __future__ import annotations

from strategies.entry_sweep import make_config

CONFIG = make_config(gap_threshold=0.03, vol_mult=1.25, gap_up_tolerance_pct=0.1)
LEAN_ENTRY = True
