"""#340-C-redo matrix cell: per-entry size=0.033 pyramid=OFF (S1 + sizing-down)."""
from __future__ import annotations

from strategies.sizing_pyramid_matrix import make_config

CONFIG = make_config(position_pct=0.033, pyramid=False)
LEAN_ENTRY = True
