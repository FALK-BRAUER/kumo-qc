"""#358 — warmup-cache LOADER tests: parity round-trip, FAIL-CLOSED guard, as-of keying.

The loader is the cloud-safety surface (the 8b50c1a guard): it must load the local cache ONLY on a
fingerprint match and fall back to None (→ live re-derivation) on cloud/mismatch/missing/garbage.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from sweeps.warmup_cache.loader import WEEKLY_FIELDS, load_weekly_cache

_WK = {"w_tenkan": 1.5, "w_kijun": 2.5, "w_senkou_a": 3.5,
       "w_senkou_b": 4.5, "w_close_0": 5.5, "w_close_26": 6.5}
_FIELDS = ["d_price", "d_tenkan", "d_cloud_top", "ma200", *WEEKLY_FIELDS, "roc13"]


def _write_cache(root: Path, fingerprint: str, sym_rows: dict[str, list[tuple[str, dict]]]) -> Path:
    """Write a cache dir matching build_warmup_cache's layout: <root>/<fp>/_FIELDS.json + <sym>.jsonl."""
    d = root / fingerprint
    d.mkdir(parents=True, exist_ok=True)
    (d / "_FIELDS.json").write_text(json.dumps({"fields": _FIELDS, "fingerprint": fingerprint}))
    for sym, rows in sym_rows.items():
        lines = []
        for date_iso, wk in rows:
            row = {"date": date_iso, "d_price": 10.0, "roc13": 0.1, **wk}
            lines.append(json.dumps(row, separators=(",", ":")))
        (d / f"{sym}.jsonl").write_text("\n".join(lines) + "\n")
    return d


# ── 1. PARITY round-trip: the loaded weekly scalars are byte-identical to what was written ──
def test_round_trip_exact(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"aapl": [("2025-01-02", _WK)]})
    cache = load_weekly_cache(d, "fp1")
    assert cache is not None
    got = cache["AAPL"][_dt.date(2025, 1, 2)]
    assert got == _WK                                   # exact, no drift
    assert set(got) == set(WEEKLY_FIELDS)               # only the 6 weekly scalars


def test_symbol_keyed_uppercase(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"msft": [("2025-03-03", _WK)]})
    cache = load_weekly_cache(d, "fp1")
    assert "MSFT" in cache and "msft" not in cache      # caller keys by symbol.value (upper)


# ── 2. FAIL-CLOSED guard (the cloud-divergence prevention) ──
def test_fail_closed_no_expected_fingerprint(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"aapl": [("2025-01-02", _WK)]})
    assert load_weekly_cache(d, None) is None           # cloud: no injected fingerprint → never load
    assert load_weekly_cache(d, "") is None


def test_fail_closed_no_cache_dir():
    assert load_weekly_cache(None, "fp1") is None
    assert load_weekly_cache("/nonexistent/path/xyz", "fp1") is None


def test_fail_closed_fingerprint_mismatch(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"aapl": [("2025-01-02", _WK)]})
    assert load_weekly_cache(d, "fp2") is None          # cloud's different vendor data → mismatch → no load


def test_fail_closed_missing_fields_json(tmp_path):
    d = tmp_path / "fp1"
    (d).mkdir(parents=True)
    (d / "aapl.jsonl").write_text(json.dumps({"date": "2025-01-02", **_WK}) + "\n")
    assert load_weekly_cache(d, "fp1") is None          # no _FIELDS.json → can't verify fingerprint → no load


def test_fail_closed_cache_lacks_weekly_fields(tmp_path):
    d = tmp_path / "fp1"
    d.mkdir(parents=True)
    (d / "_FIELDS.json").write_text(json.dumps({"fields": ["d_price", "ma200"], "fingerprint": "fp1"}))
    (d / "aapl.jsonl").write_text(json.dumps({"date": "2025-01-02", "d_price": 10.0}) + "\n")
    assert load_weekly_cache(d, "fp1") is None          # pre-weekly cache → don't half-load


# ── 3. AS-OF keying: lookup by decision-date; a date not in the cache → None (no future row) ──
def test_asof_keying_present_and_absent(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"aapl": [
        ("2025-01-02", _WK),
        ("2025-01-03", {**_WK, "w_tenkan": 9.9}),
    ]})
    cache = load_weekly_cache(d, "fp1")
    assert cache["AAPL"][_dt.date(2025, 1, 2)]["w_tenkan"] == 1.5
    assert cache["AAPL"][_dt.date(2025, 1, 3)]["w_tenkan"] == 9.9
    assert cache["AAPL"].get(_dt.date(2025, 1, 6)) is None   # a date with no row → caller falls back live (no future peek)


# ── robustness: a corrupt per-symbol file skips ONLY that symbol (others still load) ──
def test_corrupt_symbol_file_skipped_not_poisoning(tmp_path):
    d = _write_cache(tmp_path, "fp1", {"good": [("2025-01-02", _WK)]})
    (d / "bad.jsonl").write_text("{not json\n")
    cache = load_weekly_cache(d, "fp1")
    assert cache is not None and "GOOD" in cache and "BAD" not in cache
