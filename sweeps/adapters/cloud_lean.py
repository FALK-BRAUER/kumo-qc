"""`CloudLeanRun` (#214 A.6) — the real cloud run-a-config adapter (ground truth).

Cloud = ground truth, local = fast filter (CONVENTIONS §Parity). Every sweep WINNER goes
through a cloud BT gated on `assert_cloud_clean`. This adapter FORMALISES the raw poll loop
in `scripts/qc_v2_cloud.py` into a reusable, ASSERTED primitive behind the RunConfig seam.

`assert_cloud_clean` here RAISES `CloudValidationError` (the design A.6 contract) rather than
returning a (bool, reason) — the sweep driver wants fail-loud promotion gating. The CHECK is
identical to `scripts/qc_v2_cloud.assert_cloud_clean` (error is None AND progress == 1 AND
orders > 0), kept in lock-step so the sweep and the manual cloud driver agree on "clean".

Single parse path: the cloud `/backtests/read` statistics are parsed by the SAME
`result_parse` module the local adapter uses (the QC stat key names are identical).

Testability: the deploy/run/read cloud calls are INJECTED (`deploy`, `run_backtest`,
`read_backtest`). Unit tests pass MOCKS returning fixture cloud documents — ZERO real QC
spend, ZERO `qc_v2_cloud` import side effects (that module reads the keychain at import; the
adapter never imports it — the prod wiring passes its functions in from the call site).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sweeps.adapters.result_parse import parse_run_result
from sweeps.types import (
    CloudValidationError,
    ResultMetrics,
    RunResult,
    SweepConfig,
    TradeRecord,
    Window,
)


@dataclass(frozen=True, slots=True)
class CloudResult:
    """The cloud BT outcome (A.6). `raw` is the full `/backtests/read` document — parsed for
    metrics/trades through the shared parser only AFTER assert_cloud_clean passes."""

    backtest_id: str
    progress: float
    error: str | None
    raw: Mapping[str, Any] = field(default_factory=dict)


def _orders_value(raw: Mapping[str, Any]) -> Any:
    return (raw.get("statistics", {}) or {}).get("Total Orders")


def assert_cloud_clean(result: CloudResult) -> None:
    """The cloud-ground-truth gate (CONVENTIONS §Parity). RAISES CloudValidationError unless:

      1. error is None        — no runtime/wiring crash (the #318 completed-but-crashed trap;
                                a fail-loud like dv_rank_cap is a REAL fail, not a result).
      2. progress == 1.0      — ran end-to-end; a partial run is not a result.
      3. liveness: orders > 0 — a champion that decides daily must trade; 0/NaN/null orders ⇒
                                the engine silently no-op'd (the silent-zero-champion hole, #326).
      4. metrics finite       — no NaN/inf in the trio.

    Mirrors scripts/qc_v2_cloud.assert_cloud_clean's checks (kept in lock-step) but fail-loud."""
    if result.error:
        raise CloudValidationError(f"runtime error: {str(result.error)[:300]}")
    if result.progress != 1:
        raise CloudValidationError(f"incomplete: progress={result.progress}")
    raw_orders = _orders_value(result.raw)
    if raw_orders is None:
        raise CloudValidationError(
            "liveness UNVERIFIABLE: Total Orders is null — null != clean (would silently pass a "
            "0-entry champion); fail loud (#326/#277)"
        )
    try:
        n = int(str(raw_orders).replace(",", ""))
    except (ValueError, TypeError) as exc:
        raise CloudValidationError(
            f"liveness UNVERIFIABLE: unparseable Total Orders {raw_orders!r} — fail loud (#277)"
        ) from exc
    if n <= 0:
        raise CloudValidationError("liveness: 0 orders (override only if legitimately flat)")
    stats = result.raw.get("statistics", {}) or {}
    for key in ("Sharpe Ratio", "Net Profit", "Drawdown"):
        v = stats.get(key)
        if v is not None:
            try:
                fv = float(str(v).replace("%", "").replace(",", "").strip())
            except (ValueError, TypeError):
                continue
            if not math.isfinite(fv):
                raise CloudValidationError(f"non-finite metric '{key}'={v} — degraded, not clean")


# Injected cloud calls (prod wiring passes qc_v2_cloud's functions; tests pass mocks).
Deploy = Callable[[SweepConfig, Window], str]
"""Deploy the dist closure for `config`/`window` to the cloud project; return the compileId."""
RunBacktest = Callable[[str, str], CloudResult]
"""Submit + poll a cloud BT (name, compileId) -> CloudResult (raw read document + progress/error)."""


@dataclass(frozen=True, slots=True)
class CloudLeanRun:
    """The real cloud run-a-config primitive (ground truth). Integration-flagged; unit-tested
    against MOCKED cloud calls. Satisfies RunConfig (`__call__ -> ResultMetrics`) and
    RichRunConfig (`run_result -> RunResult`).

    `deploy` builds+deploys the config's closure and returns a compileId. `run_backtest`
    submits+polls and returns a CloudResult. `assert_cloud_clean` gates promotion: a winner
    that fails the cloud gate is DROPPED (raises), never promoted (local was a mirage)."""

    deploy: Deploy
    run_backtest: RunBacktest

    def _bt_name(self, config: SweepConfig, window: Window) -> str:
        return f"sweep-{config.config_hash}-{window.name}"

    def fetch(self, config: SweepConfig, window: Window) -> CloudResult:
        """Deploy + run + GATE. Returns the clean CloudResult or RAISES CloudValidationError.
        No positive-outcome claim on a dirty cloud run (the §Parity lesson)."""
        compile_id = self.deploy(config, window)
        result = self.run_backtest(self._bt_name(config, window), compile_id)
        assert_cloud_clean(result)  # raises on any miss — no unclean result is returned
        return result

    def run_result(self, config: SweepConfig, window: Window) -> RunResult:
        """The full cloud RunResult (gated). Parsed through the SAME parser as local."""
        result = self.fetch(config, window)
        return parse_run_result(result.raw)

    def __call__(self, config: SweepConfig, window: Window) -> ResultMetrics:
        """The RunConfig Protocol surface: the gated, leaderboard-facing metrics trio."""
        return self.run_result(config, window).metrics


def trades_from_cloud(result: CloudResult) -> tuple[TradeRecord, ...]:
    """Convenience: the per-trade series from a (clean) cloud result, via the shared parser."""
    return parse_run_result(result.raw).trades
