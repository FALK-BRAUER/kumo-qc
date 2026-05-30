"""Tests for scripts/build_filter.py — the tradeability FILTER precompute (#233).

Synthetic daily zips with hand-chosen closes/volumes so each floor boundary, the
adv_window mean, and the point-in-time guard are checkable. Behavioral, not structural.
"""
from __future__ import annotations

import importlib.util
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

_SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_filter.py"
_spec = importlib.util.spec_from_file_location("build_filter", _SPEC_PATH)
assert _spec and _spec.loader
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)

DECI = 10_000.0


def _write_zip(data_dir: Path, ticker: str, rows: list[tuple[str, float, float]]) -> None:
    lines = []
    for ymd, close_usd, vol in rows:
        dc = int(round(close_usd * DECI))
        lines.append(f"{ymd} 00:00,{dc},{dc},{dc},{dc},{int(vol)}")
    csv_body = "\n".join(lines) + "\n"
    with zipfile.ZipFile(data_dir / f"{ticker}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{ticker}.csv", csv_body)


def _dates(start: date, count: int) -> list[str]:
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "daily"
    d.mkdir()
    return d


def test_price_above_floor_passes_below_fails(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "above", [(d, 11.0, 1_000_000) for d in ds])  # > 10
    _write_zip(data_dir, "below", [(d, 9.0, 1_000_000) for d in ds])   # < 10
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    last = "2025-01-04"
    assert "above" in filt[last]
    assert "below" not in filt[last]


def test_price_exactly_at_floor_passes(data_dir: Path):
    # Boundary: close == min_price -> eligible (>= comparison).
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "edge", [(d, 10.0, 1_000_000) for d in ds])
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    assert "edge" in filt["2025-01-04"]


def test_dv_above_floor_passes_below_fails(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 4)
    # priced fine; DV = close*vol. floor 5e6.
    _write_zip(data_dir, "liquid", [(d, 50.0, 200_000) for d in ds])   # 1e7 DV > 5e6
    _write_zip(data_dir, "thin", [(d, 50.0, 50_000) for d in ds])      # 2.5e6 DV < 5e6
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=5_000_000.0, adv_window=3)
    last = "2025-01-04"
    assert "liquid" in filt[last]
    assert "thin" not in filt[last]


def test_dv_exactly_at_floor_passes(data_dir: Path):
    # close 50 * vol 100_000 = 5_000_000 == floor -> eligible.
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "edge", [(d, 50.0, 100_000) for d in ds])
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=5_000_000.0, adv_window=3)
    assert "edge" in filt["2025-01-04"]


def test_adv_window_mean_math(data_dir: Path):
    # adv_window=3. Volumes 100k,200k,300k over 3 days at close 50 ->
    # DVs 5e6, 1e7, 1.5e7; trailing-3 mean on day 3 = (5e6+1e7+1.5e7)/3 = 1e7.
    # Carried DV value must equal that mean.
    ds = _dates(date(2025, 1, 1), 3)
    _write_zip(data_dir, "x", [
        (ds[0], 50.0, 100_000),
        (ds[1], 50.0, 200_000),
        (ds[2], 50.0, 300_000),
    ])
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    assert filt["2025-01-03"]["x"] == pytest.approx(10_000_000.0)


def test_artifact_carries_dv_per_eligible_ticker(data_dir: Path):
    # The eligible artifact is {date: {ticker: dv}} so the universe step ranks without
    # re-reading zips. Verify the value is the trailing-mean DV (constant-volume case).
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "x", [(d, 50.0, 1_000_000) for d in ds])  # DV 5e7 constant
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    assert filt["2025-01-04"]["x"] == pytest.approx(50_000_000.0)


def test_point_in_time_first_window_days_absent(data_dir: Path):
    # No name before it has adv_window bars (no hindsight).
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "x", [(d, 50.0, 1_000_000) for d in ds])
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    assert filt["2025-01-01"] == {}  # 1 bar < window
    assert filt["2025-01-02"] == {}  # 2 bars < window
    assert "x" in filt["2025-01-03"]  # 3 bars == window


def test_every_trading_date_emitted_incl_zero_eligible(data_dir: Path):
    # #182 gap trap: every date keyed, zero-eligible -> empty DICT (not omitted).
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "cheaponly", [(d, 3.0, 100_000_000) for d in ds])  # below price floor
    filt = bf.build_filter(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    for dk in ("2025-01-03", "2025-01-04", "2025-01-05"):
        assert dk in filt, f"{dk} omitted — silent gap (#182)"
        assert filt[dk] == {}


def test_membership_hash_deterministic_and_dv_independent(data_dir: Path):
    # Membership fingerprint = pure eligibility (DV excluded). Two runs identical;
    # length 64 (sha256). It is the "diff this FIRST" handle in divergence-debug.
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "a", [(d, 50.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "b", [(d, 80.0, 2_000_000) for d in ds])
    kwargs = dict(data_dir=data_dir, min_price=10.0, min_avg_dollar_volume=1.0, adv_window=3)
    f1 = bf.build_filter(**kwargs)
    f2 = bf.build_filter(**kwargs)
    h1 = bf.membership_hash(f1)
    assert h1 == bf.membership_hash(f2)
    assert len(h1) == 64


def test_cli_writes_filter_json_and_meta(data_dir: Path, tmp_path: Path):
    ds = _dates(date(2025, 1, 1), 4)
    _write_zip(data_dir, "a", [(d, 50.0, 1_000_000) for d in ds])
    out = tmp_path / "f.json"
    rc = bf.main([
        "--min-price", "10", "--min-avg-dollar-volume", "1", "--adv-window", "3",
        "--data-dir", str(data_dir), "--out", str(out),
    ])
    assert rc == 0 and out.exists()
    import json
    payload = json.loads(out.read_text())
    assert "_filter_meta" in payload
    assert payload["_filter_meta"]["min_price"] == 10.0
    assert len(payload["_filter_meta"]["membership_fingerprint"]) == 64
    # eligible value is a {ticker: dv} dict
    assert payload["2025-01-04"]["a"] == pytest.approx(50_000_000.0)
    meta = out.with_suffix(".meta.json")
    assert meta.exists()
