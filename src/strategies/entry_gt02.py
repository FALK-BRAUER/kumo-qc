"""#276b entry-sweep gap_threshold=0.02 (S1 + BctIntradayGapVolConfirm gap_threshold=0.02)."""
from __future__ import annotations

from strategies.entry_sweep import make_config

CONFIG = make_config(gap_threshold=0.02)
LEAN_ENTRY = True
