from datetime import datetime

import pytest

from engine.base import DegradedDataError
from engine.context import PhaseContext
from phases.exit.mfe_intraday_exit.mfe_intraday_exit import MfeIntradayExit


class FakeHolding:
    def __init__(self, quantity=100):
        self.invested = True
        self.quantity = quantity


class FakeUpperHolding:
    def __init__(self, quantity=100):
        self.Invested = True
        self.Quantity = quantity


class FakeTransactions:
    def __init__(self, orders=None):
        self.orders = orders or []

    def get_open_orders(self, symbol=None):
        return self.orders


class FakeOrder:
    def __init__(self, order_id):
        self.id = order_id


class FakeTicket:
    def __init__(self, order_id):
        self.order_id = order_id


class FakeQC:
    def __init__(self, sym, path=None, orders=None):
        self.portfolio = {sym: FakeHolding()}
        self.transactions = FakeTransactions(orders)
        self._position_meta = {sym: {"entry_price": 100.0, "entry_date": datetime(2025, 1, 1)}}
        self._position_path = {
            sym: path or {
                "last_price": 106.0,
                "peak_price": 108.0,
                "trough_price": 98.0,
                "current_return_pct": 0.06,
                "mfe_pct": 0.08,
                "mae_pct": -0.02,
                "giveback_pct": 0.02,
                "days_held": 2,
                "bars_held": 12,
            }
        }
        self.logged = []

    def log(self, msg):
        self.logged.append(msg)


def _sym(name="AAPL"):
    return type("Symbol", (), {"value": name})()


def _run(qc, **params):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 3, 10, 35), data=None)
    phase = MfeIntradayExit(MfeIntradayExit.Params(**params), logger=None)
    result = phase.evaluate(ctx)
    return result, ctx


def test_contract_and_clock_are_intraday():
    assert MfeIntradayExit.REQUIRES_UPSTREAM == ["position_path"]
    assert MfeIntradayExit.PHASE_RESOLUTION == "intraday"


def test_target_exit_fires_from_position_path_last_price():
    sym = _sym()
    qc = FakeQC(sym)

    result, ctx = _run(qc, target_pct=0.05, min_hold_bars=1)

    assert result.facts == {"exit_count": 1, "target_count": 1, "giveback_count": 0}
    assert len(ctx.bar_state.exit_intents) == 1
    intent = ctx.bar_state.exit_intents[0]
    assert intent.ticker == "AAPL"
    assert intent.qty == -100
    assert intent.price == 106.0
    assert intent.order_type == "market"
    assert qc.logged == [
        "EXIT_EVENT|2025-01-03|AAPL|event=MFE_INTRADAY_EXIT|module=exit.mfe_intraday_exit"
        "|reason=target|days_held=2|qty=100.000000|entry_price=100.000000|exit_price=106.000000"
        "|pnl=600.000000|return_pct=0.060000|mfe_pct=0.080000|mae_pct=-0.020000"
        "|peak_return_pct=0.080000|giveback_from_peak_pct=0.020000"
    ]


def test_target_exit_handles_uppercase_holding_contract():
    sym = _sym("UPPER")
    qc = FakeQC(sym)
    qc.portfolio[sym] = FakeUpperHolding(quantity=25)

    result, ctx = _run(qc, target_pct=0.05, min_hold_bars=1)

    assert result.facts == {"exit_count": 1, "target_count": 1, "giveback_count": 0}
    assert ctx.bar_state.exit_intents[0].qty == -25


def test_diagnostic_log_reports_seen_path_and_maxima():
    sym = _sym("DIAG")
    qc = FakeQC(sym)

    result, _ctx = _run(qc, target_pct=0.20, min_hold_bars=1, diagnostic_log=True)

    assert result.facts["exit_count"] == 0
    assert result.facts["holdings_seen"] == 1
    assert result.facts["invested_seen"] == 1
    assert result.facts["paths_seen"] == 1
    assert result.facts["max_current_return_pct"] == 0.06
    assert result.facts["max_mfe_pct"] == 0.08
    assert result.facts["max_giveback_pct"] == 0.02
    assert qc.logged == [
        "MFE_DIAG_COUNTS|2025-01-03|h=1|i=1|p=1|so=0|sa=0|se=0|sp=0|sh=0|sc=0",
        "MFE_DIAG_MAX|2025-01-03|r=0.060000|rs=DIAG|m=0.080000|ms=DIAG|g=0.020000|gs=DIAG",
    ]


def test_tracked_protective_stop_order_does_not_block_runtime_exit():
    sym = _sym("STOP")
    qc = FakeQC(sym, orders=[FakeOrder(order_id=77)])
    qc._position_meta[sym]["protective_stop_ticket"] = FakeTicket(order_id=77)

    result, ctx = _run(qc, target_pct=0.05, min_hold_bars=1)

    assert result.facts["exit_count"] == 1
    assert ctx.bar_state.exit_intents[0].ticker == "STOP"


def test_unrelated_open_order_still_blocks_runtime_exit():
    sym = _sym("OPEN")
    qc = FakeQC(sym, orders=[FakeOrder(order_id=12)])
    qc._position_meta[sym]["protective_stop_ticket"] = FakeTicket(order_id=77)

    result, ctx = _run(qc, target_pct=0.05, min_hold_bars=1, diagnostic_log=True)

    assert result.facts["exit_count"] == 0
    assert result.facts["skipped_open_orders"] == 1
    assert ctx.bar_state.exit_intents == []


def test_giveback_exit_uses_fraction_threshold():
    sym = _sym("MSFT")
    qc = FakeQC(
        sym,
        path={
            "last_price": 104.0,
            "peak_price": 110.0,
            "current_return_pct": 0.04,
            "mfe_pct": 0.10,
            "mae_pct": -0.01,
            "giveback_pct": 0.06,
            "days_held": 1,
            "bars_held": 8,
        },
    )

    result, ctx = _run(
        qc,
        target_pct=0.0,
        min_mfe_pct=0.06,
        giveback_fraction=0.50,
        min_giveback_pct=0.02,
        min_hold_bars=2,
    )

    assert result.facts["giveback_count"] == 1
    assert ctx.bar_state.exit_intents[0].ticker == "MSFT"


def test_session_path_can_drive_same_day_fade_exit():
    sym = _sym("TSLA")
    qc = FakeQC(
        sym,
        path={
            "last_price": 103.0,
            "peak_price": 112.0,
            "current_return_pct": 0.03,
            "mfe_pct": 0.12,
            "mae_pct": -0.01,
            "giveback_pct": 0.09,
            "session_mfe_pct": 0.07,
            "session_giveback_pct": 0.04,
            "days_held": 5,
            "bars_held": 20,
        },
    )

    result, ctx = _run(
        qc,
        target_pct=0.0,
        min_mfe_pct=0.06,
        giveback_fraction=0.50,
        min_giveback_pct=0.03,
        min_hold_bars=2,
        use_session_path=True,
    )

    assert result.facts["giveback_count"] == 1
    assert ctx.bar_state.exit_intents[0].price == 103.0


def test_min_hold_bars_defers_exit():
    sym = _sym("NVDA")
    qc = FakeQC(sym)
    qc._position_path[sym]["bars_held"] = 1

    result, ctx = _run(qc, target_pct=0.05, min_hold_bars=3)

    assert result.facts["exit_count"] == 0
    assert ctx.bar_state.exit_intents == []


def test_missing_position_path_raises_loud():
    sym = _sym("AMD")
    qc = FakeQC(sym)
    qc._position_path = {}

    with pytest.raises(DegradedDataError, match="PositionPathTracker"):
        _run(qc)


def test_skips_when_exit_already_present():
    sym = _sym("SHOP")
    qc = FakeQC(sym)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 3, 10, 35), data=None)
    ctx.bar_state.exit_intents.append(type("Intent", (), {"ticker": "SHOP"})())

    MfeIntradayExit(MfeIntradayExit.Params(target_pct=0.05), logger=None).evaluate(ctx)

    assert len(ctx.bar_state.exit_intents) == 1
