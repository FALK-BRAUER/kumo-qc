# bct-history

Archive of **Blue Cloud Trading (BCT)** members posts — George's actual trades + the daily Buy
Scanner results. This is the methodology **source-of-truth / validation ground-truth**: kumo-qc
replicates the BCT 8-condition Ichimoku scan, so George's scanner output + live trades are what we
measure recall/precision against (CLAUDE.md: 74.2% recall / 100% precision vs scanner).

**What goes here:** one `YYYY-MM-DD.md` per BCT post — trades added/closed, market overview, and the
Buy Scanner results table (symbol + Pullback-Tenkan / weekly-Ichimoku flags + %change). Transcribed
from the members posts/screenshots.

**What does not:** strategy code (that's `algorithm/` + `src/phases/`), backtest results
(`bt-results.csv`), or analysis (`docs/notes/`). This dir is raw BCT reference data only.
