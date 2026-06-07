"""Exit phase: ScratchFlatExit (#407).

George-style loser management scratches stalled trades near flat before the structural Kijun/cloud
break. The phase consumes the `position_path` downstream contract so it can detect no-progress and
round-trip-to-flat patterns without owning the path state itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext


class ScratchFlatExit(BasePhase):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM = ["position_path"]
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        no_progress_days: int = 3
        min_mfe_pct: float = 0.02
        scratch_band_pct: float = 0.005
        max_loss_after_mfe_pct: float = 0.02
        enabled: bool = True

    def __init__(self, params: "ScratchFlatExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        exits_logged: list[str] = []
        no_progress_count = 0
        roundtrip_count = 0
        capped_loss_count = 0

        for symbol, holding in list(qc.portfolio.items()):
            if not getattr(holding, "invested", False) or qc.transactions.get_open_orders(symbol):
                continue
            if self._already_exiting(ctx, getattr(symbol, "value", str(symbol))):
                continue
            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            entry_date = meta.get("entry_date")
            if entry_price <= 0.0 or not isinstance(entry_date, datetime):
                continue
            close = self._close(qc, symbol)
            if close <= 0.0:
                continue

            path = getattr(qc, "_position_path", {}).get(symbol)
            if path is None:
                raise DegradedDataError(
                    f"scratch-flat exit requires PositionPathTracker state: "
                    f"symbol={symbol.value!r} date={date_str} missing qc._position_path entry"
                )
            peak = max(float(path.get("peak_price", entry_price)), close, entry_price)
            pnl_pct = close / entry_price - 1.0
            peak_pct = float(path.get("mfe_pct", peak / entry_price - 1.0))
            mae_pct = float(path.get("mae_pct", min(close, entry_price) / entry_price - 1.0))
            days_held = int(path.get("days_held", max((ctx.time - entry_date).days, 0)))

            reason = ""
            if (
                days_held >= self.p.no_progress_days
                and peak_pct < self.p.min_mfe_pct
                and pnl_pct >= -self.p.max_loss_after_mfe_pct
            ):
                reason = "no_progress"
                no_progress_count += 1
            elif (
                peak_pct >= self.p.min_mfe_pct
                and abs(pnl_pct) <= self.p.scratch_band_pct
            ):
                reason = "roundtrip_flat"
                roundtrip_count += 1
            elif (
                peak_pct >= self.p.min_mfe_pct
                and pnl_pct <= -self.p.max_loss_after_mfe_pct
            ):
                reason = "loss_cap_after_mfe"
                capped_loss_count += 1
            if not reason:
                continue

            ctx.bar_state.exit_intents.append(
                OrderIntent(
                    ticker=symbol.value,
                    qty=-holding.quantity,
                    price=close,
                    stop=entry_price,
                    module="exit.scratch_flat_exit",
                    risk_dollars=0.0,
                    order_type="market",
                )
            )
            exits_logged.append(
                log_exit_event(
                    qc,
                    event="SCRATCH_FLAT_EXIT",
                    date=date_str,
                    symbol=symbol,
                    module="exit.scratch_flat_exit",
                    reason=reason,
                    quantity=float(holding.quantity),
                    entry_price=entry_price,
                    exit_price=close,
                    days_held=days_held,
                    mfe_pct=peak_pct,
                    mae_pct=mae_pct,
                    peak_return_pct=peak_pct,
                    giveback_from_peak_pct=peak_pct - pnl_pct,
                )
            )

        return PhaseResult(
            decision=exits_logged,
            blocked=False,
            reason=f"{len(exits_logged)} scratch-flat exits",
            facts={
                "exit_count": len(exits_logged),
                "no_progress_count": no_progress_count,
                "roundtrip_count": roundtrip_count,
                "capped_loss_count": capped_loss_count,
            },
            metrics={},
        )

    @staticmethod
    def _close(qc: Any, symbol: Any) -> float:
        sec = qc.securities[symbol]
        return float(getattr(sec, "close", getattr(sec, "price", 0.0)) or 0.0)

    @staticmethod
    def _already_exiting(ctx: PhaseContext, ticker: str) -> bool:
        return any(intent.ticker == ticker for intent in ctx.bar_state.exit_intents)

    @property
    def version_marker(self) -> str:
        return "scratch_flat_exit_v1"


def log_exit_event(
    qc: Any,
    *,
    event: str,
    date: str,
    symbol: Any,
    module: str,
    reason: str,
    quantity: float,
    entry_price: float,
    exit_price: float,
    days_held: int,
    mfe_pct: float,
    mae_pct: float,
    peak_return_pct: float,
    giveback_from_peak_pct: float,
) -> str:
    ticker = str(getattr(symbol, "value", symbol))
    pnl = (exit_price - entry_price) * quantity
    return_pct = exit_price / entry_price - 1.0 if entry_price > 0.0 else 0.0
    fields = {
        "event": event,
        "module": module,
        "reason": reason,
        "days_held": days_held,
        "qty": quantity,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": pnl,
        "return_pct": return_pct,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "peak_return_pct": peak_return_pct,
        "giveback_from_peak_pct": giveback_from_peak_pct,
    }
    line = f"EXIT_EVENT|{date}|{ticker}|" + "|".join(
        f"{key}={_format_value(value)}" for key, value in fields.items()
    )
    log = getattr(qc, "log", None) or getattr(qc, "Log", None)
    if callable(log):
        log(line)
    return line


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
