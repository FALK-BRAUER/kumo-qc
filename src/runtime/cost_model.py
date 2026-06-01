"""GH#321 — realistic IBKR transaction-cost + slippage wiring (single code path, cloud == local).

A frictionless backtest lets the optimizer favour high-turnover params that are brittle and lose
money under real friction (Gemini-2.5-pro review, 2026-06-02). #321 installs a venue-accurate cost
model so every swept result is meaningful and the cost-aware baseline is what the sweep must beat.

DESIGN (docs/notes/321-cost-model-design.md):
  - BrokerageModel = `BrokerageName.INTERACTIVE_BROKERS_BROKERAGE` / `AccountType.MARGIN` — IBKR is
    the LIVE broker (paper DUK434934 / live U18777181). This makes fills, supported-order-type
    validation, and the buying-power model match the venue we actually trade.
  - FeeModel (per equity) = QC built-in `InteractiveBrokersFeeModel` — encodes the IBKR US-equity
    TIERED schedule ($0.0035/share, $0.35/order min, 1% trade-value max + reg pass-throughs). We
    wire the BUILT-IN (charter: prefer QC built-ins over hand-rolled math) and unit-test the
    resulting per-fill behaviour rather than re-deriving the schedule.
  - SlippageModel (per equity) = `ConstantSlippageModel(slippage_percent)` — a flat per-side bps.
    Chosen over VolumeShareSlippageModel because our universe is LIQUID (price>=$10, trailing-20d
    ADV>=$100M selection-gate floors): on a DAILY bar the volume-share ratio is ~0 → under-penalises
    turnover (defeats #321's purpose); on a 5-MIN bar it spikes on bar-granularity noise. A flat
    bps is conservative AND turnover-monotone (2x trades ⇒ 2x slippage) — the property #321 pins.

WHERE IT WIRES — a SECURITY INITIALIZER (`set_security_initializer`). It fires once per security at
subscription, on EVERY equity however added (the daily universe via add_universe, the intraday
5-min feeds via add_equity, SPY) — local AND cloud, ONE code path, NO `if cloud` branch (charter).
Indices (VIX) are skipped: not tradeable, carry no fees. `wire_cost_models(qc, ...)` is called once
from lean_entry.initialize(); the cost assumption lives in ONE place and applies uniformly.

PROVENANCE: `slippage_percent` is sourced from a lean_entry class attr (SLIPPAGE_PERCENT), the same
treatment as the universe knobs (PREFILTER_DV etc.) — NOT in STRATEGY_CONFIG, so config_hash is
byte-unchanged; the cost change is pinned by the GIT COMMIT (this file) + the startup COST_MODEL_INIT
log. The cost assumption is explicit + version-pinned per the charter (cost = a strategy input).

TESTABILITY: the QC types (BrokerageName/AccountType/InteractiveBrokersFeeModel/ConstantSlippageModel)
live in AlgorithmImports — absent in the dev venv. We import them lazily INSIDE the functions (guarded)
so this module imports cleanly under unit tests, and the tests stub the qc + security objects to
exercise the REAL wiring control-flow (the lean_entry test idiom). The actual fill arithmetic of the
QC built-ins is integration-verified on a LEAN run; the unit tests pin our conservative reference of
the SAME schedule so the math is locked even where the QC classes are unavailable.
"""
from __future__ import annotations

from typing import Any

# Default per-SIDE slippage: 5 bps. EXPLICIT + version-pinned (charter). Conservative for the
# ADV>=$100M / price>=$10 liquid universe at 10%-position clip sizes.
DEFAULT_SLIPPAGE_PERCENT: float = 0.0005

# IBKR US-equity TIERED commission constants — the conservative arithmetic REFERENCE the unit
# tests assert against where the QC built-in is unavailable (dev venv). On a real LEAN run the
# QC InteractiveBrokersFeeModel is authoritative; these mirror its documented schedule so the
# per-fill behaviour (per-share scaling + the min-per-order floor) is locked in CI.
IB_PER_SHARE: float = 0.0035          # $/share
IB_MIN_PER_ORDER: float = 0.35        # $ floor per order
IB_MAX_PCT_OF_TRADE: float = 0.01     # 1% of trade value cap


def ib_equity_commission(shares: float, price: float) -> float:
    """Conservative arithmetic REFERENCE for the IBKR US-equity tiered commission on ONE fill.

    commission = clamp( shares * IB_PER_SHARE , min=IB_MIN_PER_ORDER , max=1% of trade value ).

    PURE (no QC types). This is the test/reference oracle — the LIVE path uses QC's
    InteractiveBrokersFeeModel (wired by the security initializer below), which models the same
    schedule plus exchange/regulatory pass-throughs. `shares` is treated as an absolute count
    (a buy and a sell of N shares cost the same commission)."""
    qty = abs(float(shares))
    if qty == 0:
        return 0.0
    raw = qty * IB_PER_SHARE
    floored = max(raw, IB_MIN_PER_ORDER)
    trade_value = qty * abs(float(price))
    cap = trade_value * IB_MAX_PCT_OF_TRADE
    # The 1% cap only binds for very low-priced names; never let the cap drop BELOW the per-order
    # floor (a 1-share $0.01 trade still costs the $0.35 min at IBKR). Cap applies above the floor.
    return min(floored, cap) if cap >= IB_MIN_PER_ORDER else floored


def apply_constant_slippage(reference_price: float, direction: int,
                            slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> float:
    """Conservative arithmetic REFERENCE for ConstantSlippageModel on ONE fill: the fill price
    moves AGAINST the order by `slippage_percent` (a buy fills higher, a sell fills lower).

    PURE (no QC types). `direction` > 0 = buy, < 0 = sell. The LIVE path uses QC's
    ConstantSlippageModel (wired below); this mirrors it so the per-side directionality +
    turnover-monotonicity are unit-pinned. Flat bps ⇒ N round-trips cost N× the slippage."""
    p = abs(float(reference_price))
    s = abs(float(slippage_percent))
    if direction > 0:
        return p * (1.0 + s)
    if direction < 0:
        return p * (1.0 - s)
    return p


def _is_equity(security: Any) -> bool:
    """True iff `security` is a tradeable EQUITY (the only type we charge IB equity fees on).

    Robust across the QC runtime AND the test stubs: prefer `security.type`/`.security_type`
    compared to the SecurityType.EQUITY enum when AlgorithmImports is present; fall back to a
    string match ("equity") so a stub exposing `.type = "equity"` / `.type = "index"` works too."""
    st = getattr(security, "type", None)
    if st is None:
        st = getattr(security, "security_type", None)
    try:  # pragma: no cover - QC runtime enum path
        from AlgorithmImports import SecurityType
        if st == SecurityType.EQUITY:
            return True
        if st == SecurityType.INDEX:
            return False
    except Exception:  # noqa: BLE001 - dev venv / stub path
        pass
    return str(st).lower().endswith("equity")


def make_equity_cost_initializer(slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> Any:
    """Build the per-security initializer callable: install InteractiveBrokersFeeModel +
    ConstantSlippageModel on every EQUITY, skip indices. Returns a plain callable
    `initializer(security)` so it works both as a QC security initializer and in unit tests.

    The QC types are imported LAZILY inside the callable (guarded) so importing this module never
    requires AlgorithmImports; if a stubbed security carries no QC types the callable still calls
    `set_fee_model`/`set_slippage_model` with our reference instances (the test path)."""

    def _initializer(security: Any) -> None:
        if not _is_equity(security):
            return  # indices (VIX) etc. — not tradeable, no fees/slippage
        fee_model: Any
        slip_model: Any
        try:  # pragma: no cover - QC runtime; absent in the dev venv
            from AlgorithmImports import ConstantSlippageModel, InteractiveBrokersFeeModel
            fee_model = InteractiveBrokersFeeModel()
            slip_model = ConstantSlippageModel(slippage_percent)
        except Exception:  # noqa: BLE001 - dev venv / unit test: use reference stand-ins
            fee_model = _RefIbFeeModel()
            slip_model = _RefConstantSlippageModel(slippage_percent)
        security.set_fee_model(fee_model)
        security.set_slippage_model(slip_model)

    return _initializer


def wire_cost_models(qc: Any, *, slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> None:
    """Wire the IBKR brokerage model + the equity cost security-initializer onto `qc` (the QC
    algorithm). Called ONCE from lean_entry.initialize(). Single code path, no `if cloud` branch.

    1. set_brokerage_model(INTERACTIVE_BROKERS_BROKERAGE, MARGIN) — venue-accurate fills + BP.
    2. set_security_initializer(make_equity_cost_initializer(slippage_percent)) — IB fee +
       constant slippage on every equity, however subscribed (universe / intraday / SPY).
    3. log COST_MODEL_INIT — the version-pin breadcrumb (config_hash is unchanged; the commit
       records the cost change)."""
    try:  # pragma: no cover - QC runtime; absent in the dev venv / unit tests
        from AlgorithmImports import AccountType, BrokerageName
        qc.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE, AccountType.MARGIN)
    except Exception:  # noqa: BLE001 - dev venv / stub: a stubbed qc records the call args itself
        set_bm = getattr(qc, "set_brokerage_model", None)
        if callable(set_bm):
            # stub path: pass sentinel strings so the test can assert IB/MARGIN without QC enums
            set_bm("INTERACTIVE_BROKERS_BROKERAGE", "MARGIN")

    qc.set_security_initializer(make_equity_cost_initializer(slippage_percent))

    log = getattr(qc, "log", None)
    if callable(log):
        log(
            f"COST_MODEL_INIT|brokerage=INTERACTIVE_BROKERS_BROKERAGE|account=MARGIN|"
            f"fee=InteractiveBrokersFeeModel|slippage=ConstantSlippageModel|"
            f"slippage_percent={slippage_percent} (#321 realistic IBKR cost+slippage)"
        )


# --------------------------------------------------------------------------------------------
# Reference stand-ins used ONLY when AlgorithmImports is absent (dev venv / unit tests). They
# expose the SAME .get_order_fee / .get_slippage_approximation surface as the QC models so the
# wiring + math can be exercised without the QC runtime. On a real LEAN run the QC built-ins are
# used instead (see make_equity_cost_initializer).
# --------------------------------------------------------------------------------------------
class _RefIbFeeModel:
    """Mirrors QC InteractiveBrokersFeeModel for the dev venv: commission via ib_equity_commission."""

    def get_order_fee(self, shares: float, price: float) -> float:
        return ib_equity_commission(shares, price)


class _RefConstantSlippageModel:
    """Mirrors QC ConstantSlippageModel for the dev venv: a flat per-side bps move."""

    def __init__(self, slippage_percent: float = DEFAULT_SLIPPAGE_PERCENT) -> None:
        self.slippage_percent = float(slippage_percent)

    def get_slippage_approximation(self, reference_price: float, direction: int) -> float:
        """Slippage AMOUNT (price delta), per QC's ConstantSlippageModel contract."""
        return abs(float(reference_price)) * self.slippage_percent

    def fill_price(self, reference_price: float, direction: int) -> float:
        return apply_constant_slippage(reference_price, direction, self.slippage_percent)
