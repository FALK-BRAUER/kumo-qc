# e40c-qqq-regime — Trade Analysis (Track B)

Source: verified local FY2025 BT (raw data + dollar-volume tiebreak), worktree kumo-qc-e40c, backtests/2026-05-29_16-44-10. Sharpe 0.778 / +23.6% / 9.1% DD / 143 orders / 67 closed round-trips + 9 open EoY.

## Edge profile
| | Count | Avg P&L | Avg hold | Total |
|--|--|--|--|--|
| Winners | 31 | +$1,016 | **52.9 days** | +$31,491 |
| Losers | 36 | -$464 | **15.6 days** | -$16,693 |
Net +$14,798. Win rate 46% but **payoff ratio 2.2:1** → profitable trend-following.

**Core mechanic:** winners are held ~53 days (trend left to run); losers cut at ~16 days (Kijun stop). Classic "cut losers, let winners run." The QQQ>50MA regime gate (vs e40b SPY200 which FAILED) sits out weak-Nasdaq stretches → lowest DD (9.1%) of all variants.

## Winners (amplify)
HOOD +6035 (Jun→Nov, ~5mo), APP +4365, HOOD +2441, TSLA +2361, GOOG +1867, MSFT +1673.
Characteristic: large-cap/liquid momentum + tech, multi-month holds, ride the trend.

## Losers (avoidable?)
PLTR -1321 (Jan 6→8, 2 days), VST -1227, IBM -1205, NOW -1031 (3 days), COIN -941, MDT -856.
Characteristic: **fast whipsaw stop-outs** (days, not weeks) on **high-volatility names** (PLTR/VST/COIN/NOW). Entered → immediately reversed → Kijun-stopped at a loss. -$16.7k drag is concentrated here.

## Proposed follow-up experiments (screen on W1-W6 windows first, FY2025 only if positive)
1. **Entry whipsaw filter** — require N-day confirmation above Kijun before entry, OR skip if recent ATR/realized-vol > threshold. Targets the 16-day fast losers. (relates to idea bank)
2. **Max-ATR / vol-cap on entry** — block high-vol names (PLTR/COIN/VST class) that produce fast whipsaw losses. Cut the loss drag.
3. **Trend-aware exit (let winners run longer)** — winners avg 53d; test a looser/trailing exit (e.g. weekly-Kijun or chandelier) vs daily Kijun stop, to extend the +$1016 winners.
4. **Risk-based sizing (E89, GH #118)** — $X risk/trade sizing instead of flat 10%; size winners up / cap whipsaw losers. (Track D)
5. **Portfolio 4% trailing-DD circuit breaker (GH #32, OPEN)** — halt new entries when portfolio -4% from peak; may cut whipsaw clusters in drawdowns.

## Idea bank (GitHub, leaned on)
- #118 E89 unlimited slots + $200 risk sizing + heat cap (CLOSED — risk-sizing model exists)
- #76 Risk-based sizing BT vs flat-10% (CLOSED)
- #75 [ARCH] Remove fixed slots — risk-based sizing + heat cap (CLOSED)
- #50 dynamic MAX_POSITIONS by VIX+IWM regime (CLOSED)
- #32 portfolio 4% trailing-DD circuit breaker (OPEN)
- #71 top-100 QC community strategies for BCT-compatible ideas (CLOSED)
