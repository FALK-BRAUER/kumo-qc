"""Exit phase: Cloud-Adherence Trail (#339 candidate B — the BCT-3 'hold above cloud' exit).

Kind: exit_hard
Marker: cloud_adherence_trail_v1

HYPOTHESIS (BCT-3, #339): the champion's daily-Kijun-break exit is the WORST exit (24% win) — it
realizes RECOVERABLE dips. BCT-3 finds dips that hold ABOVE the cloud recover ~75% of the time. So
this exit trails the CLOUD BOTTOM (min(SenkouA, SenkouB)), NOT the Kijun: a position is HELD through
a Kijun-break as long as price stays above the cloud (a recoverable dip), and only exits when price
breaches the cloud bottom (adherence broken → the uptrend structure has failed). The intent: cut the
Q1/Q4 whipsaw bleed (the choppy quarters where Kijun-break churns recoverable dips into realized
losses) while still protecting on a genuine trend break.

Charter: single code path; exits run UNCONDITIONALLY (blocked=False always). Same fail-loud cold-
d_ichi guard as KijunG3Exits (#261-8: an invested position with a cold/missing daily Ichimoku at
stop-eval would ride UNPROTECTED → raise). NOT a time-exit: the position only exits on a price-stop
breach (cloud bottom), never on age. The optional weekly_kijun_exit composes the weekly-Kijun stop
(candidate H's charter stack).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.base import BasePhase, DegradedDataError, PhaseResult
from engine.context import OrderIntent, PhaseContext


class CloudAdherenceTrail(BasePhase):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
        # Optional weekly-Kijun stop on top of the cloud-bottom trail (candidate H's charter stack).
        weekly_kijun_exit_enabled: bool = False
        enabled: bool = True

    def __init__(self, params: "CloudAdherenceTrail.Params", logger: Any) -> None:
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
                # Benign skip: no indicator object at all (delisted/unsubscribed name still held —
                # nothing to evaluate a stop against). Distinct from the cold-d_ichi raise below
                # (indicator EXISTS but isn't ready = broken wiring on a warmed name). Mirrors
                # KijunG3Exits' #261-8 boundary exactly.
                continue
            # FAIL-LOUD (#261-8): an INVESTED position whose daily Ichimoku is missing/COLD at
            # stop-eval rides UNPROTECTED — raise (an invested name must have a warm d_ichi; entry
            # required it + _seed_daily warmed it).
            d_ichi = ind.get("d_ichi")
            if d_ichi is None or not d_ichi.is_ready:
                raise DegradedDataError(
                    f"invested position with a cold/missing daily Ichimoku at stop-eval: "
                    f"symbol={symbol.value!r} date={date_str} d_ichi_present={d_ichi is not None} "
                    f"is_ready={getattr(d_ichi, 'is_ready', None)} — the cloud-adherence stop cannot "
                    f"be evaluated, so the position would ride UNPROTECTED. An invested name must have "
                    f"a warm d_ichi (entry requires it); a cold one is degraded data, fail loud (#261-8)"
                )

            close = float(qc.securities[symbol].close)
            senkou_a = d_ichi.senkou_a.current.value
            senkou_b = d_ichi.senkou_b.current.value
            cloud_bottom = min(senkou_a, senkou_b)

            w_ichi = ind.get("w_ichi")
            w_kijun = w_ichi.kijun.current.value if (w_ichi and w_ichi.is_ready) else None

            # BCT-3 cloud adherence: exit ONLY when price breaches the cloud bottom (structure
            # broken). A dip below Kijun but ABOVE the cloud is a recoverable dip → HOLD.
            if close < cloud_bottom:
                ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value, qty=-holding.quantity, price=close,
                        stop=cloud_bottom, module="exit.cloud_adherence_trail", risk_dollars=0.0,
                    )
                )
                exits_logged.append(f"CLOUD_ADHERENCE_EXIT|{date_str}|{symbol.value}")
            elif weekly_kijun_exit and w_kijun is not None and close < w_kijun:
                ctx.bar_state.exit_intents.append(
                    OrderIntent(
                        ticker=symbol.value, qty=-holding.quantity, price=close,
                        stop=w_kijun, module="exit.cloud_adherence_trail", risk_dollars=0.0,
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
        return "cloud_adherence_trail_v1"
