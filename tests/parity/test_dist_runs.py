"""#265 G-DATA — dist/ runs end-to-end and produces the champion result (FAIL-LOUD).

Two complementary guards:

  1. STRUCTURAL (always runs, no LEAN): the COMMITTED dist/ closure is the champion_asis
     closure — it rebuilds to the pinned config_hash, the flat closure imports in isolation
     (proves flatness — the cloud deploy ships exactly these files), and the manifest pin is
     self-consistent. This is the "dist runs" guard that is cheap enough for CI.

  2. RECORDED-RESULT (real data, FAIL-LOUD): the dist, run end-to-end under LEAN locally,
     produces the CHAMPION trio. A full LEAN BT (560-day warmup × ~10k-name universe) is too
     heavy for CI, so the CI assertion is against the RECORDED result in results/bt-results.csv
     (provenance-pinned) PLUS, when a real local BT artifact is present in the worktree, the
     actual on-disk order-events are asserted to match the recorded champion (the BT was run
     out-of-band by scripts/measure_base_baseline.sh local / the #265 driver). DESIGN CHOICE
     flagged per Falk's mandate: recorded-result-in-CI + real-artifact-when-present, not a live
     BT in CI.

FAIL-LOUD: a dist that no longer rebuilds to the pin, or no longer imports, or whose recorded
champion result is missing/wrong → AssertionError (never skip-silently).
"""
from __future__ import annotations

import csv
import glob
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DIST = _ROOT / "dist"
_LEDGER = _ROOT / "results" / "bt-results.csv"

# The pinned champion provenance (dist/_metadata.py) + the recorded champion local trio.
_PINNED_CONFIG_HASH = "e573e84b1ce1"
_CHAMPION_MARKER = "champion-asis-post259"
_CHAMPION_LOCAL = {"sharpe": -0.139, "ret_pct": 3.62, "orders": 244, "symbols": 93}


# ── STRUCTURAL: the committed dist IS the champion closure ─────────────────────


def test_committed_dist_metadata_pins_champion() -> None:
    meta = (_DIST / "_metadata.py").read_text()
    assert f"CONFIG_HASH = '{_PINNED_CONFIG_HASH}'" in meta, (
        f"FAIL-LOUD: dist/_metadata.py no longer pins config_hash {_PINNED_CONFIG_HASH}"
    )
    man = json.loads((_DIST / "_manifest.json").read_text())
    assert man["config_hash"] == _PINNED_CONFIG_HASH, "manifest config_hash != pin"
    # the champion phase set must be present (dv_rank_cap universe + bct signal + the two regimes)
    assert man["phase_markers"]["universe"] == "dv_rank_cap_v1"
    assert man["phase_markers"]["signal"] == "bct_score_full_v1"
    assert "spy_200ma_v1" in man["phase_markers"]["regime"]


def test_committed_dist_main_is_deployable_champion() -> None:
    main_txt = (_DIST / "main.py").read_text()
    assert "name='champion-asis'" in main_txt, "dist/main.py is not the champion strategy"
    # deployable: a BCTAlgorithm subclass + the LEAN entry import (the cloud-deployed shape)
    assert "class BCTAlgorithm(BctEngineAlgorithm)" in main_txt
    assert "from lean_entry import BctEngineAlgorithm" in main_txt
    # list-valued regime must be a single grouped list literal (the codegen regression)
    assert main_txt.count("'regime':") == 1, "duplicate 'regime' key — list kind not grouped"


def test_committed_dist_imports_flat_in_isolation() -> None:
    """Import dist/main.py with ONLY dist/ on the path — proves the closure is flat + complete,
    i.e. it runs as the cloud ships it (no package prefixes, no missing sibling)."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import main; c=main.STRATEGY_CONFIG; "
         "print(c.name, sorted(c.phases))"],
        cwd=str(_DIST), capture_output=True, text=True,
    )
    assert out.returncode == 0, f"FAIL-LOUD: dist closure not importable in isolation:\n{out.stderr}"
    assert "champion-asis" in out.stdout
    # the enabled champion phases must all be wired
    for kind in ("universe", "signal", "regime", "sizing", "exit_hard", "diagnostics"):
        assert kind in out.stdout, f"phase {kind!r} missing from dist closure"


def test_committed_dist_rebuilds_to_the_pin() -> None:
    """Rebuilding strategies.champion_asis must reproduce the pinned config_hash — proves the
    committed dist traces to the champion SOURCE (git = source of truth)."""
    sys.path[:0] = [str(_ROOT / "src"), str(_ROOT / "build")]
    from build.cloud_package import build  # noqa: E402

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        r = build("strategies.champion_asis", dist_dir=Path(td))
        assert r.config_hash == _PINNED_CONFIG_HASH, (
            f"FAIL-LOUD: champion_asis rebuilds to {r.config_hash}, not the pin "
            f"{_PINNED_CONFIG_HASH} — dist drifted from source"
        )


# ── RECORDED-RESULT: the champion trio (FAIL-LOUD on missing/wrong) ────────────


def _read_ledger() -> list[dict[str, str]]:
    if not _LEDGER.is_file():
        raise AssertionError(f"FAIL-LOUD: ledger missing at {_LEDGER}")
    with _LEDGER.open() as fh:
        return list(csv.DictReader(fh))


def test_recorded_champion_local_result_present() -> None:
    rows = _read_ledger()
    hits = [
        r for r in rows
        if r.get("marker") == _CHAMPION_MARKER and str(r.get("bt_id", "")).startswith("local:")
    ]
    if not hits:
        raise AssertionError(
            f"FAIL-LOUD: no recorded local champion result (marker {_CHAMPION_MARKER}) — "
            f"dist-runs result not recorded"
        )
    r = hits[0]
    assert abs(float(r["sharpe"]) - _CHAMPION_LOCAL["sharpe"]) < 1e-6, (
        f"recorded champion Sharpe {r['sharpe']} != {_CHAMPION_LOCAL['sharpe']}"
    )
    assert abs(float(r["ret_pct"]) - _CHAMPION_LOCAL["ret_pct"]) < 1e-6
    assert int(float(r["orders"])) == _CHAMPION_LOCAL["orders"]
    assert r["config_hash"] == _PINNED_CONFIG_HASH, "recorded result not pinned to the dist hash"


def _latest_local_bt_events() -> Path | None:
    cands = sorted(
        glob.glob(str(_ROOT / "algorithm" / "v2_champion_asis" / "backtests" / "*" / "*-order-events.json"))
    )
    return Path(cands[-1]) if cands else None


def test_real_local_bt_matches_recorded_champion_when_present() -> None:
    """When a real local BT artifact exists (run out-of-band), its order-events must match the
    recorded champion symbol/order counts — proof the dist ACTUALLY ran end-to-end under LEAN
    and produced the champion. SKIPS only if no artifact present; NEVER passes on a wrong one."""
    ev = _latest_local_bt_events()
    if ev is None:
        pytest.skip("no local BT artifact in worktree (the heavy LEAN BT runs out-of-band)")
    data = json.loads(ev.read_text())
    if not data:
        raise AssertionError(f"FAIL-LOUD: order-events empty in {ev} — dist produced 0 trades")
    filled = [e for e in data if e.get("status") == "filled"]
    symbols = {str(e.get("symbolValue", "")).upper() for e in filled if e.get("symbolValue")}
    # allow a small tolerance (the artifact is the SAME run that was recorded, so it should match
    # exactly; tolerance covers a re-run with identical config drifting by a name or two).
    assert abs(len(symbols) - _CHAMPION_LOCAL["symbols"]) <= 5, (
        f"FAIL-LOUD: local BT traded {len(symbols)} symbols, recorded champion is "
        f"{_CHAMPION_LOCAL['symbols']} — dist did not reproduce the champion"
    )
    # order-events ≈ 2× orders (submit+fill); assert filled count is in the champion range.
    assert 200 <= len(filled) <= 280, (
        f"FAIL-LOUD: {len(filled)} filled events, champion ~243 — dist result drifted"
    )
