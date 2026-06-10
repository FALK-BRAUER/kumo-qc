# Scanner Opportunity Panel #463

This report builds the label-free scanner opportunity surface. It intentionally does not
include future returns, MFE/MAE, PnL, exits, or path labels; those belong to #464.

## Inputs

- George candidates: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/george_scanner_candidates_raw.csv`
- Kumo candidates: `/Users/falk/projects/kumo-lab/data/bluecloudtrading/scanner_compare/falk_scanner_candidates_enriched.csv`
- Kumo top-N threshold: `100`

## Panel

- Opportunities: `313332`
- Date range: `2025-03-25` to `2026-06-05`
- Dates: `321`
- Symbols: `3796`

## Source Summary

| source_flag | opportunities | pct_of_panel | date_count | symbol_count |
| --- | --- | --- | --- | --- |
| kumo_scanner | 310389 | 99.061 | 275 | 3509 |
| kumo_top_n | 25500 | 8.138 | 255 | 1409 |
| kumo_full_universe | 309818 | 98.879 | 255 | 3485 |
| kumo_targeted_only | 571 | 0.182 | 20 | 308 |
| george_scanner_ocr | 501 | 0.16 | 71 | 291 |
| george_scanner_manual | 49 | 0.016 | 5 | 45 |
| george_scanner_positive | 511 | 0.163 | 71 | 294 |
| george_watchlist | 201 | 0.064 | 6 | 164 |
| george_video_mention | 5629 | 1.796 | 200 | 1151 |
| george_scanner_or_watchlist | 712 | 0.227 | 75 | 400 |
| kumo_and_george_any | 3334 | 1.064 | 185 | 614 |
| kumo_and_george_scanner_positive | 322 | 0.103 | 59 | 205 |
| george_any_only_no_kumo | 2943 | 0.939 | 204 | 1039 |
| video_only_context | 5565 | 1.776 | 200 | 1133 |

## Date Sample

| scan_date | opportunities | kumo_scanner | kumo_top_n | george_scanner_positive | george_watchlist | george_video_mention | video_only_context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-03-25 | 32 | 0 | 0 | 0 | 0 | 32 | 32 |
| 2025-04-11 | 31 | 31 | 0 | 0 | 0 | 0 | 0 |
| 2025-04-12 | 34 | 0 | 0 | 0 | 0 | 34 | 34 |
| 2025-04-22 | 20 | 0 | 0 | 0 | 0 | 20 | 20 |
| 2025-05-05 | 1433 | 1433 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-06 | 1437 | 1437 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-07 | 1430 | 1430 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-08 | 1428 | 1427 | 100 | 0 | 0 | 11 | 11 |
| 2025-05-09 | 1422 | 1422 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-12 | 1425 | 1423 | 100 | 0 | 0 | 26 | 26 |
| 2025-05-13 | 1415 | 1413 | 100 | 0 | 0 | 5 | 5 |
| 2025-05-14 | 1416 | 1415 | 100 | 0 | 0 | 12 | 12 |
| 2025-05-15 | 1418 | 1418 | 100 | 0 | 0 | 4 | 4 |
| 2025-05-16 | 1419 | 1419 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-19 | 1432 | 1428 | 100 | 0 | 0 | 18 | 18 |
| 2025-05-20 | 1423 | 1421 | 100 | 0 | 0 | 10 | 10 |
| 2025-05-21 | 1414 | 1414 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-22 | 1415 | 1415 | 100 | 0 | 0 | 4 | 4 |
| 2025-05-23 | 1403 | 1403 | 100 | 0 | 0 | 0 | 0 |
| 2025-05-27 | 1428 | 1428 | 100 | 0 | 0 | 0 | 0 |

## Source Semantics

- `kumo_scanner` means the row came from the Kumo/Falk candidate surface.
- `kumo_top_n` means the full-universe Kumo rank was within the configured top-N threshold.
- `george_scanner_ocr` means OCR/post-image scanner evidence was present.
- `george_scanner_manual` means manual/legacy scanner table evidence was present.
- `george_scanner_positive` is scanner OCR or manual/legacy scanner evidence.
- `george_watchlist` means explicit watchlist/post-text evidence was present.
- `george_video_mention` is context evidence only; video-only rows are not scanner positives.
