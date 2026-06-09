"""Behavioral tests for pure scanner sector/industry breadth features."""
from __future__ import annotations

import math

from phases.shared.sector_breadth import BreadthCandidate, sector_industry_breadth_rows


def test_sector_and_industry_breadth_uses_candidate_panel_denominator() -> None:
    rows = sector_industry_breadth_rows(
        [
            BreadthCandidate(
                ticker="AAA",
                sector="Technology",
                industry="Software",
                bct_score=7,
                day_return_pct=2.0,
                rel_volume20=1.4,
            ),
            BreadthCandidate(
                ticker="BBB",
                sector="Technology",
                industry="Software",
                bct_score=6,
                day_return_pct=-1.0,
                rel_volume20=0.8,
            ),
            BreadthCandidate(
                ticker="CCC",
                sector="Technology",
                industry="Semiconductors",
                bct_score=8,
                day_return_pct=4.0,
                rel_volume20=2.0,
            ),
            BreadthCandidate(
                ticker="DDD",
                sector="Healthcare",
                industry="Biotech",
                bct_score=5,
                day_return_pct=3.0,
                rel_volume20=1.1,
            ),
        ]
    )

    aaa = rows[0]
    ccc = rows[2]
    ddd = rows[3]

    assert aaa["sector_key"] == "technology"
    assert aaa["industry_key"] == "technology|software"
    assert aaa["sector_denominator_count"] == 3
    assert aaa["sector_bct6_count"] == 3
    assert aaa["sector_bct7_count"] == 2
    assert aaa["sector_positive_return_count"] == 2
    assert aaa["sector_median_day_return_pct"] == 2.0
    assert aaa["sector_median_rel_volume20"] == 1.4
    assert aaa["sector_bct7_pct"] == 100.0 * 2.0 / 3.0
    assert aaa["industry_denominator_count"] == 2
    assert aaa["industry_bct7_count"] == 1
    assert aaa["industry_positive_return_pct"] == 50.0

    assert ccc["industry_key"] == "technology|semiconductors"
    assert ccc["industry_denominator_count"] == 1
    assert ccc["industry_bct7_pct"] == 100.0
    assert ddd["sector_denominator_count"] == 1
    assert ddd["sector_bct6_pct"] == 0.0


def test_sector_breadth_uses_runtime_maps_when_row_taxonomy_is_missing() -> None:
    rows = sector_industry_breadth_rows(
        [
            BreadthCandidate("AAA", bct_score=7, day_return_pct=1.0, rel_volume20=1.2),
            BreadthCandidate("bbb", bct_score=6, day_return_pct=-2.0, rel_volume20=0.9),
        ],
        sector_by_ticker={"aaa": "Materials", "bbb": "Materials"},
        industry_by_ticker={"AAA": "Metals", "bbb": "Metals"},
    )

    assert rows[0]["sector_key"] == "materials"
    assert rows[0]["industry_key"] == "materials|metals"
    assert rows[0]["sector_denominator_count"] == 2
    assert rows[0]["industry_bct6_count"] == 2
    assert rows[1]["industry_positive_return_count"] == 1


def test_missing_taxonomy_falls_back_to_unknown_group() -> None:
    rows = sector_industry_breadth_rows(
        [
            BreadthCandidate("AAA", bct_score=None, day_return_pct=None, rel_volume20=None),
            BreadthCandidate("BBB", sector="", industry="", bct_score=7, day_return_pct=2.0, rel_volume20=1.5),
        ]
    )

    assert rows[0]["sector_key"] == "unknown"
    assert rows[0]["industry_key"] == "unknown|unknown"
    assert rows[0]["sector_denominator_count"] == 0
    assert rows[0]["sector_bct6_count"] == 0
    assert rows[0]["sector_median_day_return_pct"] == 0.0
    assert math.isnan(rows[0]["sector_median_rel_volume20"])
    assert rows[1]["industry_denominator_count"] == 0
