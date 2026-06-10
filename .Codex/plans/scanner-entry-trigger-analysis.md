# Scanner Entry Trigger Analysis

## Goal

Produce the first issue #465 entry research slice from the merged #464 path labels.

## Scope In This Slice

- Compare leakage-safe next-open gates using only source/rank/score and next-open gap fields.
- Generate gate summaries, rank/gap bucket summaries, and best/worst examples.
- Recommend a first simple LEAN sweep candidate if a gate is useful.

## Explicitly Out Of Scope

- Alternate first-hour confirmation entry prices.
- Breakout-above-prior-high entry replay.
- Pullback-to-cloud/VWAP entry replay.

Those require another raw intraday replay pass that changes entry time and entry price. This
slice should not pretend those were measured.
