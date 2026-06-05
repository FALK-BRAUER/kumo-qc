"""#340-C screen V3 — conviction-weighted add (Pe-convstack): 0.25 × position_value ×
clamp(unrealized%/10, 0.5, 3.0), floored ≥1 share — biggest adds to the strongest winners."""
from __future__ import annotations

from strategies.pyramid_screen import make_config

CONFIG = make_config("Pe-convstack")
LEAN_ENTRY = True
