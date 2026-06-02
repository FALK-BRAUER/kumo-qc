"""End-to-end sweep RUNNER (#214 / #320-C) — the missing orchestrator that fires the pipeline.

The sweep components (enumerate, pool, aggregate, score, gates, leaderboard, provenance) were all
built + unit-tested individually, but nothing CHAINED them into a runnable sweep that produces a
leaderboard. This is that chain:

    configs ──run_pool(primitive)──▶ ConfigRun[]                 (one cloud/fake BT per config×window)
            ──aggregate──▶ AggregateResult ──score──▶ ScoredConfig   (the D5 composite)
            ──trade_count_gate + concentration_guard──▶ GateVerdicts (the robustness gates)
            ──build_leaderboard──▶ leaderboard.csv (trio + provenance)
            ──ledger_rows──▶ ledger.csv (every (config,window) fact pinned)

ADAPTER-AGNOSTIC: the run primitive is INJECTED. Tests inject a FAKE primitive returning canned
ResultMetrics (deterministic, zero cloud); the live sweep injects make_cloud_run(...).run_result
(REAL QC, assert_cloud_clean per run). The runner never imports an adapter — the caller chooses.

FAILURE ISOLATION (the pool itself propagates via executor.map; the runner adds isolation here):
the primitive is wrapped so a config whose BT raises (dirty cloud run / assert_cloud_clean failure /
parse error) is RECORDED as a failure and EXCLUDED from the leaderboard — it never corrupts the
other configs or silently enters the board with garbage metrics. Failures surface in
SweepOutcome.failures, never hidden.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Callable

from sweeps.aggregate import aggregate
from sweeps.enumerate import DEFAULT_DOF_BUDGET
from sweeps.leaderboard import LeaderboardRow, build_leaderboard, to_csv
from sweeps.objective.gates import (
    GateVerdict,
    WindowReturns,
    concentration_guard,
    trade_count_gate,
)
from sweeps.pool import DEFAULT_MAX_WORKERS, run_pool
from sweeps.provenance import LedgerRow, Provenance, ledger_rows
from sweeps.score import ScoredConfig, score
from sweeps.types import ConfigRun, ResultMetrics, SweepConfig, Window
from sweeps.windows import SIX_WINDOWS

# Sentinel: a config whose primitive raised. orders=-1 is impossible for a real run → the runner
# detects it post-pool and routes the config to failures (never to scoring/leaderboard).
_FAILED = ResultMetrics(sharpe=0.0, ret_pct=0.0, dd_pct=0.0, orders=-1)


@dataclass(frozen=True, slots=True)
class ConfigScorecard:
    """One config's full verdict: the D5 score (leaderboard payload) + the robustness gates."""

    config: SweepConfig
    scored: ScoredConfig
    trade_gate: GateVerdict
    concentration_gate: GateVerdict

    @property
    def gates_pass(self) -> bool:
        return self.trade_gate.passed and self.concentration_gate.passed


@dataclass(frozen=True, slots=True)
class SweepFailure:
    """A config excluded from the leaderboard because a backtest raised. Surfaced, never hidden."""

    config: SweepConfig
    error: str


@dataclass(frozen=True, slots=True)
class SweepOutcome:
    """The full sweep result: the ranked leaderboard, per-config scorecards (with gates), the
    pinned ledger, the leaderboard CSV, and any excluded failures."""

    leaderboard: list[LeaderboardRow]
    scorecards: list[ConfigScorecard]
    ledger: list[LedgerRow]
    leaderboard_csv: str
    failures: list[SweepFailure] = field(default_factory=list)


def _window_returns(
    run: ConfigRun, *, oos_window: str | None, stress_window: str | None
) -> list[WindowReturns]:
    """Map a ConfigRun's per-window metrics → the gates' WindowReturns evidence. ret is the
    window's Ret% as a fraction; n_trades is the fill count; OOS/stress windows are flagged by name."""
    return [
        WindowReturns(
            window=wr.window,
            n_trades=wr.metrics.orders,
            ret=wr.metrics.ret_pct / 100.0,
            is_oos=(wr.window.name == oos_window),
            is_stress=(wr.window.name == stress_window),
        )
        for wr in run.window_results
    ]


def _isolating(run_primitive: Callable[[SweepConfig, Window], ResultMetrics],
               failures: dict[str, str], retries: int = 1):
    """Wrap the injected primitive so a raised BT is recorded (by config_hash) + returns the
    _FAILED sentinel, instead of propagating through executor.map and killing the whole sweep.

    RETRY-ON-TRANSIENT (#333): a cell that raises is re-attempted up to `retries` extra times before
    being recorded a failure — a single transient death (e.g. a memory-pressure kill mid-warmup at
    higher concurrency) shouldn't void the cell AND (via run_sweep's per-config exclusion) the whole
    config + the long run. Only a cell that fails EVERY attempt is recorded."""

    def wrapped(config: SweepConfig, window: Window) -> ResultMetrics:
        last: Exception | None = None
        for _ in range(retries + 1):
            try:
                return run_primitive(config, window)
            except Exception as exc:  # dirty run / assert_cloud_clean / parse error / transient kill
                last = exc
        failures.setdefault(config.config_hash, f"{type(last).__name__}: {last} (after {retries + 1} attempts)")
        return _FAILED

    return wrapped


def run_sweep(
    configs: Sequence[SweepConfig],
    run_primitive: Callable[[SweepConfig, Window], ResultMetrics],
    *,
    windows: Sequence[Window] = SIX_WINDOWS,
    oos_window: str | None = None,
    stress_window: str | None = None,
    dof_budget: int = DEFAULT_DOF_BUDGET,
    max_workers: int = DEFAULT_MAX_WORKERS,
    pins: tuple[str, str, str] | None = None,
    retries: int = 1,
) -> SweepOutcome:
    """Fire the full sweep: every config over every window via the injected primitive, scored +
    gated + ranked into a leaderboard, with the per-(config,window) ledger pinned to provenance.

    `run_primitive(config, window) -> ResultMetrics` is the injected backtest (fake in tests, the
    cloud adapter's run_result in production). A config whose primitive raises is isolated to
    SweepOutcome.failures and excluded from the leaderboard (never silent-garbage into the board).

    `pins` = the shared provenance triple-minus-config: (commit, data_fingerprint, marker). The
    runner builds a PER-CONFIG Provenance (filling each config's own config_hash) so every ledger
    row is fully pinned (the charter: no result without commit+config-hash+data-fingerprint). None
    skips the ledger (e.g. a dry scoring pass).
    """
    failed: dict[str, str] = {}
    config_runs = run_pool(
        list(configs), _isolating(run_primitive, failed, retries=retries), windows=windows, max_workers=max_workers
    )

    # Partition: a config with ANY _FAILED window (orders==-1) is excluded from scoring.
    clean: list[ConfigRun] = []
    failures: list[SweepFailure] = []
    for cr in config_runs:
        if any(wr.metrics.orders < 0 for wr in cr.window_results):
            failures.append(SweepFailure(
                config=cr.config,
                error=failed.get(cr.config.config_hash, "backtest failed (sentinel, no recorded error)"),
            ))
            continue
        clean.append(cr)

    scorecards: list[ConfigScorecard] = []
    scored_list: list[ScoredConfig] = []
    ledger: list[LedgerRow] = []
    for cr in clean:
        agg = aggregate(cr)
        sc = score(agg, dof_budget=dof_budget)
        scored_list.append(sc)
        wrs = _window_returns(cr, oos_window=oos_window, stress_window=stress_window)
        scorecards.append(ConfigScorecard(
            config=cr.config, scored=sc,
            trade_gate=trade_count_gate(wrs), concentration_gate=concentration_guard(wrs),
        ))
        if pins is not None:
            commit, data_fingerprint, marker = pins
            prov = Provenance(
                commit=commit, config_hash=cr.config.config_hash,
                data_fingerprint=data_fingerprint, marker=marker,
            )
            ledger.extend(ledger_rows(cr, prov, bt_id=cr.config.config_hash))

    leaderboard = build_leaderboard(scored_list)
    return SweepOutcome(
        leaderboard=leaderboard,
        scorecards=scorecards,
        ledger=ledger,
        leaderboard_csv=to_csv(leaderboard),
        failures=failures,
    )
