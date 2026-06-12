# #479 Dynamic Scanner Realized Sweep Analysis

Window: FY2025 local LEAN, `workers=3`.

Pack: `dynamic_realized_scanner`, 12/12 OK.

Runtime contract: scanner threshold rows used `scanner_ranker_top_x=0` with score thresholds
`-0.25`, `-0.20`, and `-0.16`. No fixed Top-X slot and no fixed day/session exit was added.

## Leaderboard Read

| variant | return | DD | Sharpe | orders | realized | unrealized | closed win | closed trades |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| target08_let_run_dynamic_score_medium | 11.113% | 15.100% | 0.710 | 161 | 16281.73 | $-5,019.06 | 92.0% | 75 |
| target04_fast_take_dynamic_off | 10.736% | 17.800% | 0.555 | 277 | 24951.92 | $-13,962.47 | 96.9% | 127 |
| giveback_no_bull_dynamic_score_loose | 10.720% | 17.400% | 0.563 | 309 | 24786.99 | $-13,780.74 | 90.9% | 143 |
| target08_let_run_dynamic_off | 10.687% | 17.300% | 0.557 | 249 | 24379.87 | $-13,466.60 | 93.8% | 113 |
| giveback_no_bull_dynamic_off | 10.635% | 17.400% | 0.560 | 335 | 23957.43 | $-13,010.36 | 89.7% | 156 |
| target04_fast_take_dynamic_score_strict | 10.061% | 7.600% | 1.020 | 118 | 11285.10 | $-1,111.86 | 98.2% | 56 |

## Per-Base Deltas

Against `giveback_no_bull_dynamic_off`:

| scanner mode | return delta | DD delta | realized delta | unrealized delta | order delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| score_loose | +0.085 | +0.000 | +829.56 | -770.38 | -26 |
| score_medium | -3.316 | -9.500 | -12379.34 | +8883.71 | -196 |
| score_strict | -9.052 | -11.400 | -18731.96 | +9443.70 | -254 |

Against `target04_fast_take_dynamic_off`:

| scanner mode | return delta | DD delta | realized delta | unrealized delta | order delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| score_loose | -0.951 | -0.200 | -946.68 | -6.12 | -2 |
| score_medium | -1.804 | -6.700 | -10472.43 | +8567.16 | -115 |
| score_strict | -0.675 | -10.200 | -13666.82 | +12850.61 | -159 |

Against `target08_let_run_dynamic_off`:

| scanner mode | return delta | DD delta | realized delta | unrealized delta | order delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| score_loose | -1.036 | +0.300 | -812.15 | -209.95 | +14 |
| score_medium | +0.426 | -2.200 | -8098.14 | +8447.54 | -88 |
| score_strict | -4.950 | -10.500 | -16125.19 | +11025.11 | -169 |

## Interpretation

`target08_let_run_dynamic_score_medium` is the best overall row in this pack: it improves total
return by 0.426 points and DD by 2.2 points versus its scanner-off control, with 88 fewer orders.
The mechanism is not higher realized PnL. It reduces negative unrealized drag by about 8447.54
while giving up about 8098.14 of realized net. That makes it a better total-return/DD row, but not
yet a clean realized-PnL improvement.

`target04_fast_take_dynamic_score_strict` is the best drawdown-quality row: 10.061% return, 7.6%
DD, Sharpe 1.020, and only $-1,111.86 unrealized. It sacrifices 13666.82 realized net versus its
off control, so it is a risk-control candidate, not a realized-PnL promotion.

`giveback_no_bull_dynamic_score_loose` barely improves return and realized net versus off, but it
does not improve DD and worsens open drag. It is not a strong promotion candidate.

## Operational Read

The dynamic no-Top-X score-threshold mode is much slower than the previous fixed Top-X sweeps.
Even with complete weekly cache, the broad/off/loose rows keep large daily candidate panels and pay
the daily active-universe traversal cost. The FY pack completed cleanly with `workers=3`, but this
mode is expensive enough that larger sweeps should either:

- use fewer broad controls per pack,
- add a documented wide safety cap for compute only, or
- materialize daily ranker outputs into a cache before LEAN replay.

## Decision

Do not promote this as a production champion. The best next candidate for follow-up is
`target08_let_run_dynamic_score_medium`, because it improves total return and DD without static
Top-X or static day/session logic. The follow-up should analyze its trade history and test whether
the lost realized PnL can be recovered through scanner-aware exits or revalidation rather than
tighter static thresholds.
