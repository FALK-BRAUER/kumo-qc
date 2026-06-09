# position_path_tracker
Tracks per-position path metrics before exit phases run.
Use this to provide the intraday `position_path` downstream contract: shared MFE/MAE, peak/trough, giveback, bars-held, and session state for George-style exits.
Do not put exit decisions or broker-order intents here.
