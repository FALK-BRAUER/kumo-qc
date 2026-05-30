# phases/universe/liquid_substrate

The universe phase: full liquid substrate via tradeability **floors only**.

- **What it holds:** `liquid_substrate.py` (consumer phase) + its test mirror.
- **Model:** every name clearing `min_price` AND trailing-`adv_window` mean dollar
  volume `>= min_avg_dollar_volume` that day is in. No top-N, no rank, no count cap.
  Variable-size daily set. The floor gates *tradeability*; `bct_score_full` selects.
- **What goes here:** changes to floor consumption / fail-loud semantics only. Selection
  logic does NOT go here. Narrow the universe only by raising a floor, never a count.
