"""Tests for scripts/build_universe.py — the RANK + CAP precompute (#220, rescoped).

Reads the eligible artifact (date -> {ticker: dv}) and ranks+caps. Behavioral: rank by
DV desc, ticker-asc tiebreak, coarse_max cap, order preserved, SHUFFLE-input determinism
(the #182 test), every date preserved. No zips here — input is the filter artifact.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_universe.py"
_spec = importlib.util.spec_from_file_location("build_universe", _SPEC_PATH)
assert _spec and _spec.loader
bu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bu)


def test_ranks_by_dv_desc_not_alphabetical():
    # alphabetical order is the REVERSE of DV order, so the two can't be confused.
    elig = {"2025-01-02": {"aaa": 2e7, "mmm": 5e7, "zzz": 1e8}}
    uni = bu.rank_and_cap(elig)
    assert uni["2025-01-02"] == ["zzz", "mmm", "aaa"]
    assert uni["2025-01-02"] != sorted(uni["2025-01-02"])


def test_tiebreak_ticker_asc_on_equal_dv():
    elig = {"2025-01-02": {"delta": 5e7, "bravo": 5e7, "alpha": 5e7, "charlie": 5e7}}
    uni = bu.rank_and_cap(elig)
    assert uni["2025-01-02"] == ["alpha", "bravo", "charlie", "delta"]


def test_coarse_max_caps_to_top_k_by_dv():
    elig = {"2025-01-02": {"big": 1e8, "mid": 5e7, "small": 2e7}}
    uni = bu.rank_and_cap(elig, coarse_max=2)
    assert uni["2025-01-02"] == ["big", "mid"]  # top-2 by DV, rank order; small capped


def test_unbounded_default_keeps_all_in_rank_order():
    elig = {"2025-01-02": {"big": 1e8, "mid": 5e7, "small": 2e7}}
    uni = bu.rank_and_cap(elig)  # default 9999
    assert uni["2025-01-02"] == ["big", "mid", "small"]


def test_shuffle_input_identical_output_order():
    # THE #182 DETERMINISM TEST: dict iteration order must NOT affect the ranked output.
    # Same DV values inserted in different orders -> identical ranked list.
    a = {"2025-01-02": {"zzz": 1e8, "aaa": 2e7, "mmm": 5e7}}
    b = {"2025-01-02": {"aaa": 2e7, "mmm": 5e7, "zzz": 1e8}}  # different insertion order
    c = {"2025-01-02": {"mmm": 5e7, "zzz": 1e8, "aaa": 2e7}}
    out = [bu.rank_and_cap(x)["2025-01-02"] for x in (a, b, c)]
    assert out[0] == out[1] == out[2] == ["zzz", "mmm", "aaa"]


def test_empty_eligible_date_stays_empty():
    elig = {"2025-01-02": {}, "2025-01-03": {"x": 5e7}}
    uni = bu.rank_and_cap(elig)
    assert uni["2025-01-02"] == []
    assert uni["2025-01-03"] == ["x"]


def test_every_date_preserved():
    elig = {"2025-01-02": {}, "2025-01-03": {}, "2025-01-06": {"x": 5e7}}
    uni = bu.rank_and_cap(elig)
    assert set(uni) == {"2025-01-02", "2025-01-03", "2025-01-06"}


def test_order_hash_is_order_sensitive():
    # The ranked artifact's whole point is ORDER; the fingerprint must change if order does.
    u1 = {"d": ["a", "b", "c"]}
    u2 = {"d": ["c", "b", "a"]}
    assert bu.order_hash(u1) != bu.order_hash(u2)
    assert bu.order_hash(u1) == bu.order_hash({"d": ["a", "b", "c"]})  # deterministic
    assert len(bu.order_hash(u1)) == 64


def test_load_filter_artifact_strips_meta(tmp_path: Path):
    art = tmp_path / "f.json"
    art.write_text(json.dumps({
        "2025-01-02": {"x": 5e7},
        "_filter_meta": {"min_price": 10.0},
    }))
    loaded = bu.load_filter_artifact(art)
    assert loaded == {"2025-01-02": {"x": 5e7}}
    assert "_filter_meta" not in loaded


def test_cli_reads_filter_writes_ranked(tmp_path: Path):
    filt = tmp_path / "f.json"
    filt.write_text(json.dumps({
        "2025-01-02": {"big": 1e8, "mid": 5e7},
        "_filter_meta": {},
    }))
    out = tmp_path / "u.json"
    rc = bu.main(["--filter-artifact", str(filt), "--coarse-max", "5", "--out", str(out)])
    assert rc == 0 and out.exists()
    payload = json.loads(out.read_text())
    assert payload["2025-01-02"] == ["big", "mid"]  # rank order
    assert payload["_universe_meta"]["coarse_max"] == 5
    assert "rank+cap" in payload["_universe_meta"]["model"]
    assert len(payload["_universe_meta"]["order_fingerprint"]) == 64
    assert out.with_suffix(".meta.json").exists()
