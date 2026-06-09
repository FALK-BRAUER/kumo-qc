# scanner_sector_breadth_substrate_442

Feature-source ablation rerun for #442 after moving sector/industry breadth to a live-denominator
substrate. Contains CSV summaries from `george_feature_source_ablation`.

Best deployable breadth-only clean_top2000 cell: `64/101/139/189/208` hits at K
`5/10/20/50/100`. This reproduces the prior `101/306` recall@10 lift but remains below promotion.
