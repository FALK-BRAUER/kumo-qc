"""GH#321 — realistic IBKR cost+slippage model: wiring + commission/slippage math + turnover penalty.

The QC types (BrokerageName/AccountType/InteractiveBrokersFeeModel/ConstantSlippageModel) live in
AlgorithmImports — absent in the dev venv. So:
  - the WIRING tests stub the qc + security objects and exercise the REAL control-flow in
    runtime.cost_model (the lean_entry test idiom), and
  - the MATH tests assert the conservative arithmetic REFERENCE (ib_equity_commission /
    apply_constant_slippage), which mirrors the QC built-ins' documented schedule, so the per-fill
    behaviour (min-per-order floor, per-share scaling, per-side slippage, turnover-monotonicity) is
    locked in CI even where the QC classes are unavailable.
"""
from __future__ import annotations

from typing import Any

import pytest

from runtime.cost_model import (
    DEFAULT_SLIPPAGE_PERCENT,
    IB_MIN_PER_ORDER,
    IB_PER_SHARE,
    apply_constant_slippage,
    ib_equity_commission,
    make_equity_cost_initializer,
    wire_cost_models,
)


# ---------------------------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------------------------
class FakeSecurity:
    """Records the fee/slippage models set on it. `type_` mimics security.type ("equity"/"index")."""

    def __init__(self, type_: str) -> None:
        self.type = type_
        self.fee_model: Any = None
        self.slippage_model: Any = None

    def set_fee_model(self, m: Any) -> None:
        self.fee_model = m

    def set_slippage_model(self, m: Any) -> None:
        self.slippage_model = m


class FakeQc:
    """Records set_brokerage_model + set_security_initializer + log calls."""

    def __init__(self) -> None:
        self.brokerage_args: Any = None
        self.initializer: Any = None
        self.logs: list[str] = []

    def set_brokerage_model(self, *args: Any) -> None:
        self.brokerage_args = args

    def set_security_initializer(self, fn: Any) -> None:
        self.initializer = fn

    def log(self, msg: str) -> None:
        self.logs.append(msg)


# ---------------------------------------------------------------------------------------------
# 1. wiring: brokerage model + security initializer set; initializer installs models on equities
# ---------------------------------------------------------------------------------------------
def test_wire_cost_models_sets_ib_brokerage_and_initializer() -> None:
    qc = FakeQc()
    wire_cost_models(qc, slippage_percent=0.0005)
    # brokerage model set to IB / MARGIN (sentinel strings on the stub path)
    assert qc.brokerage_args == ("INTERACTIVE_BROKERS_BROKERAGE", "MARGIN")
    # a security initializer was registered
    assert callable(qc.initializer)
    # version-pin breadcrumb logged
    assert any("COST_MODEL_INIT" in m and "slippage_percent=0.0005" in m for m in qc.logs)


def test_initializer_installs_fee_and_slippage_on_equity() -> None:
    init = make_equity_cost_initializer(slippage_percent=0.0005)
    eq = FakeSecurity("Equity")
    init(eq)
    assert eq.fee_model is not None, "equity must get a fee model"
    assert eq.slippage_model is not None, "equity must get a slippage model"
    # the reference slippage model carries the configured per-side bps
    assert eq.slippage_model.slippage_percent == pytest.approx(0.0005)


# ---------------------------------------------------------------------------------------------
# 2. index (VIX) skipped — not tradeable, no fee/slippage
# ---------------------------------------------------------------------------------------------
def test_initializer_skips_index() -> None:
    init = make_equity_cost_initializer()
    idx = FakeSecurity("Index")
    init(idx)
    assert idx.fee_model is None
    assert idx.slippage_model is None


# ---------------------------------------------------------------------------------------------
# 3. slippage application — per-side directionality + turnover-monotonicity
# ---------------------------------------------------------------------------------------------
def test_constant_slippage_per_side_direction() -> None:
    # buy fills HIGHER (slippage against the buyer), sell fills LOWER
    buy = apply_constant_slippage(100.0, direction=+1, slippage_percent=0.0005)
    sell = apply_constant_slippage(100.0, direction=-1, slippage_percent=0.0005)
    assert buy == pytest.approx(100.0 * 1.0005)
    assert sell == pytest.approx(100.0 * 0.9995)
    assert buy > 100.0 > sell


def test_constant_slippage_default_is_5bps() -> None:
    assert DEFAULT_SLIPPAGE_PERCENT == pytest.approx(0.0005)
    buy = apply_constant_slippage(200.0, direction=+1)
    assert buy == pytest.approx(200.0 * 1.0005)


# ---------------------------------------------------------------------------------------------
# 4. commission math — per-share scaling + the min-per-order floor + the 1% cap
# ---------------------------------------------------------------------------------------------
def test_commission_per_share_scaling_above_floor() -> None:
    # 10,000 shares @ $50 = $35.00 (0.0035 * 10000), well below the 1% cap ($5,000,000 * 0.01)
    assert ib_equity_commission(10_000, 50.0) == pytest.approx(35.0)


def test_commission_hits_min_per_order_floor() -> None:
    # 10 shares: 10 * 0.0035 = $0.035 < $0.35 → floored to the $0.35 min-per-order
    assert ib_equity_commission(10, 100.0) == pytest.approx(IB_MIN_PER_ORDER)
    # 100 shares: 100 * 0.0035 = $0.35 → exactly at the floor
    assert ib_equity_commission(100, 100.0) == pytest.approx(0.35)
    # 101 shares: just above the floor
    assert ib_equity_commission(101, 100.0) == pytest.approx(101 * IB_PER_SHARE)


def test_commission_buy_and_sell_symmetric() -> None:
    # absolute share count: a sell of N costs the same commission as a buy of N
    assert ib_equity_commission(-500, 40.0) == pytest.approx(ib_equity_commission(500, 40.0))


def test_commission_one_percent_cap_binds_on_cheap_size() -> None:
    # A very cheap, large clip where 1% of trade value < per-share raw but still >= the floor.
    # 20,000 shares @ $0.50 = $10,000 trade value; per-share raw = 20000*0.0035 = $70; 1% cap = $100.
    # cap >= raw here so raw wins (not capped). Construct a case where the cap actually binds:
    # 100,000 shares @ $0.10 = $10,000 value; raw = 100000*0.0035 = $350; 1% cap = $100 (binds).
    c = ib_equity_commission(100_000, 0.10)
    assert c == pytest.approx(100.0)  # capped at 1% of $10,000, and 100 >= the $0.35 floor


def test_commission_zero_shares_is_zero() -> None:
    assert ib_equity_commission(0, 100.0) == 0.0


# ---------------------------------------------------------------------------------------------
# 5. initialize() wires the cost model — drive the REAL BctEngineAlgorithm.initialize body
# ---------------------------------------------------------------------------------------------
def test_initialize_calls_wire_cost_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real lean_entry.initialize() must call wire_cost_models with the class SLIPPAGE_PERCENT.
    We monkeypatch wire_cost_models to record the call, and stub the QC-only init calls so the
    real initialize() body runs up to the wiring line."""
    import runtime.lean_entry as lean_entry
    from runtime.lean_entry import BctEngineAlgorithm

    recorded: dict[str, Any] = {}

    def _fake_wire(qc: Any, *, slippage_percent: float) -> None:
        recorded["qc"] = qc
        recorded["slippage_percent"] = slippage_percent

    monkeypatch.setattr(lean_entry, "wire_cost_models", _fake_wire)

    # module-level QC enums are None in the dev venv — stub the ones initialize() reads.
    class _Enum:
        DAILY = "DAILY"
        RAW = "RAW"

    monkeypatch.setattr(lean_entry, "Resolution", _Enum, raising=False)
    monkeypatch.setattr(lean_entry, "DataNormalizationMode", _Enum, raising=False)

    algo = BctEngineAlgorithm.__new__(BctEngineAlgorithm)

    # --- stub the QC-runtime surface initialize() touches (mirrors the lean_entry test idiom) ---
    inert = lambda *a, **k: None  # noqa: E731
    for name in (
        "set_start_date", "set_end_date", "set_cash", "set_benchmark", "set_time_zone",
        "set_warmup", "add_universe", "log",
    ):
        monkeypatch.setattr(algo, name, inert, raising=False)

    class _Settings:
        resolution = None
        data_normalization_mode = None

    algo.universe_settings = _Settings()

    class _Eq:
        def __init__(self) -> None:
            self.symbol = "SPY"

        def set_data_normalization_mode(self, m: Any) -> None:
            pass

    monkeypatch.setattr(algo, "add_equity", lambda *a, **k: _Eq(), raising=False)
    monkeypatch.setattr(algo, "add_index", lambda *a, **k: _Eq(), raising=False)
    monkeypatch.setattr(algo, "sma", lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(algo, "ichimoku", lambda *a, **k: object(), raising=False)

    class _Sched:
        def on(self, *a: Any, **k: Any) -> None:
            pass

    class _DateRules:
        def every_day(self, *a: Any, **k: Any) -> Any:
            return object()

    class _TimeRules:
        def after_market_close(self, *a: Any, **k: Any) -> Any:
            return object()

    algo.schedule = _Sched()
    algo.date_rules = _DateRules()
    algo.time_rules = _TimeRules()

    # StrategyEngine construction at the end of initialize needs a config; stub the engine ctor.
    import engine.engine as engine_mod
    monkeypatch.setattr(engine_mod, "StrategyEngine", lambda **k: object(), raising=False)
    monkeypatch.setattr(lean_entry, "StrategyEngine", lambda **k: object(), raising=False)
    algo.STRATEGY_CONFIG = object()

    algo.initialize()

    assert recorded.get("qc") is algo
    assert recorded.get("slippage_percent") == pytest.approx(BctEngineAlgorithm.SLIPPAGE_PERCENT)


# ---------------------------------------------------------------------------------------------
# 6. BEHAVIORAL (GH#321 acceptance): high-turnover penalized vs low-turnover at EQUAL gross edge
# ---------------------------------------------------------------------------------------------
def _net_after_costs(round_trips: int, shares: float, price: float,
                     gross_edge_per_trip: float) -> float:
    """Simulate N round-trips (buy+sell) at a fixed share count + price, EQUAL gross edge per trip.
    Net = total gross edge − Σ commissions (2 fills/trip) − Σ slippage cost (2 sides/trip)."""
    gross = round_trips * gross_edge_per_trip
    commission = 0.0
    slippage_cost = 0.0
    for _ in range(round_trips):
        # two fills per round trip (entry + exit)
        commission += ib_equity_commission(shares, price) * 2
        # slippage cost per side ≈ shares * price * bps; buy higher + sell lower → 2 sides
        slip_per_side = abs(apply_constant_slippage(price, +1) - price) * shares
        slippage_cost += slip_per_side * 2
    return gross - commission - slippage_cost


def test_high_turnover_penalized_vs_low_turnover_at_equal_gross_edge() -> None:
    shares, price = 1_000.0, 100.0
    # Equal TOTAL gross edge: 1 trip earns $X; 10 trips each earn $X/10 → same gross, 10x the friction.
    total_gross = 500.0
    low = _net_after_costs(round_trips=1, shares=shares, price=price, gross_edge_per_trip=total_gross)
    high = _net_after_costs(
        round_trips=10, shares=shares, price=price, gross_edge_per_trip=total_gross / 10
    )
    # gross is identical; the high-turnover config nets STRICTLY LESS after friction.
    assert high < low
    # and the gap is exactly the extra 9 round-trips' worth of friction (sanity on monotonicity).
    friction_per_trip = ib_equity_commission(shares, price) * 2 + (
        abs(apply_constant_slippage(price, +1) - price) * shares * 2
    )
    assert (low - high) == pytest.approx(9 * friction_per_trip)
