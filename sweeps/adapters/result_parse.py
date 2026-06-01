"""Shared LEAN/QC result parsing (#214 adapters) — ONE parse path, local + cloud.

Single-code-path discipline (CONVENTIONS §Parity): local `lean backtest` writes a result
JSON and cloud `/backtests/read` returns a `statistics` block — BOTH use the SAME QC
statistics key names (`Sharpe Ratio` / `Net Profit` / `Drawdown` / `Total Orders`) and the
SAME `totalPerformance.closedTrades` / `charts["Strategy Equity"].series["Return"]` shapes.
So both adapters parse through THIS module rather than each rolling its own — the parser is
the single source of truth for "QC stats block -> RunResult".

Fail-loud contract (CLAUDE.md data-integrity): NaN/inf metrics or an empty-orders run
(the empty-warmup-coarse +3.9% artifact) are DEGRADED, not banked. The parser flags
degraded; the adapter decides to RAISE (it never returns a mirage into the scoring path).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sweeps.types import ResultMetrics, ResultParseError, RunResult, TradeRecord


def _to_float(raw: Any, *, field: str) -> float:
    """Coerce a QC stat value to float. Strips `%` and thousands `,`. Raises on garbage.

    QC stats arrive as strings ("1.442", "39.4%", "1,234") OR numbers. A None/missing or
    unparseable value is NOT silently zeroed — that masks a degraded run."""
    if raw is None:
        raise ResultParseError(f"missing stat '{field}' — cannot bank a None as a metric")
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("%", "").replace(",", "").strip()
    if s == "":
        raise ResultParseError(f"empty stat '{field}'")
    try:
        return float(s)
    except ValueError as exc:
        raise ResultParseError(f"unparseable stat '{field}'={raw!r}") from exc


def _to_int(raw: Any, *, field: str) -> int:
    return int(round(_to_float(raw, field=field)))


def parse_metrics(statistics: Mapping[str, Any]) -> ResultMetrics:
    """QC `statistics` block -> the metrics trio + order count.

    Keys are the canonical QC names (identical local + cloud). Raises ResultParseError on a
    missing/unparseable mandatory field — never a silent zero (MEMORY result-table-format:
    Sharpe + Ret% + DD% mandatory)."""
    sharpe = _to_float(statistics.get("Sharpe Ratio"), field="Sharpe Ratio")
    ret_pct = _to_float(statistics.get("Net Profit"), field="Net Profit")
    dd_pct = _to_float(statistics.get("Drawdown"), field="Drawdown")
    orders = _to_int(statistics.get("Total Orders"), field="Total Orders")
    for name, val in (("Sharpe Ratio", sharpe), ("Net Profit", ret_pct), ("Drawdown", dd_pct)):
        if not math.isfinite(val):
            raise ResultParseError(f"non-finite stat '{name}'={val} — degraded, not a result")
    return ResultMetrics(sharpe=sharpe, ret_pct=ret_pct, dd_pct=dd_pct, orders=orders)


def _trade_dt(raw: Any) -> datetime:
    """Parse a LEAN closed-trade timestamp (ISO 8601, possibly with trailing 'Z')."""
    if isinstance(raw, datetime):
        return raw
    s = str(raw).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def parse_trades(total_performance: Mapping[str, Any]) -> tuple[TradeRecord, ...]:
    """`totalPerformance.closedTrades` -> the per-trade series the DSR/PBO objective consumes.

    LEAN closed-trade fields: `symbol` (a dict with `value`, or a string), `entryTime`,
    `exitTime`, `profitLoss` (net of fees). Per-trade return is profitLoss / entry notional
    (`entryPrice * |quantity|`); if notional is missing/zero, ret falls back to 0.0 (the
    objective layer keys off pnl for concentration; ret is the returns-series proxy)."""
    closed = total_performance.get("closedTrades") or []
    out: list[TradeRecord] = []
    for t in closed:
        sym = t.get("symbol")
        symbol = str(sym.get("value")) if isinstance(sym, Mapping) else str(sym)
        pnl = _to_float(t.get("profitLoss"), field="profitLoss")
        entry_price = float(t.get("entryPrice") or 0.0)
        qty = abs(float(t.get("quantity") or 0.0))
        notional = entry_price * qty
        ret = pnl / notional if notional else 0.0
        out.append(
            TradeRecord(
                symbol=symbol,
                entry_dt=_trade_dt(t.get("entryTime")),
                exit_dt=_trade_dt(t.get("exitTime")),
                pnl=pnl,
                ret=ret,
            )
        )
    return tuple(out)


def parse_daily_returns(charts: Mapping[str, Any]) -> tuple[float, ...]:
    """`charts["Strategy Equity"].series["Return"].values` -> the per-period return series.

    LEAN emits the equity Return series as `[[unix_time, value], ...]`. Used for DSR/CPCV
    (B.1/B.3). Returns an empty tuple if the series is absent (a run with no equity curve is
    handled by the degraded check, not here)."""
    eq = (charts.get("Strategy Equity") or {})
    series = eq.get("series") or eq.get("Series") or {}
    if isinstance(series, Mapping):
        ret = series.get("Return") or {}
    else:  # series-as-list fallback
        ret = next((s for s in series if s.get("name") == "Return"), {})
    values: Sequence[Any] = ret.get("values") or ret.get("Values") or []
    out: list[float] = []
    for v in values:
        if isinstance(v, (list, tuple)) and len(v) >= 2:
            out.append(float(v[1]))
        elif isinstance(v, Mapping):
            out.append(float(v.get("y", 0.0)))
    return tuple(out)


def parse_run_result(result: Mapping[str, Any]) -> RunResult:
    """A full LEAN/cloud result document -> RunResult (metrics + trades + daily returns).

    `is_degraded` is set when orders == 0 (the empty-warmup-coarse artifact — the engine
    silently no-op'd). The ADAPTER, not the parser, decides to RAISE on degraded — the
    parser only classifies (so a legitimately-flat config CAN be inspected if ever needed).
    """
    statistics = result.get("statistics") or result.get("Statistics") or {}
    if not statistics:
        raise ResultParseError("result has no 'statistics' block — not a parseable backtest")
    metrics = parse_metrics(statistics)
    trades = parse_trades(result.get("totalPerformance") or {})
    daily_returns = parse_daily_returns(result.get("charts") or {})
    is_degraded = metrics.orders <= 0
    return RunResult(
        metrics=metrics,
        trades=trades,
        daily_returns=daily_returns,
        is_degraded=is_degraded,
    )
