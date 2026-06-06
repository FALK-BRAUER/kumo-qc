"""#276b entry-sweep gap_threshold=0.04 (S1 + BctIntradayGapVolConfirm gap_threshold=0.04)."""
from __future__ import annotations

from strategies.entry_sweep import make_config

CONFIG = make_config(gap_threshold=0.04)
LEAN_ENTRY = True
