"""#345 rotation screen R1 — gain-floored evict-on-better-candidate (S1 + GainFlooredRotation R1)."""
from __future__ import annotations

from strategies.rotation_screen import make_config

CONFIG = make_config("R1")
LEAN_ENTRY = True
