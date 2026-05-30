"""Tests for scripts/build_universe.py — the point-in-time top-N DV precompute.

Uses small synthetic daily zips in tmp_path (deci-cents close, share volume) with
known closes/volumes so the expected ranking / floors / point-in-time behaviour are
hand-checkable. build_universe.py lives in scripts/, imported by path.
"""
from __future__ import annotations

import importlib.util
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

_SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_universe.py"
_spec = importlib.util.spec_from_file_location("build_universe", _SPEC_PATH)
assert _spec and _spec.loader
build_universe_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_universe_mod)

DECI = 10_000.0


def _write_zip(data_dir: Path, ticker: str, rows: list[tuple[str, float, float]]) -> None:
    """rows = [(YYYYMMDD, close_dollars, volume_shares), ...]. Writes a LEAN-style zip
    with an inner <ticker>.csv: 'YYYYMMDD 00:00,O,H,L,C,V' (deci-cents OHLC)."""
    lines = []
    for ymd, close_usd, vol in rows:
        dc = int(round(close_usd * DECI))
        # O/H/L are not used by the builder; reuse close in deci-cents.
        lines.append(f"{ymd} 00:00,{dc},{dc},{dc},{dc},{int(vol)}")
    csv_body = "\n".join(lines) + "\n"
    zpath = data_dir / f"{ticker}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{ticker}.csv", csv_body)


def _dates(start: date, count: int) -> list[str]:
    """count consecutive calendar days as YYYYMMDD strings (builder treats every
    bar-date as a trading date; synthetic data uses dense days for simplicity)."""
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(count)]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "daily"
    d.mkdir()
    return d


def test_topn_ranking_by_dollar_volume(data_dir: Path):
    # window=3. Three tickers, all priced > floor, all liquid. DV ordering:
    # big (close 100, vol 1e6 -> 1e8) > mid (50, 1e6 -> 5e7) > small (20, 1e6 -> 2e7).
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "big", [(d, 100.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "mid", [(d, 50.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "small", [(d, 20.0, 1_000_000) for d in ds])

    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=2, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    last = "2025-01-05"
    assert last in uni
    # top 2 by DV = big, mid. Output is sorted alphabetically within the day.
    assert set(uni[last]) == {"big", "mid"}
    assert "small" not in uni[last]
    # Result list is sorted.
    assert uni[last] == sorted(uni[last])


def test_price_floor_excludes_cheap(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 4)
    # cheapo has HUGE dv but close < price_floor -> excluded.
    _write_zip(data_dir, "cheapo", [(d, 5.0, 100_000_000) for d in ds])
    _write_zip(data_dir, "pricey", [(d, 50.0, 1_000_000) for d in ds])

    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=10, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    last = "2025-01-04"
    assert uni[last] == ["pricey"]


def test_dv_floor_excludes_illiquid(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 4)
    # thin: close 50 * vol 100 = 5_000 DV < floor 1e6 -> excluded.
    _write_zip(data_dir, "thin", [(d, 50.0, 100) for d in ds])
    _write_zip(data_dir, "thick", [(d, 50.0, 1_000_000) for d in ds])  # 5e7 DV

    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=10, price_floor=10.0, dv_floor=1_000_000.0, dv_window=3,
    )
    last = "2025-01-04"
    assert uni[last] == ["thick"]


def test_point_in_time_no_history_absent_then_present(data_dir: Path):
    # window=3. "early" lists from day 1; "late" lists only from day 4.
    # On day 3 "late" has 0 bars -> absent. On day 6 "late" has 3 bars -> present.
    early_ds = _dates(date(2025, 1, 1), 6)
    late_ds = _dates(date(2025, 1, 4), 3)  # 2025-01-04..06
    _write_zip(data_dir, "early", [(d, 50.0, 1_000_000) for d in early_ds])
    _write_zip(data_dir, "late", [(d, 80.0, 2_000_000) for d in late_ds])

    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=10, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )

    # 2025-01-03: late has no bars at all -> absent. early has 3 bars -> present.
    assert "late" not in uni["2025-01-03"]
    assert "early" in uni["2025-01-03"]
    # 2025-01-05: late has only 2 bars (04,05) < window=3 -> still absent (point-in-time).
    assert "late" not in uni["2025-01-05"]
    # 2025-01-06: late now has 3 bars -> present.
    assert "late" in uni["2025-01-06"]


def test_no_future_leak_first_window_days_absent(data_dir: Path):
    # A ticker must not appear before it accumulates dv_window bars, even though the
    # full history exists in the file (no hindsight).
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "x", [(d, 50.0, 1_000_000) for d in ds])
    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=10, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    # days 1,2 (only 1,2 bars) -> x absent / date omitted; day 3 onward -> present.
    assert uni.get("2025-01-01", []) == []  # omitted (no eligible) -> .get default
    assert uni.get("2025-01-02", []) == []
    assert "x" in uni["2025-01-03"]
    assert "x" in uni["2025-01-05"]


def test_deterministic_hash(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "big", [(d, 100.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "mid", [(d, 50.0, 1_000_000) for d in ds])

    kwargs = dict(data_dir=data_dir, n=5, price_floor=10.0, dv_floor=1.0, dv_window=3)
    uni1 = build_universe_mod.build_universe(**kwargs)
    uni2 = build_universe_mod.build_universe(**kwargs)
    h1 = build_universe_mod.content_hash(uni1)
    h2 = build_universe_mod.content_hash(uni2)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_changes_when_universe_changes(data_dir: Path):
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "big", [(d, 100.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "mid", [(d, 50.0, 1_000_000) for d in ds])
    base = build_universe_mod.build_universe(
        data_dir=data_dir, n=5, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    # n=1 drops "mid" from the top set -> different mapping -> different hash.
    narrowed = build_universe_mod.build_universe(
        data_dir=data_dir, n=1, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    assert build_universe_mod.content_hash(base) != build_universe_mod.content_hash(narrowed)


def test_cli_writes_json_and_meta(data_dir: Path, tmp_path: Path):
    ds = _dates(date(2025, 1, 1), 5)
    _write_zip(data_dir, "big", [(d, 100.0, 1_000_000) for d in ds])
    _write_zip(data_dir, "mid", [(d, 50.0, 1_000_000) for d in ds])
    out = tmp_path / "u.json"
    rc = build_universe_mod.main([
        "--n", "5", "--price-floor", "10", "--dv-floor", "1", "--dv-window", "3",
        "--data-dir", str(data_dir), "--out", str(out),
    ])
    assert rc == 0
    assert out.exists()
    meta = out.with_suffix(".meta.json")
    assert meta.exists()

    import json
    payload = json.loads(out.read_text())
    assert "_universe_meta" in payload
    assert payload["_universe_meta"]["n"] == 5
    assert len(payload["_universe_meta"]["universe_fingerprint"]) == 64
    # meta sibling has params + fingerprint.
    meta_obj = json.loads(meta.read_text())
    assert meta_obj["params"]["dv_window"] == 3
    assert meta_obj["universe_fingerprint"] == payload["_universe_meta"]["universe_fingerprint"]


def test_every_trading_date_emitted_no_gaps_incl_zero_eligible(data_dir: Path):
    # #182 other-trap guard: every substrate trading date (>= window history) gets a KEY,
    # even when zero tickers qualify -> empty list, NOT omitted. So a consumer's missing
    # date means non-trading-day, never a silent precompute gap.
    ds = _dates(date(2025, 1, 1), 5)
    # all below price_floor -> every eligible-eval is False -> zero-eligible days
    _write_zip(data_dir, "cheaponly", [(d, 3.0, 100_000_000) for d in ds])
    uni = build_universe_mod.build_universe(
        data_dir=data_dir, n=10, price_floor=10.0, dv_floor=1.0, dv_window=3,
    )
    # dates with >= window(3) history: 2025-01-03, -04, -05 — all present, all EMPTY (not omitted)
    for dk in ("2025-01-03", "2025-01-04", "2025-01-05"):
        assert dk in uni, f"{dk} omitted — silent gap (the #182 trap)"
        assert uni[dk] == [], f"{dk} should be empty (zero-eligible), got {uni[dk]}"
