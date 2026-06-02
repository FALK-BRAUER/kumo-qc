"""Dummy-data tests for the end-to-end sweep RUNNER (#214/#320-C) — the harness proven on canned
data, ZERO cloud (HQ constraint). A fake primitive returns hand-engineered ResultMetrics so the
full chain (pool → aggregate → score → gates → leaderboard → ledger + failure-isolation) is
asserted with exact, hand-verifiable expectations BEFORE any live grid.
"""
from __future__ import annotations

import pytest

from sweeps.enumerate import enumerate_catalog
from sweeps.run_sweep import run_sweep
from sweeps.types import ResultMetrics, SweepConfig, Window
from sweeps.windows import SIX_WINDOWS
from tests.sweeps.conftest import MOCK_CATALOG, constant_runner, make_runner

GOOD = ResultMetrics(sharpe=1.2, ret_pct=12.0, dd_pct=8.0, orders=15)


def _uniform_table(configs, metrics):
    return {(c.config_hash, w.name): metrics for c in configs for w in SIX_WINDOWS}


# --- end-to-end: the machine FIRES, scores, ranks ---------------------------------------

def test_end_to_end_fires_and_ranks() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)  # type: ignore[arg-type]
    out = run_sweep(configs, constant_runner(GOOD), windows=SIX_WINDOWS)
    # one leaderboard row + one scorecard per config, no failures.
    assert len(out.leaderboard) == len(configs)
    assert len(out.scorecards) == len(configs)
    assert out.failures == []
    # ranks are 1..N, contiguous, sorted by composite DESC.
    ranks = [r.rank for r in out.leaderboard]
    assert ranks == list(range(1, len(configs) + 1))
    composites = [r.scored.composite for r in out.leaderboard]
    assert composites == sorted(composites, reverse=True)


def test_leaderboard_csv_has_metric_trio() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:3]  # type: ignore[arg-type]
    out = run_sweep(configs, constant_runner(GOOD))
    header = out.leaderboard_csv.splitlines()[0].lower()
    # the trio is mandatory on every row (MEMORY: result-table-format — never Sharpe alone).
    assert "sharpe" in header
    assert "ret" in header or "return" in header
    assert "dd" in header or "drawdown" in header


def test_better_config_ranks_first() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:2]  # type: ignore[arg-type]
    best, worst = configs[0], configs[1]
    table = {}
    for w in SIX_WINDOWS:
        table[(best.config_hash, w.name)] = ResultMetrics(2.0, 20.0, 5.0, 20)   # high, stable
        table[(worst.config_hash, w.name)] = ResultMetrics(0.3, 3.0, 12.0, 20)  # low
    out = run_sweep(configs, make_runner(table))
    assert out.leaderboard[0].scored.aggregate.config.config_hash == best.config_hash


# --- failure isolation: a raised BT is recorded, not fatal ------------------------------

def test_failure_isolation_excludes_not_corrupts() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:3]  # type: ignore[arg-type]
    bad = configs[1].config_hash

    def flaky(config: SweepConfig, window: Window) -> ResultMetrics:
        if config.config_hash == bad:
            raise RuntimeError("assert_cloud_clean: dirty run")
        return GOOD

    out = run_sweep(configs, flaky)
    # the bad config is recorded as a failure, EXCLUDED from the board; the other two survive.
    assert len(out.failures) == 1
    assert out.failures[0].config.config_hash == bad
    assert "dirty run" in out.failures[0].error
    assert len(out.leaderboard) == 2
    assert bad not in {r.scored.aggregate.config.config_hash for r in out.leaderboard}


# --- the gates: engineer dummy results to PASS and FAIL each ----------------------------

def test_trade_gate_fails_when_starved() -> None:
    [cfg] = enumerate_catalog(MOCK_CATALOG)[:1]  # type: ignore[arg-type]
    starved = ResultMetrics(sharpe=1.0, ret_pct=5.0, dd_pct=5.0, orders=5)  # 5×6=30 < 50 floor
    out = run_sweep([cfg], constant_runner(starved))
    sc = out.scorecards[0]
    assert sc.trade_gate.passed is False
    assert "trades" in (sc.trade_gate.reason or "")


def test_trade_gate_passes_when_ample() -> None:
    [cfg] = enumerate_catalog(MOCK_CATALOG)[:1]  # type: ignore[arg-type]
    out = run_sweep([cfg], constant_runner(GOOD))  # 15×6=90 ≥ 50, all ≥10
    assert out.scorecards[0].trade_gate.passed is True


def test_concentration_gate_fails_on_single_window_carry() -> None:
    [cfg] = enumerate_catalog(MOCK_CATALOG)[:1]  # type: ignore[arg-type]
    table = {}
    for i, w in enumerate(SIX_WINDOWS):
        # one window supplies ~all positive return (>60% share) → single-window-carried.
        ret = 70.0 if i == 0 else 0.0
        table[(cfg.config_hash, w.name)] = ResultMetrics(1.0, ret, 5.0, 15)
    out = run_sweep([cfg], make_runner(table))
    sc = out.scorecards[0]
    assert sc.concentration_gate.passed is False
    assert "concentration" in (sc.concentration_gate.reason or "")


def test_concentration_gate_fails_on_negative_oos() -> None:
    [cfg] = enumerate_catalog(MOCK_CATALOG)[:1]  # type: ignore[arg-type]
    oos = SIX_WINDOWS[5].name  # flag the last window OOS
    table = {}
    for i, w in enumerate(SIX_WINDOWS):
        ret = -3.0 if i == 5 else 5.0  # OOS window negative
        table[(cfg.config_hash, w.name)] = ResultMetrics(1.0, ret, 5.0, 15)
    out = run_sweep([cfg], make_runner(table), oos_window=oos)
    sc = out.scorecards[0]
    assert sc.concentration_gate.passed is False
    assert "OOS" in (sc.concentration_gate.reason or "")


def test_concentration_gate_passes_when_broad_and_positive() -> None:
    [cfg] = enumerate_catalog(MOCK_CATALOG)[:1]  # type: ignore[arg-type]
    # balanced positive across all windows → no single-window carry, no negatives.
    out = run_sweep([cfg], constant_runner(ResultMetrics(1.0, 6.0, 5.0, 15)))
    assert out.scorecards[0].concentration_gate.passed is True


# --- ledger pinning: every row carries the full provenance triple -----------------------

def test_ledger_rows_fully_pinned() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:2]  # type: ignore[arg-type]
    pins = ("abc1234commit", "data-fp-2025", "sweep-v1")
    out = run_sweep(configs, constant_runner(GOOD), pins=pins)
    # one ledger row per (config, window).
    assert len(out.ledger) == len(configs) * len(SIX_WINDOWS)
    for row in out.ledger:
        # the full pinning triple on every row (LedgerRow flattens the provenance fields).
        assert row.commit == "abc1234commit"
        assert row.data_fingerprint == "data-fp-2025"
        # config_hash filled per-config (asserted == the config's hash by ledger_rows).
        assert row.config_hash in {c.config_hash for c in configs}


def test_no_pins_skips_ledger() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:2]  # type: ignore[arg-type]
    out = run_sweep(configs, constant_runner(GOOD))  # pins=None
    assert out.ledger == []


# --- parsing / fail-loud: a missing metric raises in the primitive, isolated by the runner

def test_missing_metric_in_table_is_isolated() -> None:
    configs = enumerate_catalog(MOCK_CATALOG)[:2]  # type: ignore[arg-type]
    # table missing every cell for configs[1] → make_runner raises KeyError → isolated to failures.
    table = {(configs[0].config_hash, w.name): GOOD for w in SIX_WINDOWS}
    out = run_sweep(configs, make_runner(table))
    assert len(out.leaderboard) == 1
    assert len(out.failures) == 1
    assert out.failures[0].config.config_hash == configs[1].config_hash
