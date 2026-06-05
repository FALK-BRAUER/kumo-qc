"""#340-reserve cell sz025_b050_on: size 0.025 × budget 0.5 × pyrON."""
from strategies.reserve_pyramid_grid import make_config

CONFIG = make_config(position_pct=0.025, budget=0.5, pyramid=True)
LEAN_ENTRY = True
