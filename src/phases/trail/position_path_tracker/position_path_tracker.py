"""Trail phase: PositionPathTracker.

Maintains per-position path state for downstream exit modules: peak/trough prices, MFE/MAE percent,
giveback, days/bars held, and current session range. It is deliberately a `trail` phase because trail
runs before `exit_hard` in the engine order, and it advertises the named `position_path` contract
through PROVIDES_DOWNSTREAM so exits can fail at init if the tracker is missing or misordered.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext


class PositionPathTracker(BasePhase):
    PHASE_KIND = "trail"
    PHASE_RESOLUTION = "intraday"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["position_path"]

    @dataclass(slots=True)
    class Params:
        use_bar_high_low: bool = True
        track_session_path: bool = True
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
            if not self._is_invested(holding):
                paths.pop(symbol, None)
                continue
            active_symbols.add(symbol)
            meta = getattr(qc, "_position_meta", {}).get(symbol, {})
            entry_price = float(meta.get("entry_price", 0.0) or 0.0)
            entry_date = meta.get("entry_date")
            if entry_price <= 0.0:
                continue

            open_, low, high, close = self._ohlc(ctx, symbol)
            if close <= 0.0:
                continue

            prior = paths.get(symbol, {})
            bars_held = int(prior.get("bars_held", 0) or 0) + 1
            peak_price = max(float(prior.get("peak_price", entry_price)), high, close, entry_price)
            trough_price = min(float(prior.get("trough_price", entry_price)), low, close, entry_price)
            days_held = (ctx.time - entry_date).days if isinstance(entry_date, datetime) else 0
            current_return_pct = close / entry_price - 1.0
            mfe_pct = peak_price / entry_price - 1.0
            mae_pct = trough_price / entry_price - 1.0
            session = self._session_path(prior, ctx, open_, high, low, close, entry_price)
            paths[symbol] = {
                "entry_price": entry_price,
                "entry_date": entry_date,
                "peak_price": peak_price,
                "trough_price": trough_price,
                "last_open": open_,
                "last_high": high,
                "last_low": low,
                "last_price": close,
                "current_return_pct": current_return_pct,
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "giveback_pct": max(mfe_pct - current_return_pct, 0.0),
                "days_held": max(days_held, 0),
                "bars_held": bars_held,
                "updated": ctx.time,
                **session,
            }
            updated += 1

        for symbol in list(paths):
            if symbol not in active_symbols:
                paths.pop(symbol, None)

        return PhaseResult(
            decision=[],
            blocked=False,
            reason="",
            facts={"tracked": len(paths)},
            metrics={},
        )

    @staticmethod
    def _paths(qc: Any) -> dict[Any, dict[str, Any]]:
        paths = getattr(qc, "_position_path", None)
        if paths is None:
            paths = {}
            qc._position_path = paths
        return paths

    @staticmethod
    def _is_invested(holding: Any) -> bool:
        invested = getattr(holding, "invested", None)
        if invested is None:
            invested = getattr(holding, "Invested", False)
        return bool(invested)

    def _ohlc(self, ctx: PhaseContext, symbol: Any) -> tuple[float, float, float, float]:
        sec = ctx.qc.securities[symbol]
        close = float(getattr(sec, "close", getattr(sec, "price", 0.0)) or 0.0)
        open_ = close
        low = close
        high = close
        if self.p.use_bar_high_low:
            bar = self._bar(ctx.data, symbol)
            open_ = float(getattr(bar, "open", getattr(bar, "Open", open_)) or open_) if bar is not None else open_
            high = float(getattr(bar, "high", getattr(bar, "High", high)) or high) if bar is not None else high
            low = float(getattr(bar, "low", getattr(bar, "Low", low)) or low) if bar is not None else low
            close = float(getattr(bar, "close", getattr(bar, "Close", close)) or close) if bar is not None else close
        high = max(high, close)
        low = min(low, close)
        return open_, low, high, close

    def _session_path(
        self,
        prior: dict[str, Any],
        ctx: PhaseContext,
        open_: float,
        high: float,
        low: float,
        close: float,
        entry_price: float,
    ) -> dict[str, Any]:
        if not self.p.track_session_path:
            return {}
        session_date = ctx.time.date()
        prior_date = prior.get("session_date")
        if prior_date != session_date:
            session_open = open_ if open_ > 0.0 else close
            session_high = max(high, close, session_open)
            session_low = min(low, close, session_open)
            session_bars = 1
        else:
            session_open = float(prior.get("session_open", open_ if open_ > 0.0 else close))
            session_high = max(float(prior.get("session_high", session_open)), high, close)
            session_low = min(float(prior.get("session_low", session_open)), low, close)
            session_bars = int(prior.get("session_bars", 0) or 0) + 1
        session_mfe_pct = session_high / entry_price - 1.0
        session_mae_pct = session_low / entry_price - 1.0
        current_return_pct = close / entry_price - 1.0
        return {
            "session_date": session_date,
            "session_open": session_open,
            "session_high": session_high,
            "session_low": session_low,
            "session_close": close,
            "session_bars": session_bars,
            "session_mfe_pct": session_mfe_pct,
            "session_mae_pct": session_mae_pct,
            "session_giveback_pct": max(session_mfe_pct - current_return_pct, 0.0),
        }

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
        return "position_path_tracker_v2"
