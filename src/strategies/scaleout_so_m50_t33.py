"""#scaleout cell so_m50_t33: milestones (0.5, 1.0, 1.5) x trim_frac 0.33."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.5, 1.0, 1.5), trim_frac=0.33)
LEAN_ENTRY = True
