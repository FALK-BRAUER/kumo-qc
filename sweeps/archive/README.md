# sweeps/archive/

The durable results-archive snapshotter (#276b, `docs/notes/results-archive-design.md`). The ONE
channel that survives the cloud BT purge — without it every run's trades + decision context evaporate.

- `snapshot.py` — `persist_run(...)`: writes `results/archive/<config_hash>/<backtest_id>/` with
  `result.json` (full config + provenance + ALL QC statistics + 3-state status) and
  `trades.jsonl.gz` (one closed trade per line, decision context parsed from the entry-order TAG).
  FAIL-LOUD: raises on fetch error, schema-drift, bad status, or empty-trades-when-orders>0. The
  `/orders/read` fetch and the write-destination are INJECTED (tests mock them — ZERO real QC/LEAN).
- `candidates.py` / `george_coverage_audit.py` / `george_topk_audit.py` /
  `george_learned_ranker.py` / `massive_qc_bridge.py` / `first_hour_confirmation.py` /
  `george_sector_context_audit.py` — local candidate-population, George-label coverage, top-K,
  date-grouped learned-ranker, Massive-backed substrate bridge, first-hour confirmation, and
  sector/industry-context helpers. They are offline sweep/audit tools, not runtime phases.
  The harnesses take explicit
  label/denominator/coarse paths and fail loudly when pointed at an empty worktree data cache.

Massive bridge broad-universe reproduction command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.massive_qc_bridge \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --top-n 3000 \
  --no-min-score
```

Massive bridge score-6 candidate-lane command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.massive_qc_bridge \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --top-n 3000 \
  --min-score 6
```

Score-6 first-hour label-smoke command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.first_hour_confirmation \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --minute-dir /Users/falk/projects/kumo-qc/data/equity/usa/minute \
  --year 2026 \
  --top-n 3000 \
  --min-score 6 \
  --labels-only
```

Score-6 first-hour full-pool precision command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.first_hour_confirmation \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --minute-dir /Users/falk/projects/kumo-qc/data/equity/usa/minute \
  --year 2026 \
  --top-n 3000 \
  --min-score 6
```

The full-pool run reproduced 47,493 score-6 candidate rows and 281/306 George labels in-panel.
First-hour confirmation is an enrichment layer: `fh_confirm_basic` reached 2.110% label precision
(3.57x lift) and `fh_confirm_breakout` reached 2.477% precision (4.19x lift), but neither is a
standalone top-list selector.

Sector/industry context command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_sector_context_audit \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --top-n 3000 \
  --min-score 6
```

The profiled run reproduced the same 47,493 score-6 candidate rows and 281/306 labels. Of those
in-panel labels, 187 had sector/industry profile coverage. Sector top7 recall was 159/187
(85.03%), industry-in-sector top5 recall was 142/187 (75.94%), and stock-in-industry top10 recall
was 176/187 (94.12%). Simple hierarchy rank variants are still weak for top10: the best plain
sector-context score hit 13/306 recall@10.

Score-6 top-K reproduction command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_topk_audit \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026
```

Date-grouped learned-ranker command:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026
```

Date-grouped learned-ranker with sector/industry context:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --use-sector-context
```

The controlled profiled-denominator comparison moved `clean_top2000` OOF recall@10 from 59/306
without context to 65/306 with sector/industry context. That is useful feature lift, but still not
enough for a runtime top-list promotion.

Date-grouped pairwise ranker with sector/industry context:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --model-type pairwise \
  --use-sector-context \
  --learning-rate 0.08 \
  --pairwise-negatives-per-positive 80
```

The best current dependency-free learned result is
`learned_oof_pairwise_sector_context_clean_top2000`: 46/306 recall@5, 72/306 recall@10,
109/306 recall@20, and 160/306 recall@50. It is an offline selector benchmark, not runtime logic.

Pairwise ranker with live-panel denominator rank features:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --model-type pairwise \
  --use-sector-context \
  --use-denominator-ranks \
  --learning-rate 0.08 \
  --pairwise-negatives-per-positive 80
```

The denominator-rank features are recomputed per date over the live score-6 candidate panel; they
do not read George rank, OCR rows, transcripts, or lab model scores.
This moved the pairwise+sector clean-top2000 benchmark from 72/306 to 87/306 recall@10 and improved
median George rank from 19.0 to 14.5. Keep it research-only until the runtime handoff gate proves a
matching live denominator.

Pairwise ranker with live-panel denominator ranks plus profiled sector/industry breadth:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --year 2026 \
  --model-type pairwise \
  --use-sector-context \
  --use-denominator-ranks \
  --use-sector-breadth \
  --learning-rate 0.08 \
  --pairwise-negatives-per-positive 80
```

Profiled breadth moved the clean-top2000 benchmark only modestly, from 87/306 to 88/306 recall@10,
but the broader score7-or-clean6 gate improved from 77/306 to 82/306 recall@10. Treat it as useful
research input for the next grouped ranker, not a standalone promotion.

Pairwise ranker with first-hour features:

```bash
PYTHONPATH=src:. .venv/bin/python -m sweeps.archive.george_learned_ranker \
  --labels-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_oof_stage1_scores.csv \
  --denominator-csv /Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_ranking_denominator_profiled.csv \
  --coarse-dir /Users/falk/projects/kumo-qc/data/equity/usa/fundamental/coarse \
  --minute-dir /Users/falk/projects/kumo-qc/data/equity/usa/minute \
  --year 2026 \
  --model-type pairwise \
  --use-sector-context \
  --use-first-hour \
  --learning-rate 0.08 \
  --pairwise-negatives-per-positive 80
```

First-hour features did not improve the current selector: pairwise+sector is 72/306 recall@10,
pairwise+first-hour is 70/306, and pairwise+sector+first-hour is 66/306. Keep first-hour as a
separate confirmation/reducer layer until minute coverage and validation improve.

Goes here: the snapshot writer + its schemas. Does NOT go here: the `/orders/read` prod wiring (lives
in `adapters/qc_cloud_prod.py` / the local adapter — they inject the fetch), or any engine import
(the config is passed pre-serialized to keep this module phase-agnostic).
