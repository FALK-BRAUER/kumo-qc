"""#340-reserve cell sz050_b070_on: size 0.05 × budget 0.7 × pyrON."""
from strategies.reserve_pyramid_grid import make_config

CONFIG = make_config(position_pct=0.05, budget=0.7, pyramid=True)
LEAN_ENTRY = True
