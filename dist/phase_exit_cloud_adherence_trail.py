from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from base import BasePhase, DegradedDataError, PhaseResult
from context import OrderIntent, PhaseContext


class CloudAdherenceTrail(BasePhase):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    @dataclass(slots=True)
    class Params:
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

            close = float(qc.securities[symbol].close)

            daily_fp = getattr(qc, "_daily_cache_fp", None)
            if daily_fp:
                if weekly_kijun_exit:
                    raise DegradedDataError(
                        "warmup-skip + weekly_kijun_exit_enabled unsupported: w_kijun is not in the "
                        "daily_scalar cache (the champion runs weekly_kijun_exit OFF)"
                    )
                row = qc._require_daily_row(symbol, ctx.time.date())
                if row is None:
                    continue
                cloud_bottom = row["d_cloud_bottom"]
                w_kijun = None
            else:
                ind = getattr(qc, "_indicators", {}).get(symbol)
                if ind is None:
                    continue
                d_ichi = ind.get("d_ichi")
                if d_ichi is None or not d_ichi.is_ready:
                    raise DegradedDataError(
                        f"invested position with a cold/missing daily Ichimoku at stop-eval: "
                        f"symbol={symbol.value!r} date={date_str} d_ichi_present={d_ichi is not None} "
                        f"is_ready={getattr(d_ichi, 'is_ready', None)} — the cloud-adherence stop cannot "
                        f"be evaluated, so the position would ride UNPROTECTED. An invested name must have "
                        f"a warm d_ichi (entry requires it); a cold one is degraded data, fail loud (#261-8)"
                    )
                cloud_bottom = min(d_ichi.senkou_a.current.value, d_ichi.senkou_b.current.value)
                w_ichi = ind.get("w_ichi")
                w_kijun = w_ichi.kijun.current.value if (w_ichi and w_ichi.is_ready) else None

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
            blocked=False,
            reason=f"{len(exits_logged)} exits",
            facts={"exit_count": len(exits_logged)},
            metrics={},
        )

    @property
    def version_marker(self) -> str:
        return "cloud_adherence_trail_v1"
