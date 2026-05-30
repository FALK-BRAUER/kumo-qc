"""
Regime phase: E28 VIX percentile gate.
Blocks entries when VIX is in top X% of 2-year distribution.
Default OFF (vix_percentile_enabled=False). Faithful carve of oracle L482-499.
"""
from __future__ import annotations
from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext


class VixPercentile(PhaseInterface):
    PHASE_KIND = "regime"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = []

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        enabled = self._params.get("vix_percentile_enabled", False)
        if not enabled:
            return PhaseResult(decision="skip", blocked=False, reason="vix_percentile disabled", facts={}, metrics={})

        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        threshold = self._params.get("vix_percentile_threshold", 75.0)
        lookback = self._params.get("vix_percentile_lookback", 504)
        vix = getattr(qc, "vix", None)

        if vix is None or not qc.securities.contains_key(vix):
            return PhaseResult(decision="skip", blocked=False, reason="VIX not in securities", facts={}, metrics={})

        try:
            from QuantConnect import Resolution  # noqa
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
