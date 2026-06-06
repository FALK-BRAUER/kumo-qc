"""#276b entry-sweep gap_threshold=0.03 (S1 + BctIntradayGapVolConfirm gap_threshold=0.03)."""
from __future__ import annotations

from strategies.entry_sweep import make_config

CONFIG = make_config(gap_threshold=0.03)
LEAN_ENTRY = True
