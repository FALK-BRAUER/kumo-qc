"""
Exit phase: Kijun stop + G3 cloud-bottom trailing + optional cloud/weekly-kijun.

Faithful carve of oracle _rebalance L429-468 (baseline-oracle-v0).
Exits run UNCONDITIONALLY — this phase always has blocked=False.
DO NOT modify stop logic — breaks champion-asis-v1 parity (ARCH-C ±0.01 gate).
"""
from __future__ import annotations

from engine.base import PhaseInterface, PhaseResult
from engine.context import PhaseContext, OrderIntent


class KijunG3Exits(PhaseInterface):
    PHASE_KIND = "exit_hard"
    REQUIRES_UPSTREAM = []
    PROVIDES_DOWNSTREAM = ["exit_intents"]

    # Matches oracle class constants
    PHASE3_DAYS: int = 56
    PHASE3_PNL: float = 0.15

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        qc = ctx.qc
        date_str = ctx.time.strftime("%Y-%m-%d")
        cloud_exit = self._params.get("cloud_exit_enabled", False)
        weekly_kijun_exit = self._params.get("weekly_kijun_exit_enabled", False)
        phase3_days = self._params.get("phase3_days", self.PHASE3_DAYS)
        phase3_pnl = self._params.get("phase3_pnl", self.PHASE3_PNL)

        exits_logged = []

        for symbol, holding in list(qc.portfolio.items()):
            if not holding.invested or qc.transactions.get_open_orders(symbol):
                continue

            ind = getattr(qc, "_indicators", {}).get(symbol)
            if ind is None:
                continue
            d_ichi = ind.get("d_ichi")
            if d_ichi is None or not d_ichi.is_ready:
                continue

            close = float(qc.securities[symbol].close)
            kijun = d_ichi.kijun.current.value
            senkou_a = d_ichi.senkou_a.current.value
            senkou_b = d_ichi.senkou_b.current.value
            cloud_top = max(senkou_a, senkou_b)
            cloud_bottom = min(senkou_a, senkou_b)

            w_ichi = ind.get("w_ichi")
            w_kijun = w_ichi.kijun.current.value if (w_ichi and w_ichi.is_ready) else None

            # G3: Phase-3 cloud-bottom trailing (≥56d held + ≥15% gain)
            meta = getattr(qc, "_position_meta", {}).get(symbol)
            in_phase3 = False
            if meta is not None:
                days_held = (ctx.time - meta["entry_date"]).days
                pnl_pct = close / meta["entry_price"] - 1
                if days_held >= phase3_days and pnl_pct >= phase3_pnl:
                    in_phase3 = True

            if in_phase3:
                if close < cloud_bottom:
                    ctx.bar_state.exit_intents.append(
                        OrderIntent(
                            ticker=symbol.value,
                            qty=-holding.quantity,
                            price=close,
                            stop=cloud_bottom,
                            module="exit.kijun_g3_exits",
                            risk_dollars=0.0,
                        )
                    )
                    exits_logged.append(f"PHASE3_EXIT|{date_str}|{symbol.value}")
            else:
                if close < kijun:
                    ctx.bar_state.exit_intents.append(
                        OrderIntent(
                            ticker=symbol.value,
                            qty=-holding.quantity,
                            price=close,
                            stop=kijun,
                            module="exit.kijun_g3_exits",
                            risk_dollars=0.0,
                        )
                    )
                    exits_logged.append(f"STOP|{date_str}|{symbol.value}")
                elif cloud_exit and close < cloud_top:
                    ctx.bar_state.exit_intents.append(
                        OrderIntent(
                            ticker=symbol.value,
                            qty=-holding.quantity,
                            price=close,
                            stop=cloud_top,
                            module="exit.kijun_g3_exits",
                            risk_dollars=0.0,
                        )
                    )
                    exits_logged.append(f"CLOUD_EXIT|{date_str}|{symbol.value}")
                elif weekly_kijun_exit and w_kijun is not None and close < w_kijun:
                    ctx.bar_state.exit_intents.append(
                        OrderIntent(
                            ticker=symbol.value,
                            qty=-holding.quantity,
                            price=close,
                            stop=w_kijun,
                            module="exit.kijun_g3_exits",
                            risk_dollars=0.0,
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
        return "kijun_g3_exits_v1"
