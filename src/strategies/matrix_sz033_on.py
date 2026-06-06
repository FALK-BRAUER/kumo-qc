"""#340-C-redo matrix cell: per-entry size=0.033 pyramid=ON (S1 + sizing-down + pyramid)."""
from __future__ import annotations

from strategies.sizing_pyramid_matrix import make_config

CONFIG = make_config(position_pct=0.033, pyramid=True)
LEAN_ENTRY = True
