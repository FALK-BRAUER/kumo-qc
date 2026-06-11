# Scan-Time Scanner Ranking Optimization

## Goal

Build issue #492: optimize daily scanner ranking using only scan-time features and the #482
optimal/bad trade labels.

## Scope

- Kumo-first: use rows where `kumo_signal_seen` is true.
- Labels come from `sweeps/reports/scanner_trade_universe_482/scanner_trade_universe.csv.gz`:
  `optimal` is positive, `bad` is negative, `watch` is neutral/downweighted.
- Features must be scan-time safe: Kumo rank/score, gap, source metadata, sector metadata
  availability, and in-day ranks/percentiles of those scan-time fields.
- Compare learned scores against current Kumo rank/score and previous #467 model scores.

## Files

- `scripts/train_scan_time_scanner_ranker.py`
  - Read #482 trade universe.
  - Build scan-time features.
  - Train expanding-window logistic/linear rank scores.
  - Emit OOF predictions, top-k metrics, monthly stability, feature diagnostics, and report.
- `tests/scripts/test_train_scan_time_scanner_ranker.py`
  - Cover feature leakage guard, walk-forward splits, top-k metrics, and label preparation.
- `sweeps/reports/scan_time_scanner_ranker_492/README.md`
  - Generated artifact directory documentation.

## Verification

- `python3 -m pytest tests/scripts/test_train_scan_time_scanner_ranker.py`
- `python3 scripts/train_scan_time_scanner_ranker.py`

## Non-goals

- No intraday features or entry/exit policy.
- No fair George model; that depends on #489/#483.
