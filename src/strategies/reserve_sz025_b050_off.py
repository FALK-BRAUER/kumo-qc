"""#340-reserve cell sz025_b050_off: size 0.025 × budget 0.5 × pyrOFF (pyramid-isolation twin)."""
from strategies.reserve_pyramid_grid import make_config

CONFIG = make_config(position_pct=0.025, budget=0.5, pyramid=False)
LEAN_ENTRY = True
