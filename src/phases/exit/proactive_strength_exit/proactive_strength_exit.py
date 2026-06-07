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
    REQUIRES_UPSTREAM = ["position_path"]
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        target_pct: float = 0.06
        min_peak_pct: float = 0.05
        giveback_from_peak_pct: float = 0.025
        require_still_bullish: bool = True
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
            if not getattr(holding, "invested", False) or qc.transactions.get_open_orders(symbol):
                continue
            if self._already_exiting(ctx, getattr(symbol, "value", str(symbol))):
                continue
            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            if entry_price <= 0.0:
                continue
            close = self._close(qc, symbol)
            if close <= 0.0:
                continue

            path = getattr(qc, "_position_path", {}).get(symbol)
            if path is None:
                raise DegradedDataError(
                    f"proactive strength exit requires PositionPathTracker state: "
                    f"symbol={symbol.value!r} date={date_str} missing qc._position_path entry"
                )
            peak = max(float(path.get("peak_price", entry_price)), close, entry_price)
            pnl_pct = close / entry_price - 1.0
            peak_pct = float(path.get("mfe_pct", peak / entry_price - 1.0))
            giveback_pct = peak_pct - pnl_pct

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
                    qty=-holding.quantity,
                    price=close,
                    stop=peak,
                    module="exit.proactive_strength_exit",
                    risk_dollars=0.0,
                    order_type="market",
                )
            )
            exits_logged.append(
                f"PROACTIVE_STRENGTH_EXIT|{date_str}|{symbol.value}|reason={reason}"
                f"|pnl={pnl_pct:.4f}|peak={peak_pct:.4f}|giveback={giveback_pct:.4f}"
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
        return "proactive_strength_exit_v1"
