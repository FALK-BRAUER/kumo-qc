"""Exit phase: StaleMfeExit (#455).

Consumes the `position_path` contract and exits positions that have stopped making fresh MFE for a
configurable number of trading sessions. The same phase can also run a simple age-cap diagnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.exit.proactive_strength_exit.proactive_strength_exit import log_exit_event


class StaleMfeExit(BasePhase):
    PHASE_KIND = "exit_hard"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["position_path"]
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        stale_sessions: int = 20
        min_hold_sessions: int = 20
        min_mfe_pct: float = 0.04
        min_giveback_pct: float = 0.02
        min_exit_return_pct: float = -1.0
        max_exit_return_pct: float = 1.0
        max_hold_sessions: int = 0
        max_hold_return_pct: float = 1.0
        mfe_epsilon_pct: float = 0.0005
        enabled: bool = True

    def __init__(self, params: "StaleMfeExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        exits_logged: list[str] = []
        stale_count = 0
        age_count = 0
        state = self._state(qc)
        active_symbols = set()

        for symbol, holding in list(qc.portfolio.items()):
            if not self._is_invested(holding):
                continue
            active_symbols.add(symbol)
            ticker = getattr(symbol, "value", str(symbol))
            if self._already_exiting(ctx, ticker):
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
                    f"stale-MFE exit requires PositionPathTracker state: "
                    f"symbol={ticker!r} date={date_str} missing qc._position_path entry"
                )

            close = float(path.get("last_price", 0.0) or self._close(qc, symbol))
            if close <= 0.0:
                continue
            current_return_pct = float(path.get("current_return_pct", close / entry_price - 1.0))
            mfe_pct = float(path.get("mfe_pct", max(close, entry_price) / entry_price - 1.0))
            mae_pct = float(path.get("mae_pct", min(close, entry_price) / entry_price - 1.0))
            giveback_pct = float(path.get("giveback_pct", max(mfe_pct - current_return_pct, 0.0)))
            symbol_state = self._update_symbol_state(state, symbol, ctx.time.date(), mfe_pct)

            reason = ""
            if (
                self.p.max_hold_sessions > 0
                and symbol_state["sessions_held"] >= self.p.max_hold_sessions
                and current_return_pct <= self.p.max_hold_return_pct
            ):
                reason = "age_cap"
                age_count += 1
            elif (
                self.p.stale_sessions > 0
                and symbol_state["sessions_held"] >= self.p.min_hold_sessions
                and symbol_state["sessions_since_new_mfe"] >= self.p.stale_sessions
                and symbol_state["best_mfe_pct"] >= self.p.min_mfe_pct
                and giveback_pct >= self.p.min_giveback_pct
                and self.p.min_exit_return_pct <= current_return_pct <= self.p.max_exit_return_pct
            ):
                reason = "stale_mfe"
                stale_count += 1
            if not reason:
                continue

            ctx.bar_state.exit_intents.append(
                OrderIntent(
                    ticker=ticker,
                    qty=-self._quantity(holding),
                    price=close,
                    stop=float(path.get("peak_price", close) or close),
                    module="exit.stale_mfe_exit",
                    risk_dollars=0.0,
                    order_type="market",
                )
            )
            exits_logged.append(
                log_exit_event(
                    qc,
                    event="STALE_MFE_EXIT",
                    date=date_str,
                    symbol=symbol,
                    module="exit.stale_mfe_exit",
                    reason=reason,
                    quantity=self._quantity(holding),
                    entry_price=entry_price,
                    exit_price=close,
                    days_held=int(path.get("days_held", symbol_state["sessions_held"]) or 0),
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    peak_return_pct=symbol_state["best_mfe_pct"],
                    giveback_from_peak_pct=giveback_pct,
                )
            )

        for symbol in list(state):
            if symbol not in active_symbols:
                state.pop(symbol, None)

        return PhaseResult(
            decision=exits_logged,
            blocked=False,
            reason=f"{len(exits_logged)} stale-MFE exits",
            facts={
                "exit_count": len(exits_logged),
                "stale_count": stale_count,
                "age_count": age_count,
            },
            metrics={},
        )

    def _update_symbol_state(
        self,
        state: dict[Any, dict[str, Any]],
        symbol: Any,
        current_date: date,
        mfe_pct: float,
    ) -> dict[str, Any]:
        symbol_state = state.get(symbol)
        if symbol_state is None:
            symbol_state = {
                "last_seen_date": current_date,
                "sessions_held": 0,
                "sessions_since_new_mfe": 0,
                "best_mfe_pct": mfe_pct,
            }
            state[symbol] = symbol_state
            return symbol_state

        if symbol_state.get("last_seen_date") != current_date:
            symbol_state["sessions_held"] = int(symbol_state.get("sessions_held", 0) or 0) + 1
            symbol_state["sessions_since_new_mfe"] = (
                int(symbol_state.get("sessions_since_new_mfe", 0) or 0) + 1
            )
            symbol_state["last_seen_date"] = current_date

        if mfe_pct > float(symbol_state.get("best_mfe_pct", mfe_pct)) + self.p.mfe_epsilon_pct:
            symbol_state["best_mfe_pct"] = mfe_pct
            symbol_state["sessions_since_new_mfe"] = 0
        return symbol_state

    @staticmethod
    def _state(qc: Any) -> dict[Any, dict[str, Any]]:
        state = getattr(qc, "_stale_mfe_exit_state", None)
        if state is None:
            state = {}
            qc._stale_mfe_exit_state = state
        return state

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
    def _quantity(holding: Any) -> int:
        return int(getattr(holding, "quantity", getattr(holding, "Quantity", 0)) or 0)

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

    @property
    def version_marker(self) -> str:
        return "stale_mfe_exit_v1"
