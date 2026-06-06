"""#scaleout cell so_m15_t33: milestones (0.15, 0.3, 0.5) x trim_frac 0.33 (low = fires in-quarter)."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.15, 0.3, 0.5), trim_frac=0.33)
LEAN_ENTRY = True
