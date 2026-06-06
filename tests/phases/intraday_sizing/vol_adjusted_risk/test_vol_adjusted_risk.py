"""VolAdjustedRisk: sizes by dollar risk and scales down when VIX rises."""
from datetime import datetime

from engine.context import OrderIntent, PhaseContext
from phases.intraday_sizing.vol_adjusted_risk.vol_adjusted_risk import VolAdjustedRisk


class _Portfolio:
    total_portfolio_value = 100_000.0


class _QC:
    def __init__(self, vix: float | None = None) -> None:
        self.portfolio = _Portfolio()
        if vix is not None:
            self.vix_level = vix


def _run(vix: float | None = None) -> int:
    ctx = PhaseContext(qc=_QC(vix), time=datetime(2025, 1, 2, 10, 0), data=None, clock="intraday")
    ctx.bar_state.sized_orders = [
        OrderIntent(ticker="AAA", qty=0, price=100.0, stop=90.0, module="trigger", risk_dollars=0.0, order_type="market")
    ]
    VolAdjustedRisk(VolAdjustedRisk.Params(risk_pct=0.01, max_position_pct=1.0), logger=None).evaluate(ctx)
    return ctx.bar_state.sized_orders[0].qty


def test_sizes_by_dollar_risk() -> None:
    assert _run(vix=None) == 100


def test_high_vix_scales_qty_down() -> None:
    assert _run(vix=40.0) < _run(vix=20.0)
