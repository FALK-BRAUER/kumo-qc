"""#265 G-DATA — local ≈ cloud parity regression guard (FAIL-LOUD, real recorded data).

WHY: post-#259 the empty-warmup mirage is closed, but a residual remains (signal-layer; see
research/parity/residual-root-cause-2025.md). The TRUE baseline is the CLOUD number
(−0.683 Sharpe / −9.05% / 291 orders / 113 symbols); local (−0.139 / +3.62% / 244 / 93) is an
optimistic within-band approximation. This test is the REGRESSION GUARD: if a future change
re-breaks parity (e.g. re-introduces the warmup mirage → local drifts FAR from cloud, or
collapses to ~0 trades), it FAILS LOUD here.

DESIGN CHOICE (flagged per Falk's mandate): this test does NOT call the QC cloud API in CI
(no network, no cost, deterministic). It asserts against the RECORDED cloud ground-truth row in
results/bt-results.csv (the ledger = source of truth, provenance-pinned). The local side is
read from the SAME recorded ledger row; a SEPARATE real-data mirage guard
(test_local_bt_is_not_a_zero_trade_mirage) asserts the actual on-disk local BT order-events when
present. A full LEAN BT is too heavy for CI (560-day warmup × ~10k-name universe ≈ minutes) — so
the recorded-result assertion is the CI guard, the heavy BT is run out-of-band and recorded.

FAIL-LOUD edges (all FAIL, never skip-silently):
  - cloud baseline row missing from the ledger          → AssertionError (can't validate → red)
  - cloud / local row malformed (non-numeric metrics)   → AssertionError
  - local diverges from cloud BEYOND the documented band → AssertionError (the re-break guard)
  - a present local BT produced 0 trades over full-FY    → AssertionError (the mirage guard)
"""
from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LEDGER = _ROOT / "results" / "bt-results.csv"

# The post-#259 apples-to-apples markers in the ledger (config_hash e573e84b1ce1 / commit 8e80cc3).
_MARKER = "champion-asis-post259"

# DOCUMENTED RESIDUAL BAND (research/parity/residual-root-cause-2025.md §"Documented residual
# BAND"). |local − cloud| must NOT exceed these. WIDE BY NECESSITY — it documents the current
# UNCLOSED signal-layer residual, not a parity claim. Tightening the band == the acceptance
# criterion for the signal-layer fix. A future change that BLOWS PAST it (warmup re-break) =
# RED. A change that converges INSIDE it legitimately = still green (the band is an envelope).
_BAND_SHARPE = 0.70  # |Δ Sharpe|
_BAND_RETURN_PP = 15.0  # |Δ net-return| in percentage points
_BAND_ORDER_FRAC = 0.25  # |Δ orders| / cloud orders
_BAND_SYMBOL_FRAC = 0.25  # symbol-count tolerance is informational; orders is the binding one

# The recorded post-#259 cloud GROUND TRUTH (pinned; the test asserts the ledger still matches).
_CLOUD_GT = {"sharpe": -0.683, "ret_pct": -9.05, "orders": 291}


def _read_ledger_rows() -> list[dict[str, str]]:
    if not _LEDGER.is_file():
        raise AssertionError(f"FAIL-LOUD: ledger missing at {_LEDGER} — cannot validate parity")
    with _LEDGER.open() as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise AssertionError(f"FAIL-LOUD: ledger {_LEDGER} is empty")
    return rows


def _find_row(rows: list[dict[str, str]], side: str) -> dict[str, str]:
    """side = 'cloud' | 'local'. Match the post-#259 marker + the bt_id prefix. FAIL-LOUD if
    absent or ambiguous — a missing/duplicate baseline must go RED, never pass."""
    hits = [
        r for r in rows
        if r.get("marker") == _MARKER and str(r.get("bt_id", "")).startswith(side + ":")
    ]
    if not hits:
        raise AssertionError(
            f"FAIL-LOUD: no '{side}' row with marker '{_MARKER}' in {_LEDGER} — the "
            f"{'cloud ground-truth' if side == 'cloud' else 'local'} baseline is missing"
        )
    if len(hits) > 1:
        raise AssertionError(
            f"FAIL-LOUD: {len(hits)} '{side}' rows with marker '{_MARKER}' — ambiguous baseline"
        )
    return hits[0]


def _num(row: dict[str, str], col: str) -> float:
    raw = row.get(col, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise AssertionError(
            f"FAIL-LOUD: malformed ledger metric {col!r}={raw!r} in bt_id {row.get('bt_id')!r}"
        )


# ── ledger integrity (FAIL-LOUD on missing/malformed baseline) ────────────────


def test_cloud_ground_truth_row_present_and_wellformed() -> None:
    rows = _read_ledger_rows()
    cloud = _find_row(rows, "cloud")
    # the recorded value must match the pinned ground truth (guards a silent ledger edit)
    assert abs(_num(cloud, "sharpe") - _CLOUD_GT["sharpe"]) < 1e-6, (
        f"cloud GT Sharpe drifted in ledger: {cloud.get('sharpe')} != {_CLOUD_GT['sharpe']}"
    )
    assert abs(_num(cloud, "ret_pct") - _CLOUD_GT["ret_pct"]) < 1e-6
    assert int(_num(cloud, "orders")) == _CLOUD_GT["orders"]
    # provenance must be pinned (the schema rule)
    for col in ("config_hash", "data_fingerprint", "commit"):
        assert cloud.get(col), f"cloud row missing provenance pin {col!r}"


def test_local_row_present_and_wellformed() -> None:
    rows = _read_ledger_rows()
    local = _find_row(rows, "local")
    # local must be a real result, not a placeholder
    assert _num(local, "orders") > 0, "FAIL-LOUD: local baseline row has 0 orders (mirage)"
    for col in ("config_hash", "data_fingerprint", "commit"):
        assert local.get(col), f"local row missing provenance pin {col!r}"


# ── the parity band guard (the re-break detector) ─────────────────────────────


def test_local_within_documented_band_of_cloud_ground_truth() -> None:
    rows = _read_ledger_rows()
    cloud, local = _find_row(rows, "cloud"), _find_row(rows, "local")

    d_sharpe = abs(_num(local, "sharpe") - _num(cloud, "sharpe"))
    d_ret = abs(_num(local, "ret_pct") - _num(cloud, "ret_pct"))
    c_orders = _num(cloud, "orders")
    d_orders_frac = abs(_num(local, "orders") - c_orders) / c_orders if c_orders else 1.0

    assert d_sharpe <= _BAND_SHARPE, (
        f"PARITY RE-BREAK: |Δ Sharpe| {d_sharpe:.3f} > band {_BAND_SHARPE} "
        f"(local {local.get('sharpe')} vs cloud GT {cloud.get('sharpe')}) — "
        f"local drifted from cloud truth; investigate before trusting local"
    )
    assert d_ret <= _BAND_RETURN_PP, (
        f"PARITY RE-BREAK: |Δ return| {d_ret:.2f}pp > band {_BAND_RETURN_PP}pp "
        f"(local {local.get('ret_pct')}% vs cloud {cloud.get('ret_pct')}%)"
    )
    assert d_orders_frac <= _BAND_ORDER_FRAC, (
        f"PARITY RE-BREAK: order count |Δ| {d_orders_frac:.0%} > band {_BAND_ORDER_FRAC:.0%} "
        f"(local {local.get('orders')} vs cloud {cloud.get('orders')}) — a large order-count "
        f"divergence is the warmup-mirage fingerprint (local ~75 orders pre-#259)"
    )


# ── the 0-trade mirage guard, against the REAL on-disk local BT (when present) ─


def _latest_local_bt_events() -> Path | None:
    cands = sorted(
        glob.glob(str(_ROOT / "algorithm" / "v2_champion_asis" / "backtests" / "*" / "*-order-events.json"))
    )
    return Path(cands[-1]) if cands else None


def test_local_bt_is_not_a_zero_trade_mirage() -> None:
    """Real-data guard: if a local full-FY BT artifact is present, it MUST have produced trades.
    A 0-trade (or near-0) full-FY result is the empty-warmup mirage (#173) — FAIL LOUD.
    SKIPS only when no local BT artifact exists in the worktree (the heavy BT is run out-of-band);
    it NEVER passes silently on a zero-trade artifact."""
    ev = _latest_local_bt_events()
    if ev is None:
        pytest.skip("no local BT order-events in worktree (heavy BT run out-of-band)")
    data = json.loads(ev.read_text())
    filled = [e for e in data if e.get("status") == "filled"]
    symbols = {str(e.get("symbolValue", "")).upper() for e in filled if e.get("symbolValue")}
    # the mirage produced ~75 orders / 37 symbols, almost all SPY, nothing till October.
    # post-#259 the floor is far higher; assert WELL above the mirage ceiling.
    assert len(filled) >= 150, (
        f"MIRAGE GUARD: only {len(filled)} filled events in {ev.name} over full-FY — "
        f"empty-warmup mirage fingerprint (pre-#259 was ~72). Warmup coarse likely re-broke."
    )
    assert len(symbols) >= 60, (
        f"MIRAGE GUARD: only {len(symbols)} traded symbols (pre-#259 mirage was 37) — "
        f"universe breadth collapsed; warmup subscription likely empty."
    )
