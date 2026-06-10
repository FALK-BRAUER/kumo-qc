from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import build_scanner_opportunity_panel as M


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_george_video_only_is_context_not_scanner_positive(tmp_path: Path) -> None:
    path = tmp_path / "george.csv"
    _write_csv(
        path,
        [
            {
                "date": "2025-01-02",
                "symbol": "aaa",
                "george_candidate_source": "george_video_markdown_table",
                "george_source_kind": "video_markdown",
                "george_source_confidence_observed": "medium_high_video_md_table",
                "george_rank": "",
                "george_watchlist_rank": "",
                "george_watchlist_type": "video_markdown_table",
                "post_id": "",
                "source_path": "video.md",
                "source_detail": "table row",
                "video_id": "vid-1",
                "george_source_role": "video_discussed",
                "source_role": "video_discussed",
                "george_source_confidence": "medium",
                "in_george_scanner": "True",
                "ocr_status": "",
            }
        ],
    )

    normalized = M.normalize_george_candidates(path)

    assert bool(normalized.loc[0, "george_video_mention"]) is True
    assert bool(normalized.loc[0, "george_scanner_positive"]) is False
    assert bool(normalized.loc[0, "george_watchlist"]) is False


def test_kumo_top_n_requires_full_universe_rank(tmp_path: Path) -> None:
    path = tmp_path / "kumo.csv"
    _write_csv(
        path,
        [
            {
                "date": "2025-01-02",
                "symbol": "AAA",
                "falk_score": 8.5,
                "falk_rank_by_score": 5,
                "falk_scanner_source_scope": "phase2_full_universe",
                "falk_scanner_source_basis": "raw_massive_parquet",
                "falk_scanner_price_adjustment": "raw_unadjusted",
                "falk_scanner_source_path": "phase2.csv.gz",
                "falk_scanner_full_rank_available": "True",
                "falk_scanner_targeted_only": "False",
                "in_falk_kumo_scanner": "True",
                "in_falk_kumo_scanner_full_universe": "True",
                "source_role": "falk_phase2_candidate",
            },
            {
                "date": "2025-01-02",
                "symbol": "BBB",
                "falk_score": 9.5,
                "falk_rank_by_score": 3,
                "falk_scanner_source_scope": "targeted_raw_gap_score",
                "falk_scanner_source_basis": "raw_massive_parquet",
                "falk_scanner_price_adjustment": "raw_unadjusted",
                "falk_scanner_source_path": "targeted.csv",
                "falk_scanner_full_rank_available": "False",
                "falk_scanner_targeted_only": "True",
                "in_falk_kumo_scanner": "True",
                "in_falk_kumo_scanner_full_universe": "False",
                "source_role": "falk_phase2_candidate",
            },
        ],
    )

    normalized = M.normalize_kumo_candidates(path, kumo_top_n=10).set_index("symbol")

    assert bool(normalized.loc["AAA", "kumo_top_n"]) is True
    assert bool(normalized.loc["BBB", "kumo_top_n"]) is False
    assert bool(normalized.loc["BBB", "kumo_targeted_only"]) is True


def test_panel_dedupes_date_symbol_and_merges_provenance(tmp_path: Path) -> None:
    kumo_path = tmp_path / "kumo.csv"
    george_path = tmp_path / "george.csv"
    _write_csv(
        kumo_path,
        [
            {
                "date": "2025-01-02",
                "symbol": "AAA",
                "falk_close": 12.5,
                "falk_volume": 1000000,
                "falk_dollar_vol": 12500000,
                "falk_score": 7.25,
                "falk_gap_pct": 2.1,
                "falk_vol_ratio_20d": 1.8,
                "falk_rank_by_score": 42,
                "falk_scanner_source_scope": "phase2_full_universe",
                "falk_scanner_source_basis": "raw_massive_parquet",
                "falk_scanner_price_adjustment": "raw_unadjusted",
                "falk_scanner_source_path": "phase2.csv.gz",
                "falk_scanner_score_df_source": "score_df",
                "falk_scanner_score_df_commit": "abc123",
                "falk_scanner_full_rank_available": "True",
                "falk_scanner_targeted_only": "False",
                "in_falk_kumo_scanner": "True",
                "in_falk_kumo_scanner_full_universe": "True",
                "falk_phase2_qualifies_7": "True",
                "falk_phase2_qualifies_6": "True",
                "company_sector": "Technology",
                "company_industry": "Semiconductors",
                "sector_category": "Technology",
                "sector_etf_proxy": "SMH",
                "sector_profile_ok": "True",
                "source_role": "falk_phase2_candidate",
            }
        ],
    )
    _write_csv(
        george_path,
        [
            {
                "date": "2025-01-02",
                "symbol": "AAA",
                "george_candidate_source": "ocr_community_scanner_image",
                "george_source_kind": "post_image_ocr",
                "george_source_confidence_observed": "medium_vision_ocr_needs_review",
                "george_rank": 4,
                "george_watchlist_rank": "",
                "george_watchlist_type": "community_post_image",
                "post_id": "post-1",
                "post_markdown_path": "post.md",
                "source_path": "ocr.png",
                "source_detail": "ocr row",
                "video_id": "",
                "george_source_family": "scanner",
                "george_source_role": "scanner_candidate_ocr",
                "source_role": "scanner_candidate_ocr",
                "george_source_confidence": "medium",
                "in_george_scanner": "True",
                "ocr_status": "ok",
            },
            {
                "date": "2025-01-02",
                "symbol": "AAA",
                "george_candidate_source": "george_watchlist_text",
                "george_source_kind": "post_text_watchlist",
                "george_source_confidence_observed": "medium_high_post_text",
                "george_rank": "",
                "george_watchlist_rank": 1,
                "george_watchlist_type": "stock",
                "post_id": "post-2",
                "post_markdown_path": "post2.md",
                "source_path": "watchlist.md",
                "source_detail": "watchlist row",
                "video_id": "",
                "george_source_family": "watchlist",
                "george_source_role": "watchlist_post_text",
                "source_role": "watchlist_post_text",
                "george_source_confidence": "high",
                "in_george_scanner": "False",
                "ocr_status": "",
            },
        ],
    )

    kumo = M.normalize_kumo_candidates(kumo_path, kumo_top_n=50)
    george = M.normalize_george_candidates(george_path)
    panel = M.build_panel(kumo, george)

    assert len(panel) == 1
    row = panel.iloc[0]
    assert row["scan_date"] == "2025-01-02"
    assert row["symbol"] == "AAA"
    assert bool(row["kumo_scanner"]) is True
    assert bool(row["kumo_top_n"]) is True
    assert bool(row["george_scanner_ocr"]) is True
    assert bool(row["george_watchlist"]) is True
    assert row["kumo_rank_by_score"] == 42
    assert row["george_rank"] == 4
    assert row["george_watchlist_rank"] == 1
    assert row["george_post_ids"] == "post-1;post-2"
    assert row["source_tags"] == "kumo_scanner;kumo_top_n;george_scanner_ocr;george_watchlist"
    assert row["source_count"] == 4
