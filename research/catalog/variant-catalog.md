# Variant Catalog — the existing evidence base

The ~40 prototyped experiments already in our GH/branch history, mapped to phase kind — the real cases the **Variant Strategy** boundary (see [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) §9, D1–D3) must absorb. Folded from ADR-0001 §6 (the standalone ADR was dissolved into the living charter by #222).

| Phase kind | Existing variants (→ become sibling impls) | Tunable knobs (→ `.Params` axes) |
|---|---|---|
| `entry_timing` | doji-timing (c1), resistance-proximity (c2), pullback-to-tenkan / T-bounce (methodology §4), pre-breakout-zone (rs148) | zone %, body/wick thresholds, lookback |
| `stops` / `trail` | kijun-ATR-trail (e16), polarity-flip-trail (rs151), fixed-% | atr_period, atr_mult, kijun lookback |
| `adds` (pyramid) | staged-risk Pa–Pe (#172/#178), tiered step-up (#168, X2) | lots, risk-ceiling, step size |
| `sizing` | $-risk (#158-160), score-tier (#167/X1), vol-adjusted (#165/X5) | risk %, tier thresholds, vol lookback |
| `regime` | vix-2tier (e121), circuit-breaker (#32, ±vix), credit-risk-off (#29), market-breadth >50%>200MA (#157/V18), sector-RS (#156/V17) | vix threshold, DD %, breadth %, RS window |
| `exit` | weekly-cloud-breach, kijun-trail, partial-exit ladder (#179, X-ladder) | trim fractions, breach confirm |
| `reentry` | drawdown-reset (#169/X4) | reset DD, cooldown |
| `signal` | bct_score_full (8-cond), + multi-timeframe weekly cloud (#164/X3), composite ranking (#166/X7) | min_score, parabolic threshold |

## Retrofit rule

Most of these were prototyped on the v1 oracle with **forbidden mechanics** (fixed slots, max-positions, day-holds). Per the charter's retrofit rule: **take the intent, drop the mechanic** — re-express each as a principled phase impl (exposure via `gross_exposure_cap`, exits via structure, sizing via $-risk). A retrofit expressible only as a fixed slot / max-hold is **rejected, not ported**.
