"""#scaleout cell so_m100_t33: milestones (1.0, 2.0) x trim_frac 0.33."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(1.0, 2.0), trim_frac=0.33)
LEAN_ENTRY = True
