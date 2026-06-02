"""Exit phase: Cloud Breach Exit (#339 candidate C — BCT-3 H3).

Kind: exit_hard
Marker: cloud_breach_exit_v1

HYPOTHESIS (BCT-3 H3, #339): exit when price BREACHES INTO the cloud — close < cloud_TOP
(max(SenkouA, SenkouB)). This is TIGHTER than CloudAdherenceTrail (B, which holds through the whole
cloud and exits only on the cloud BOTTOM): C treats entering the cloud as the trend losing its clear
'price clearly above cloud' BCT structure (condition 5). The spectrum across the batch: A=Kijun-break
(tightest-ish), C=cloud-top breach, B=cloud-bottom breach (loosest). C tests whether exiting at the
cloud-top (rather than riding into the cloud) better balances cutting losers vs realizing recoverable
dips in the choppy Q1/Q4 regime.

Charter: single code path; exits run UNCONDITIONALLY (blocked=False always). Same fail-loud cold-
d_ichi guard (#261-8) + benign absent-indicator skip + open-orders skip as the exit_hard contract.
Not a time-exit — exits only on the cloud-top price breach. Optional weekly_kijun_exit composes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext


class CloudBreachExit(BasePhase):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        weekly_kijun_exit_enabled: bool = False
        enabled: bool = True

    def __init__(self, params: "CloudBreachExit.Params", logger: Any) -> None:
        super().__init__(params, logger)
        self.p = params

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        weekly_kijun_exit = self.p.weekly_kijun_exit_enabled
        exits_logged: list[str] = []

        for symbol, holding in list(qc.portfolio.items()):
            if not holding.invested or qc.transactions.get_open_orders(symbol):
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue  # benign skip: no indicator object (delisted/unsubscribed held name)
            d_ichi = ind.get("d_ichi")
            if d_ichi is None or not d_ichi.is_ready:
                raise DegradedDataError(
                    f"invested position with a cold/missing daily Ichimoku at stop-eval: "
                    f"symbol={symbol.value!r} date={date_str} d_ichi_present={d_ichi is not None} "
                    f"is_ready={getattr(d_ichi, 'is_ready', None)} — the cloud-breach stop cannot be "
                    f"evaluated, so the position would ride UNPROTECTED. An invested name must have a "
                    f"warm d_ichi (entry requires it); a cold one is degraded data, fail loud (#261-8)"
                )

            close = float(qc.securities[symbol].close)
            senkou_a = d_ichi.senkou_a.current.value
            senkou_b = d_ichi.senkou_b.current.value
            cloud_top = max(senkou_a, senkou_b)

            w_ichi = ind.get("w_ichi")
            w_kijun = w_ichi.kijun.current.value if (w_ichi and w_ichi.is_ready) else None

            # BCT-3 H3: exit when price breaches INTO the cloud (loses 'clearly above cloud').
            if close < cloud_top:
                ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value, qty=-holding.quantity, price=close,
                        stop=cloud_top, module="exit.cloud_breach_exit", risk_dollars=0.0,
                    )
                )
                exits_logged.append(f"CLOUD_BREACH_EXIT|{date_str}|{symbol.value}")
            elif weekly_kijun_exit and w_kijun is not None and close < w_kijun:
                ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value, qty=-holding.quantity, price=close,
                        stop=w_kijun, module="exit.cloud_breach_exit", risk_dollars=0.0,
                    )
                )
                exits_logged.append(f"WEEKLY_KIJUN_STOP|{date_str}|{symbol.value}")

        return PhaseResult(
            decision=exits_logged,
            blocked=False,  # exits NEVER block
            reason=f"{len(exits_logged)} exits",
            facts={"exit_count": len(exits_logged)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "cloud_breach_exit_v1"
