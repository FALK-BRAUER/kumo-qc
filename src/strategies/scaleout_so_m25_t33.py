"""#scaleout cell so_m25_t33: milestones (0.25, 0.5, 1.0) x trim_frac 0.33."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.25, 0.5, 1.0), trim_frac=0.33)
LEAN_ENTRY = True
