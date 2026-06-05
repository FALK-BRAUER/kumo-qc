"""#340-C screen V2 — position-fraction add (Pe-posfrac): 0.25 × position_value, floored ≥1 share."""
from __future__ import annotations

from strategies.pyramid_screen import make_config

CONFIG = make_config("Pe-posfrac")
LEAN_ENTRY = True
