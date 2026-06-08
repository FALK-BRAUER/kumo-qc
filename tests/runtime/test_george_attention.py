from __future__ import annotations

import pytest

from runtime.george_attention import load_george_attention_maps, read_george_attention


def test_george_attention_loads_weighted_ticker_and_industry_maps(tmp_path) -> None:
    path = tmp_path / "attention.csv"
    path.write_text(
        "ticker,industry,source_role,attention_score,confidence\n"
        "ATI,Specialty Metals,scanner_candidate,2.0,0.5\n"
        "ATI,Specialty Metals,actual_trade,3.0,1.0\n"
        ",Software,video_discussion,1.5,0.4\n",
        encoding="utf-8",
    )

    rows = read_george_attention(path)
    maps = load_george_attention_maps(path)

    assert len(rows) == 3
    assert maps["ticker_attention"] == {"ati": 4.0}
    assert maps["industry_attention"]["specialty metals"] == 4.0
    assert maps["industry_attention"]["software"] == pytest.approx(0.6)
    assert maps["source_role_counts"] == {
        "scanner_candidate": 1,
        "actual_trade": 1,
        "video_discussion": 1,
    }


def test_george_attention_skips_rows_without_ticker_or_industry(tmp_path) -> None:
    path = tmp_path / "attention.csv"
    path.write_text("ticker,industry,source_role\n,,bad\nCRM,Software,video_discussion\n", encoding="utf-8")

    rows = read_george_attention(path)

    assert [r.ticker for r in rows] == ["crm"]
