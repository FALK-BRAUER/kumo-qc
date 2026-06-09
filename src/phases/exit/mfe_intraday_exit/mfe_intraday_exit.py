"""Exit phase: MfeIntradayExit (#427).

Consumes the `position_path` contract from PositionPathTracker and exits winners on the same
intraday clock when a profit target or MFE giveback rule fires. The phase owns only the exit
decision; path state stays in the trail module and broker submission stays in the engine fire seam.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext
from phases.exit.proactive_strength_exit.proactive_strength_exit import log_exit_event


class MfeIntradayExit(BasePhase):
    PHASE_KIND = "exit_hard"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM = ["position_path"]
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        _HASH_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"diagnostic_log"})

        target_pct: float = 0.0
        min_mfe_pct: float = 0.06
        giveback_fraction: float = 0.40
        min_giveback_pct: float = 0.02
        min_exit_return_pct: float = 0.0
        min_hold_bars: int = 2
        use_session_path: bool = False
        diagnostic_log: bool = False
        enabled: bool = True

    def __init__(self, params: "MfeIntradayExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        exits_logged: list[str] = []
        target_count = 0
        giveback_count = 0
        diag = self._empty_diag()

        for symbol, holding in list(qc.portfolio.items()):
            diag["holdings_seen"] += 1
            if not self._is_invested(holding):
                continue
            diag["invested_seen"] += 1
            ticker = getattr(symbol, "value", str(symbol))
            if self._already_exiting(ctx, ticker):
                diag["skipped_already_exiting"] += 1
                continue

            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            if self._has_blocking_open_orders(qc, symbol, meta):
                diag["skipped_open_orders"] += 1
                continue
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            if entry_price <= 0.0:
                diag["skipped_missing_entry"] += 1
                continue

            path = getattr(qc, "_position_path", {}).get(symbol)
            if path is None:
                diag["skipped_missing_path"] += 1
                raise DegradedDataError(
                    f"MfeIntradayExit requires PositionPathTracker state: "
                    f"symbol={ticker!r} date={date_str} missing qc._position_path entry"
                )
            diag["paths_seen"] += 1

            bars_held = int(path.get("bars_held", 0) or 0)
            if bars_held < self.p.min_hold_bars:
                diag["skipped_min_hold"] += 1
                continue

            close = float(path.get("last_price", 0.0) or 0.0)
            if close <= 0.0:
                diag["skipped_nonpositive_close"] += 1
                continue

            mfe_pct = float(path.get("mfe_pct", max(close, entry_price) / entry_price - 1.0))
            mae_pct = float(path.get("mae_pct", min(close, entry_price) / entry_price - 1.0))
            current_return_pct = float(path.get("current_return_pct", close / entry_price - 1.0))
            giveback_pct = float(path.get("giveback_pct", max(mfe_pct - current_return_pct, 0.0)))
            source_mfe_pct = mfe_pct
            source_giveback_pct = giveback_pct
            if self.p.use_session_path:
                source_mfe_pct = float(path.get("session_mfe_pct", source_mfe_pct))
                source_giveback_pct = float(path.get("session_giveback_pct", source_giveback_pct))
            self._update_diag_max(diag, ticker, current_return_pct, source_mfe_pct, source_giveback_pct)

            reason = ""
            if self.p.target_pct > 0.0 and current_return_pct >= self.p.target_pct:
                reason = "target"
                target_count += 1
            else:
                giveback_trigger = max(self.p.min_giveback_pct, source_mfe_pct * self.p.giveback_fraction)
                if (
                    source_mfe_pct >= self.p.min_mfe_pct
                    and source_giveback_pct >= giveback_trigger
                    and current_return_pct >= self.p.min_exit_return_pct
                ):
                    reason = "mfe_giveback"
                    giveback_count += 1
            if not reason:
                continue

            ctx.bar_state.exit_intents.append(
                OrderIntent(
                    ticker=ticker,
                    qty=-self._quantity(holding),
                    price=close,
                    stop=float(path.get("peak_price", close) or close),
                    module="exit.mfe_intraday_exit",
                    risk_dollars=0.0,
                    order_type="market",
                )
            )
            exits_logged.append(
                log_exit_event(
                    qc,
                    event="MFE_INTRADAY_EXIT",
                    date=date_str,
                    symbol=symbol,
                    module="exit.mfe_intraday_exit",
                    reason=reason,
                    quantity=self._quantity(holding),
                    entry_price=entry_price,
                    exit_price=close,
                    days_held=int(path.get("days_held", 0) or 0),
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    peak_return_pct=mfe_pct,
                    giveback_from_peak_pct=giveback_pct,
                )
            )

        facts = {
            "exit_count": len(exits_logged),
            "target_count": target_count,
            "giveback_count": giveback_count,
        }
        if self.p.diagnostic_log:
            self._record_diagnostic(qc, date_str, diag)
            facts.update(diag)
        return PhaseResult(
            decision=exits_logged,
            blocked=False,
            reason=f"{len(exits_logged)} MFE intraday exits",
            facts=facts,
            metrics={},
        )

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

    @staticmethod
    def _empty_diag() -> dict[str, Any]:
        return {
            "holdings_seen": 0,
            "invested_seen": 0,
            "paths_seen": 0,
            "skipped_open_orders": 0,
            "skipped_already_exiting": 0,
            "skipped_missing_entry": 0,
            "skipped_missing_path": 0,
            "skipped_min_hold": 0,
            "skipped_nonpositive_close": 0,
            "max_current_return_pct": None,
            "max_current_return_symbol": "",
            "max_mfe_pct": None,
            "max_mfe_symbol": "",
            "max_giveback_pct": None,
            "max_giveback_symbol": "",
        }

    @staticmethod
    def _update_diag_max(
        diag: dict[str, Any],
        ticker: str,
        current_return_pct: float,
        mfe_pct: float,
        giveback_pct: float,
    ) -> None:
        for key, symbol_key, value in (
            ("max_current_return_pct", "max_current_return_symbol", current_return_pct),
            ("max_mfe_pct", "max_mfe_symbol", mfe_pct),
            ("max_giveback_pct", "max_giveback_symbol", giveback_pct),
        ):
            prior = diag[key]
            if prior is None or value > float(prior):
                diag[key] = value
                diag[symbol_key] = ticker

    @staticmethod
    def _record_diagnostic(qc: Any, date_str: str, diag: dict[str, Any]) -> None:
        if diag["invested_seen"] <= 0 and diag["paths_seen"] <= 0:
            return
        state = getattr(qc, "_mfe_intraday_diag", None)
        if state is None:
            state = {
                "last_log_date": "",
                "max_current_return_pct": None,
                "max_current_return_symbol": "",
                "max_mfe_pct": None,
                "max_mfe_symbol": "",
                "max_giveback_pct": None,
                "max_giveback_symbol": "",
                "skipped_open_orders": 0,
                "skipped_already_exiting": 0,
                "skipped_missing_entry": 0,
                "skipped_missing_path": 0,
                "skipped_min_hold": 0,
                "skipped_nonpositive_close": 0,
            }
            qc._mfe_intraday_diag = state

        for key in (
            "skipped_open_orders",
            "skipped_already_exiting",
            "skipped_missing_entry",
            "skipped_missing_path",
            "skipped_min_hold",
            "skipped_nonpositive_close",
        ):
            state[key] += int(diag[key])
        for key, symbol_key in (
            ("max_current_return_pct", "max_current_return_symbol"),
            ("max_mfe_pct", "max_mfe_symbol"),
            ("max_giveback_pct", "max_giveback_symbol"),
        ):
            value = diag[key]
            if value is not None and (state[key] is None or float(value) > float(state[key])):
                state[key] = value
                state[symbol_key] = diag[symbol_key]

        if state["last_log_date"] == date_str:
            return
        state["last_log_date"] = date_str
        log = getattr(qc, "log", None)
        if not callable(log):
            return

        def fmt(value: Any) -> str:
            return "NA" if value is None else f"{float(value):.6f}"

        log(
            "MFE_DIAG_COUNTS|"
            f"{date_str}|h={diag['holdings_seen']}|i={diag['invested_seen']}|p={diag['paths_seen']}|"
            f"so={state['skipped_open_orders']}|sa={state['skipped_already_exiting']}|"
            f"se={state['skipped_missing_entry']}|sp={state['skipped_missing_path']}|"
            f"sh={state['skipped_min_hold']}|sc={state['skipped_nonpositive_close']}"
        )
        log(
            "MFE_DIAG_MAX|"
            f"{date_str}|r={fmt(state['max_current_return_pct'])}|rs={state['max_current_return_symbol']}|"
            f"m={fmt(state['max_mfe_pct'])}|ms={state['max_mfe_symbol']}|"
            f"g={fmt(state['max_giveback_pct'])}|gs={state['max_giveback_symbol']}"
        )

    @property
    def version_marker(self) -> str:
        return "mfe_intraday_exit_v1"
