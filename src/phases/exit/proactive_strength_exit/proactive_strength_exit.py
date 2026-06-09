"""Exit phase: ProactiveStrengthExit (#406).

George-style management sells winners into strength before the Kijun/cloud structure breaks. This
phase tracks each held position's peak since entry in runtime memory and emits a market exit when a
profit target is reached while the daily structure is still bullish, or when a profitable trade gives
back from its peak but remains above the structural break.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext


class ProactiveStrengthExit(BasePhase):
    PHASE_KIND = "exit_hard"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["position_path"]
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        target_pct: float = 0.06
        min_peak_pct: float = 0.05
        giveback_from_peak_pct: float = 0.025
        require_still_bullish: bool = True
        min_hold_days: int = 0
        enabled: bool = True

    def __init__(self, params: "ProactiveStrengthExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        exits_logged: list[str] = []
        target_count = 0
        giveback_count = 0

        for symbol, holding in list(qc.portfolio.items()):
            if not self._is_invested(holding):
                continue
            if self._already_exiting(ctx, getattr(symbol, "value", str(symbol))):
                continue
            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            if self._has_blocking_open_orders(qc, symbol, meta):
                continue
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            if entry_price <= 0.0:
                continue

            path = getattr(qc, "_position_path", {}).get(symbol)
            if path is None:
                raise DegradedDataError(
                    f"proactive strength exit requires PositionPathTracker state: "
                    f"symbol={symbol.value!r} date={date_str} missing qc._position_path entry"
                )
            close = float(path.get("last_price", 0.0) or self._close(qc, symbol))
            if close <= 0.0:
                continue
            peak = max(float(path.get("peak_price", entry_price)), close, entry_price)
            pnl_pct = float(path.get("current_return_pct", close / entry_price - 1.0))
            peak_pct = float(path.get("mfe_pct", peak / entry_price - 1.0))
            mae_pct = float(path.get("mae_pct", min(close, entry_price) / entry_price - 1.0))
            giveback_pct = float(path.get("giveback_pct", peak_pct - pnl_pct))
            days_held = int(path.get("days_held", 0) or 0)

            if days_held < self.p.min_hold_days:
                continue

            if self.p.require_still_bullish and not self._still_bullish(qc, symbol, close):
                continue

            reason = ""
            if pnl_pct >= self.p.target_pct:
                reason = "target"
                target_count += 1
            elif peak_pct >= self.p.min_peak_pct and giveback_pct >= self.p.giveback_from_peak_pct:
                reason = "giveback"
                giveback_count += 1
            if not reason:
                continue

            ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value,
                        qty=-self._quantity(holding),
                        price=close,
                        stop=peak,
                    module="exit.proactive_strength_exit",
                    risk_dollars=0.0,
                    order_type="market",
                )
            )
            exits_logged.append(
                log_exit_event(
                    qc,
                    event="PROACTIVE_STRENGTH_EXIT",
                    date=date_str,
                    symbol=symbol,
                    module="exit.proactive_strength_exit",
                    reason=reason,
                    quantity=self._quantity(holding),
                    entry_price=entry_price,
                    exit_price=close,
                    days_held=days_held,
                    mfe_pct=peak_pct,
                    mae_pct=mae_pct,
                    peak_return_pct=peak_pct,
                    giveback_from_peak_pct=giveback_pct,
                )
            )

        return PhaseResult(
            decision=exits_logged,
            blocked=False,
            reason=f"{len(exits_logged)} proactive strength exits",
            facts={
                "exit_count": len(exits_logged),
                "target_count": target_count,
                "giveback_count": giveback_count,
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

    @staticmethod
    def _is_invested(holding: Any) -> bool:
        invested = getattr(holding, "invested", None)
        if invested is None:
            invested = getattr(holding, "Invested", False)
        return bool(invested)

    @staticmethod
    def _quantity(holding: Any) -> float:
        return float(getattr(holding, "quantity", getattr(holding, "Quantity", 0.0)) or 0.0)

    @classmethod
    def _has_blocking_open_orders(cls, qc: Any, symbol: Any, meta: dict[str, Any]) -> bool:
        orders = list(qc.transactions.get_open_orders(symbol))
        if not orders:
            return False
        protective_stop_id = cls._ticket_id(meta.get("protective_stop_ticket"))
        if protective_stop_id is None:
            return True
        return any(cls._order_id(order) != protective_stop_id for order in orders)

    @staticmethod
    def _ticket_id(ticket: Any) -> Any:
        return getattr(ticket, "order_id", getattr(ticket, "OrderId", None))

    @staticmethod
    def _order_id(order: Any) -> Any:
        return getattr(order, "id", getattr(order, "Id", getattr(order, "order_id", getattr(order, "OrderId", None))))

    @staticmethod
    def _still_bullish(qc: Any, symbol: Any, close: float) -> bool:
        ind = getattr(qc, "_indicators", {}).get(symbol)
        if ind is None:
            return False
        d_ichi = ind.get("d_ichi")
        if d_ichi is None or not getattr(d_ichi, "is_ready", False):
            return False
        try:
            tenkan = float(d_ichi.tenkan.current.value)
            kijun = float(d_ichi.kijun.current.value)
            senkou_a = float(d_ichi.senkou_a.current.value)
            senkou_b = float(d_ichi.senkou_b.current.value)
        except (AttributeError, TypeError, ValueError):
            return False
        return close > max(senkou_a, senkou_b) and close > kijun and tenkan > kijun

    @property
    def version_marker(self) -> str:
        return "proactive_strength_exit_v2"


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
