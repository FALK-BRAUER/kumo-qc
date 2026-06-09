"""Tests for the offline first-hour confirmation audit."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from sweeps.archive import first_hour_confirmation as F


def _write_minute_zip(
    minute_dir: Path,
    symbol: str,
    date: str,
    rows: list[tuple[int, float, float, float, float, int]],
) -> None:
    lean = symbol.lower()
    ymd = date.replace("-", "")
    target = minute_dir / lean
    target.mkdir(parents=True, exist_ok=True)
    lines = []
    for ms, open_, high, low, close, volume in rows:
        lines.append(
            ",".join(
                [
                    str(ms),
                    str(int(open_ * F.PRICE_SCALE)),
                    str(int(high * F.PRICE_SCALE)),
                    str(int(low * F.PRICE_SCALE)),
                    str(int(close * F.PRICE_SCALE)),
                    str(volume),
                ]
            )
        )
    with zipfile.ZipFile(target / f"{ymd}_trade.zip", "w") as zf:
        zf.writestr(f"{ymd}_{lean}_minute_trade.csv", "\n".join(lines) + "\n")


def _candidate(symbol: str, *, avg_volume20: float = 100_000.0, gap_pct: float = 0.0) -> dict[str, object]:
    return {
        "date": "2026-02-12",
        "symbol": symbol,
        "gap_pct": gap_pct,
        "avg_volume20": avg_volume20,
        "bct_score": 6,
        "bct_candidate_lane": "almost_bct_score6",
    }


def test_read_minute_trade_zip_and_first_hour_features(tmp_path: Path) -> None:
    _write_minute_zip(
        tmp_path,
        "AAA",
        "2026-02-12",
        [
            (34_200_000, 100.0, 101.0, 99.5, 100.5, 2_000),
            (34_500_000, 100.5, 102.0, 100.0, 101.5, 3_000),
            (34_800_000, 101.5, 103.0, 101.0, 102.5, 4_000),
        ],
    )
    bars = F.read_minute_trade_zip(tmp_path, "AAA", "2026-02-12")
    assert bars is not None
    features = F.first_hour_features(pd.Series(_candidate("AAA")), bars, config=F.FirstHourConfig(first_hour_bars=3))

    assert features["intraday_available"] is True
    assert features["fh_bars"] == 3
    assert features["fh_green"] is True
    assert features["fh_no_open_flush"] is True
    assert features["fh_above_prior_close"] is True
    assert features["fh_reclaims_first_bar_high"] is True
    assert features["fh_confirm_breakout_volume"] is True


def test_first_hour_flags_reject_open_flush_and_weak_close(tmp_path: Path) -> None:
    _write_minute_zip(
        tmp_path,
        "BBB",
        "2026-02-12",
        [
            (34_200_000, 100.0, 101.0, 96.0, 97.0, 1_000),
            (34_500_000, 97.0, 98.0, 95.0, 96.0, 1_000),
        ],
    )
    bars = F.read_minute_trade_zip(tmp_path, "BBB", "2026-02-12")
    assert bars is not None
    features = F.first_hour_features(pd.Series(_candidate("BBB")), bars, config=F.FirstHourConfig(first_hour_bars=2))

    assert features["fh_green"] is False
    assert features["fh_no_open_flush"] is False
    assert features["fh_confirm_basic"] is False


def test_run_confirmation_summarizes_labels_and_missing_intraday(tmp_path: Path) -> None:
    _write_minute_zip(
        tmp_path,
        "AAA",
        "2026-02-12",
        [
            (34_200_000, 100.0, 101.0, 99.5, 100.5, 2_000),
            (34_500_000, 100.5, 102.0, 100.0, 101.5, 3_000),
        ],
    )
    candidates = pd.DataFrame([_candidate("AAA"), _candidate("MISS")])
    result = F.run_confirmation(
        candidates,
        minute_dir=tmp_path,
        labels=[("2026-02-12", "AAA"), ("2026-02-12", "MISS")],
        config=F.FirstHourConfig(first_hour_bars=2, min_first_hour_adv_ratio=0.01),
    )
    flags = result.flag_summary.set_index("flag")

    assert result.summary.iloc[0]["rows"] == 2
    assert result.summary.iloc[0]["intraday_available_rows"] == 1
    assert result.summary.iloc[0]["labels_with_intraday"] == 1
    assert flags.loc["fh_confirm_basic", "label_hits"] == 1
    assert flags.loc["fh_confirm_basic", "label_recall_pct"] == 50.0
    assert flags.loc["fh_confirm_basic", "panel_label_recall_pct"] == 50.0
    assert flags.loc["fh_confirm_basic", "label_precision_pct"] == 100.0
    assert flags.loc["fh_confirm_basic", "label_lift_vs_panel"] == 1.0


def test_write_result_outputs_csvs(tmp_path: Path) -> None:
    candidates = pd.DataFrame([_candidate("MISS")])
    result = F.run_confirmation(candidates, minute_dir=tmp_path)
    out = tmp_path / "out"
    F.write_result(result, out)

    assert (out / "first_hour_panel.csv").is_file()
    assert (out / "summary.csv").is_file()
    assert (out / "flag_summary.csv").is_file()
