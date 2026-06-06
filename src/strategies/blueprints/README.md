# strategies/blueprints/

The #386 A/B/C scenario configs — the modularization proof. Each `scenario_*.py` is a
`{slot: module(params)}` StrategyConfig composing #254 catalog modules across the two-clock pipeline.

What goes here: scenario/blueprint configs that compose catalog modules (A/B/C, future variants).
What doesn't: the production champion (stays at strategies/champion_intraday_gapvol.py), retired
fixtures (→ strategies/archive/), phase implementations (→ src/phases/).

Scenario variants may reuse the same modules with different params when the proof needs multiple
intraday runs without changing the engine.

The `scenario_exit_*` variants are #398 George-style exit-management proofs. They reuse the scenario-C
entry stack and vary only the trail/exit modules.
