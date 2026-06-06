"""#scaleout cell so_m05_t33: milestones (0.05, 0.1, 0.2) x trim_frac 0.33 (low = fires in-quarter)."""
from strategies.scaleout_screen import make_config

CONFIG = make_config(milestones=(0.05, 0.1, 0.2), trim_frac=0.33)
LEAN_ENTRY = True
