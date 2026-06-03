from __future__ import annotations

from typing import Any

DEFAULT_SLIPPAGE_PERCENT: float = 0.0005

IB_PER_SHARE: float = 0.0035
IB_MIN_PER_ORDER: float = 0.35
IB_MAX_PCT_OF_TRADE: float = 0.01


def ib_equity_commission(shares: float, price: float) -> float:
    qty = abs(float(shares))
    if qty == 0:
        return 0.0
    raw = qty * IB_PER_SHARE
    floored = max(raw, IB_MIN_PER_ORDER)
    trade_value = qty * abs(float(price))
    cap = trade_value * IB_MAX_PCT_OF_TRADE
    return min(floored, cap) if cap >= IB_MIN_PER_ORDER else floored


def apply_constant_slippage(reference_price: float, direction: int,
                            slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> float:
    p = abs(float(reference_price))
    s = abs(float(slippage_percent))
    if direction > 0:
        return p * (1.0 + s)
    if direction < 0:
        return p * (1.0 - s)
    return p


def _is_equity(security: Any) -> bool:
    st = getattr(security, "type", None)
    if st is None:
        st = getattr(security, "security_type", None)
    try:
        from AlgorithmImports import SecurityType
        if st == SecurityType.EQUITY:
            return True
        if st == SecurityType.INDEX:
            return False
    except Exception:
        pass
    return str(st).lower().endswith("equity")


def make_equity_cost_initializer(slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> Any:

    def _initializer(security: Any) -> None:
        if not _is_equity(security):
            return
        fee_model: Any
        slip_model: Any
        try:
            from AlgorithmImports import ConstantSlippageModel, InteractiveBrokersFeeModel
            fee_model = InteractiveBrokersFeeModel()
            slip_model = ConstantSlippageModel(slippage_percent)
        except Exception:
            fee_model = _RefIbFeeModel()
            slip_model = _RefConstantSlippageModel(slippage_percent)
        security.set_fee_model(fee_model)
        security.set_slippage_model(slip_model)

    return _initializer


def wire_cost_models(qc: Any, *, slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> None:
    try:
        from AlgorithmImports import AccountType, BrokerageName
        qc.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
    except Exception:
        set_bm = getattr(qc, "set_brokerage_model", None)
        if callable(set_bm):
            set_bm("INTERACTIVE_BROKERS_BROKERAGE", "MARGIN")

    qc.set_security_initializer(make_equity_cost_initializer(slippage_percent))

    log = getattr(qc, "log", None)
    if callable(log):
        log(
            f"COST_MODEL_INIT|brokerage=INTERACTIVE_BROKERS_BROKERAGE|account=MARGIN|"
            f"fee=InteractiveBrokersFeeModel|slippage=ConstantSlippageModel|"
            f"slippage_percent={slippage_percent} (#321 realistic IBKR cost+slippage)"
        )


class _RefIbFeeModel:

    def get_order_fee(self, shares: float, price: float) -> float:
        return ib_equity_commission(shares, price)


class _RefConstantSlippageModel:

    def __init__(self, slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> None:
        self.slippage_percent = float(slippage_percent)

    def get_slippage_approximation(self, reference_price: float, direction: int) -> float:
        return abs(float(reference_price)) * self.slippage_percent

    def fill_price(self, reference_price: float, direction: int) -> float:
        return apply_constant_slippage(reference_price, direction, self.slippage_percent)
