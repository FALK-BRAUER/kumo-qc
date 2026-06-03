"""Regime phase: SPY daily Ichimoku bullishness gate (#342).

Kind: regime · Resolution: daily · Marker: spy_ichimoku_regime_v1

George's Ichimoku frame applied to the INDEX: allow new entries only when SPY's own daily Ichimoku
is bullish. Targets the #346 January massacre — 17/19 S1 closed losers entered Jan 3-14 2025 into
the Q1 chop, which the SPY-200MA gate (SPY sat well above its 200MA) did NOT catch. The
distinguishing signal, verified on data: SPY Tenkan < Kijun the ENTIRE Jan 3-14 window, flipping
T>K on Jan 27 2025 exactly as the market recovered. So the gate BLOCKS when SPY is not bullish:

    bullish := (Tenkan > Kijun)  AND  (close >= cloud_bottom)      [each condition toggleable]

T>K alone covers all of Jan 3-14 (price was ABOVE/IN/BELOW the cloud across that window, so
price-above-cloud alone would miss Jan 3/6/7); price>=cloud_bottom is George-coherent and does not
block the above-cloud Q2/Q3 winners.

FAIL-CLOSED (#261-7 anti-mirage): an ENABLED gate that cannot assess the regime (no SPY symbol,
insufficient history) BLOCKS entries — it never fail-opens (a not-ready gate cannot have approved
the regime). enabled=False → skip entirely (byte-parity with the no-extra-regime base).

Single code path: SPY's daily Ichimoku is computed from qc.history(spy, lookback, DAILY) — identical
local and cloud, no pre-wired indicator, no warmup-wiring edit. Standard Ichimoku (tenkan=9,
kijun=26, senkou_b=52, cloud displaced 26 bars forward → the cloud UNDER today is the senkou pair
computed 26 bars ago).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, PhaseResult
from engine.context import PhaseContext

# Standard Ichimoku periods + the forward cloud displacement.
_TENKAN = 9
_KIJUN = 26
_SENKOU_B = 52
_DISPLACE = 26
# Bars needed to read the cloud under today: senkou_b at index (n-1-26) needs 52 bars before it.
_MIN_BARS = _SENKOU_B + _DISPLACE + 1  # 79


class SpyIchimokuRegime(BasePhase):
    PHASE_KIND = "regime"
    PHASE_RESOLUTION = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    @dataclass(slots=True)
    class Params:
        enabled: bool = False
        require_tenkan_over_kijun: bool = True  # the Jan-cohort signal (T<K all of Jan 3-14)
        require_price_above_cloud: bool = True  # George-coherent; close >= cloud_bottom
        lookback: int = 120  # >= _MIN_BARS (79); 120 leaves slack for holidays/gaps

    def __init__(self, params: "SpyIchimokuRegime.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def _block(self, reason: str, date_str: str) -> PhaseResult:
        return PhaseResult(decision="block", blocked=True, reason=reason,
                           facts={"date": date_str, "regime": "spy_ichimoku"}, metrics={})

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        if not self.p.enabled:
            return PhaseResult(decision="skip", blocked=False,
                               reason="spy_ichimoku_regime disabled", facts={}, metrics={})

        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        spy = getattr(qc, "spy", None)
        # FAIL-CLOSED (#261-7): enabled gate, can't assess → BLOCK, never fail-open.
        if spy is None or not qc.securities.contains_key(spy):
            return self._block("SPY not in securities — BLOCK until assessable (#261-7)", date_str)

        try:
            from QuantConnect import Resolution  # noqa: PLC0415
            import pandas as pd  # noqa: PLC0415

            hist = qc.history(spy, self.p.lookback, Resolution.DAILY)
            if hist is None or len(hist) < _MIN_BARS:
                return self._block("insufficient SPY history — BLOCK (#261-7)", date_str)
            if isinstance(hist.index, pd.MultiIndex):
                hist = hist.droplevel(0)
            cols = {c.lower(): c for c in hist.columns}
            high = hist[cols["high"]].astype(float)
            low = hist[cols["low"]].astype(float)

            tenkan = (high.rolling(_TENKAN).max() + low.rolling(_TENKAN).min()) / 2.0
            kijun = (high.rolling(_KIJUN).max() + low.rolling(_KIJUN).min()) / 2.0
            senkou_a = (tenkan + kijun) / 2.0
            senkou_b = (high.rolling(_SENKOU_B).max() + low.rolling(_SENKOU_B).min()) / 2.0

            tenkan_now = float(tenkan.iloc[-1])
            kijun_now = float(kijun.iloc[-1])
            # The cloud plotted UNDER today = the senkou pair computed _DISPLACE bars ago.
            a_under = float(senkou_a.iloc[-1 - _DISPLACE])
            b_under = float(senkou_b.iloc[-1 - _DISPLACE])
            cloud_bottom = min(a_under, b_under)
            # Current SPY price (consistent with spy_200ma's qc.securities[spy].price read).
            close_now = float(qc.securities[spy].price)
        except Exception:  # noqa: BLE001
            # An enabled gate that errored cannot vouch for the regime → fail-closed.
            return self._block("SPY Ichimoku compute error — BLOCK (#261-7)", date_str)

        tk_ok = (not self.p.require_tenkan_over_kijun) or (tenkan_now > kijun_now)
        cloud_ok = (not self.p.require_price_above_cloud) or (close_now >= cloud_bottom)
        bullish = tk_ok and cloud_ok

        reason = (f"SPY ichimoku {'bullish' if bullish else 'bearish'}: "
                  f"T={tenkan_now:.2f} {'>' if tenkan_now > kijun_now else '<='} K={kijun_now:.2f}, "
                  f"close={close_now:.2f} {'>=' if close_now >= cloud_bottom else '<'} "
                  f"cloudB={cloud_bottom:.2f}")
        return PhaseResult(
            decision="pass" if bullish else "block",
            blocked=not bullish,
            reason=reason,
            facts={"spy": close_now, "tenkan": tenkan_now, "kijun": kijun_now,
                   "cloud_bottom": cloud_bottom, "tk_ok": tk_ok, "cloud_ok": cloud_ok,
                   "date": date_str},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "spy_ichimoku_regime_v1"
