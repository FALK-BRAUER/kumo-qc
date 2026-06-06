"""#scaleout cell so_m25_t25: milestones (0.25, 0.5, 1.0) x trim_frac 0.25."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.25, 0.5, 1.0), trim_frac=0.25)
LEAN_ENTRY = True
