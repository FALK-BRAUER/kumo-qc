"""#scaleout cell so_m20_t50: milestones (0.2, 0.4) x trim_frac 0.5 (low = fires in-quarter)."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.2, 0.4), trim_frac=0.5)
LEAN_ENTRY = True
