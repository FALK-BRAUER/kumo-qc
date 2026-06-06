"""#276b entry-sweep gap_threshold=0.05 (S1 + BctIntradayGapVolConfirm gap_threshold=0.05)."""
from __future__ import annotations

from strategies.entry_sweep import make_config

CONFIG = make_config(gap_threshold=0.05)
LEAN_ENTRY = True
