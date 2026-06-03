from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, PhaseResult
from context import PhaseContext


class VixPercentile(BasePhase):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        vix_percentile_enabled: bool = False
        vix_percentile_threshold: float = 75.0
        vix_percentile_lookback: int = 504
        enabled: bool = True

    def __init__(self, params: "VixPercentile.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        enabled = self.p.vix_percentile_enabled
        if not enabled:
            return PhaseResult(decision="skip", blocked=False, reason="vix_percentile disabled", facts={}, metrics={})

        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        threshold = self.p.vix_percentile_threshold
        lookback = self.p.vix_percentile_lookback
        vix = getattr(qc, "vix", None)

        if vix is None or not qc.securities.contains_key(vix):
            return PhaseResult(decision="skip", blocked=False, reason="VIX not in securities", facts={}, metrics={})

        try:
            from QuantConnect import Resolution
            vix_hist = qc.history(vix, lookback, Resolution.DAILY)
            if vix_hist is None or len(vix_hist) < int(lookback * 0.8):
                return PhaseResult(decision="skip", blocked=False, reason="insufficient VIX history", facts={}, metrics={})
            import pandas as pd
            if isinstance(vix_hist.index, pd.MultiIndex):
                vix_hist = vix_hist.droplevel(0)
            close_col = "close" if "close" in vix_hist.columns else "Close"
            vix_series = vix_hist[close_col].dropna()
            if len(vix_series) == 0:
                return PhaseResult(decision="skip", blocked=False, reason="empty VIX series", facts={}, metrics={})
            vix_now = float(qc.securities[vix].price)
            vix_pct = (vix_series < vix_now).mean() * 100.0
            blocked = vix_pct > threshold
            return PhaseResult(
                decision="block" if blocked else "pass",
                blocked=blocked,
                reason=f"VIX={vix_now:.2f} at {vix_pct:.1f}th pct (threshold={threshold})",
                facts={"vix": vix_now, "pct": vix_pct, "threshold": threshold, "date": date_str},
                metrics={},
            )
        except Exception:
            return PhaseResult(decision="skip", blocked=False, reason="VIX percentile error", facts={}, metrics={})

    @property
    def version_marker(self) -> str:
        return "vix_percentile_v1"
