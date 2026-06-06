# strategies/blueprints/

The #386 A/B/C scenario configs — the modularization proof. Each `scenario_*.py` is a
`{slot: module(params)}` StrategyConfig composing #254 catalog modules across the two-clock pipeline.

What goes here: scenario/blueprint configs that compose catalog modules (A/B/C, future variants).
What doesn't: the production champion (stays at strategies/champion_intraday_gapvol.py), retired
fixtures (→ strategies/archive/), phase implementations (→ src/phases/).
