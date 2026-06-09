# Sector/Industry Breadth Substrate

Issue: #442

Purpose: make the sector/industry breadth feature source reproducible without relying on precomputed
kumo-lab breadth columns or George/OCR evidence.

## Implementation

- Added `phases.shared.sector_breadth`.
- Breadth is computed from the live pre-score candidate denominator, then carried into the BCT>=6
  ranking panel.
- The runtime taxonomy input is `SECURITY_PROFILE_SOURCE`.
- Unmapped names receive zero breadth. They are not grouped into a fake `unknown` sector.
- `security_profiles.py` now supports multiple ETF proxies per ticker via `proxy_etfs`, while keeping
  `proxy_etf` as the first/primary proxy for backward compatibility.

This fits Falk's IBKR ETF watchlist better than a single static sector code. The practical taxonomy can
use a broad sector ETF plus industry/theme ETF proxies, for example `XLK` plus `SOXX/SMH/IGV/SKYY/CIBR`,
or `XLE` plus `OIH/XOP`.

## Leaderboard

Command:

```bash
PYTHONPATH=src:. /Users/falk/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m sweeps.archive.george_feature_source_ablation --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse --year 2026 --output-dir sweeps/reports/scanner_sector_breadth_substrate_442
```

Result on the 306 covered George labels:

| Cell | Gate | hits@5 | hits@10 | hits@20 | hits@50 | hits@100 | precision@10 | median George rank |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw QC-safe | clean_top2000 | 52 | 88 | 133 | 183 | 204 | 19.13% | 15.0 |
| raw + sector/industry breadth | clean_top2000 | 64 | 101 | 139 | 189 | 208 | 21.96% | 13.0 |
| full research reference | all rows | 69 | 107 | 143 | 195 | 231 | 23.26% | 20.0 |

## Read

The breadth feature source is now reproducible and cloud-handoff-safe as a feature definition, but the
ranker is still not promotable. The best deployable breadth-only clean_top2000 cell is `101/306`
recall@10, below the `117/306` promotion target.

Next useful work:

- build the actual `SECURITY_PROFILE_SOURCE` CSV from Falk's IBKR ETF/proxy taxonomy;
- add ETF proxy strength features on top of breadth;
- make denominator-relative ranks cloud-reproducible over the same live candidate panel.
