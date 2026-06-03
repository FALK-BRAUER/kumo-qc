"""Exit phase: Multi-Metric Confirm Exit (#339 candidate D — BCT-3 H2).

Kind: exit_hard
Marker: multi_metric_confirm_exit_v1

HYPOTHESIS (BCT-3 H2, #339): the Kijun-break-ALONE exit (24% win) whipsaws because ONE bearish
signal isn't confirmation. BCT-3 H2 (MACD-turn) wins 72% by requiring a CONFIRMED momentum turn. The
strategy maintains no MACD, so this exit requires ≥`confirm_n` of the available daily bearish signals
to AGREE before exiting (multi-metric confirmation, not single-signal):
  1. price below Kijun        (close < kijun)
  2. ADX falling              (adx_window[0] < adx_window[3] — momentum weakening, the now-vs-3-back
                               convention from oracle_helpers.score_symbol_native)
  3. bearish directional      (-DI > +DI)
Default confirm_n=2 → exit only when the turn is corroborated; holds single-signal noise (the Q1/Q4
whipsaw that Kijun-alone realizes). The stop level is the Kijun (the structural reference).

Charter: single code path; exits run UNCONDITIONALLY (blocked=False). Fail-loud (#261-8) if an
invested position has a cold/missing daily Ichimoku OR ADX at eval — the exit depends on BOTH, and
entry required both ready (signal cond 7 needs ADX), so a cold one is degraded data → raise (never an
unprotected ride). Benign skip for a fully-absent indicator entry (delisted/unsubscribed). Not a
time-exit. The ADX-falling sub-signal needs ≥4 ADX samples; before that it's treated as not-falling
(a benign warmup edge — Kijun + DI still protect, no unprotected ride).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext


class MultiMetricConfirmExit(BasePhase):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        confirm_n: int = 2  # how many of the 3 bearish signals must agree to exit
        enabled: bool = True

    def __init__(self, params: "MultiMetricConfirmExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        confirm_n = self.p.confirm_n
        exits_logged: list[str] = []

        for symbol, holding in list(qc.portfolio.items()):
            if not holding.invested or qc.transactions.get_open_orders(symbol):
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue  # benign skip: no indicator object (delisted/unsubscribed held name)
            d_ichi = ind.get("d_ichi")
            adx = ind.get("adx")
            adx_window = ind.get("adx_window")
            if d_ichi is None or not d_ichi.is_ready or adx is None or not adx.is_ready:
                raise DegradedDataError(
                    f"invested position with a cold/missing daily Ichimoku or ADX at exit-eval: "
                    f"symbol={symbol.value!r} date={date_str} "
                    f"d_ichi_ready={getattr(d_ichi, 'is_ready', None)} adx_ready={getattr(adx, 'is_ready', None)}"
                    f" — the multi-metric exit cannot be evaluated, so the position would ride "
                    f"UNPROTECTED. An invested name must have warm d_ichi+ADX (entry required them); "
                    f"a cold one is degraded data, fail loud (#261-8)"
                )

            close = float(qc.securities[symbol].close)
            kijun = d_ichi.kijun.current.value
            plus_di = adx.positive_directional_index.current.value
            minus_di = adx.negative_directional_index.current.value
            adx_falling = bool(adx_window is not None and adx_window.count >= 4
                               and adx_window[0] < adx_window[3])

            sig_kijun = close < kijun
            sig_di_bear = minus_di > plus_di
            confirmations = int(sig_kijun) + int(adx_falling) + int(sig_di_bear)

            if confirmations >= confirm_n:
                ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value, qty=-holding.quantity, price=close,
                        stop=kijun, module="exit.multi_metric_confirm_exit", risk_dollars=0.0,
                    )
                )
                exits_logged.append(
                    f"MULTI_CONFIRM_EXIT|{date_str}|{symbol.value}|n={confirmations}"
                    f"|kijun={int(sig_kijun)}|adxfall={int(adx_falling)}|dibear={int(sig_di_bear)}"
                )

        return PhaseResult(
            decision=exits_logged,
            blocked=False,  # exits NEVER block
            reason=f"{len(exits_logged)} exits",
            facts={"exit_count": len(exits_logged)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "multi_metric_confirm_exit_v1"
