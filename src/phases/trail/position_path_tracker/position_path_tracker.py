"""Trail phase: PositionPathTracker.

Maintains per-position path state for downstream exit modules: peak/trough prices, MFE/MAE percent,
and days held. It is deliberately a `trail` phase because trail runs before `exit_hard` in the engine
order, and it advertises the named `position_path` contract through PROVIDES_DOWNSTREAM so exits can
fail at init if the tracker is missing or misordered.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class PositionPathTracker(BasePhase):
    PHASE_KIND = "trail"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["position_path"]

    @dataclass(slots=True)
    class Params:
        use_bar_high_low: bool = True
        enabled: bool = True

    def __init__(self, params: "PositionPathTracker.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        paths = self._paths(qc)
        active_symbols = set()
        updated = 0

        for symbol, holding in list(qc.portfolio.items()):
            if not getattr(holding, "invested", False):
                paths.pop(symbol, None)
                continue
            active_symbols.add(symbol)
            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            entry_date = meta.get("entry_date")
            if entry_price <= 0.0:
                continue

            low, high, close = self._low_high_close(ctx, symbol)
            if close <= 0.0:
                continue

            prior = paths.get(symbol, {})
            peak_price = max(float(prior.get("peak_price", entry_price)), high, close, entry_price)
            trough_price = min(float(prior.get("trough_price", entry_price)), low, close, entry_price)
            days_held = (ctx.time - entry_date).days if isinstance(entry_date, datetime) else 0
            paths[symbol] = {
                "entry_price": entry_price,
                "entry_date": entry_date,
                "peak_price": peak_price,
                "trough_price": trough_price,
                "last_price": close,
                "mfe_pct": peak_price / entry_price - 1.0,
                "mae_pct": trough_price / entry_price - 1.0,
                "days_held": max(days_held, 0),
                "updated": ctx.time,
            }
            updated += 1

        for symbol in list(paths):
            if symbol not in active_symbols:
                paths.pop(symbol, None)

        return PhaseResult(
            decision=[],
            blocked=False,
            reason=f"position paths updated: {updated}",
            facts={"updated": updated, "tracked": len(paths)},
            metrics={},
        )

    @staticmethod
    def _paths(qc: Any) -> dict[Any, dict[str, Any]]:
        paths = getattr(qc, "_position_path", None)
        if paths is None:
            paths = {}
            qc._position_path = paths
        return paths

    def _low_high_close(self, ctx: PhaseContext, symbol: Any) -> tuple[float, float, float]:
        sec = ctx.qc.securities[symbol]
        close = float(getattr(sec, "close", getattr(sec, "price", 0.0)) or 0.0)
        high = close
        low = close
        if self.p.use_bar_high_low:
            bar = self._bar(ctx.data, symbol)
            high = float(getattr(bar, "high", getattr(bar, "High", high)) or high) if bar is not None else high
            low = float(getattr(bar, "low", getattr(bar, "Low", low)) or low) if bar is not None else low
            close = float(getattr(bar, "close", getattr(bar, "Close", close)) or close) if bar is not None else close
        high = max(high, close)
        low = min(low, close)
        return low, high, close

    @staticmethod
    def _bar(data: Any, symbol: Any) -> Any:
        if data is None:
            return None
        try:
            if hasattr(data, "contains_key") and data.contains_key(symbol):
                return data[symbol]
            return data[symbol]
        except (KeyError, TypeError, AttributeError):
            return None

    @property
    def version_marker(self) -> str:
        return "position_path_tracker_v1"
