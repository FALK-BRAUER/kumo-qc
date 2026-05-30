"""
Pyramid technique engine — Phase 3b (#172). Pure, QC-agnostic functions for the
5 add-trigger / add-size schemes. F1 proved the breakeven-triggered $200 add is
refuted (Exp$/trade +26 -> -10); this sweep searches for a mechanic that survives.

Convention: the INITIAL lot is sized by the risk base (risk_amount), NOT here.
This engine governs ADD lots only. `lots` = current lot count (1 after initial
entry); the next add creates lot `lots+1` and uses add index `lots-1`.

Variants:
  Pa de-pyramid    : adds at +5%, +10% from entry; sizes $250, $125 (decreasing)
  Pb wide-spaced   : adds at +10%, +20% from entry; sizes $200, $200
  Pc ATR-spaced    : adds at +1*ATR, +2*ATR from entry; sizes $200, $200
  Pd vol-confirmed : add on any day daily TR > 1.5x 20d avg TR; size $200 (event)
  Pe indicator     : add on a fresh Tenkan>Kijun cross; size $200 (event)
  Pe-rampup        : Pe trigger; anti-Kelly grow-with-evidence sizes $200, $400, $600;
                     uncapped keeps growing 200*(idx+1) for any add index (event)
  Pe-conviction    : Pe trigger; decreasing sizes $300, $200, $100;
                     uncapped floors at $100 (never below, keeps adding each cross) (event)
  Pe-winscale      : Pe trigger; gain-conditional on close vs entry — base $300,
                     +5% -> $500, +10% -> $600; index-independent, same every add (event)
All cap at MAX_LOTS (caller-enforced).
"""
from __future__ import annotations

# add-lot dollar sizes per variant, indexed by add number (lot 2 = idx0, lot 3 = idx1).
# Pd/Pe are event-driven with a flat $200 add regardless of index.
ADD_SIZES = {
    "Pa": [250.0, 125.0],
    "Pb": [200.0, 200.0],
    "Pc": [200.0, 200.0],
    "Pd": [200.0, 200.0],
    "Pe": [200.0, 200.0],
    "Pe-rampup": [200.0, 400.0, 600.0],
    "Pe-conviction": [300.0, 200.0, 100.0],
    "Pe-winscale": [300.0, 300.0, 300.0],  # base; gain-conditional override in add_dollars
}

# price-extension thresholds (fractional) for level-based variants, by add index
_PRICE_THRESH = {
    "Pa": [0.05, 0.10],
    "Pb": [0.10, 0.20],
}
# ATR multiples for Pc, by add index
_ATR_MULT = {"Pc": [1.0, 2.0]}

VARIANTS = ("Pa", "Pb", "Pc", "Pd", "Pe", "Pe-rampup", "Pe-conviction", "Pe-winscale")


def add_dollars(
    variant: str,
    lots: int,
    uncapped: bool = False,
    *,
    entry_price: float | None = None,
    close: float | None = None,
) -> float:
    """$-risk for the add creating lot `lots+1`. 0 if beyond the scheme.
    uncapped (Pc/Pe + Pe-* only): the lot count is bounded by signal frequency +
    max_ticker_risk_usd, not a hardcoded cap. Per-variant uncapped sizing:
      Pc/Pe        : flat last-scheme size.
      Pe-rampup    : keep growing 200*(idx+1) for any add index (anti-Kelly).
      Pe-conviction: decreasing then floor at 100 (never below 100, never 0).
      Pe-winscale  : gain-conditional, index-independent (handled below for all modes).
    entry_price/close are only consumed by Pe-winscale; if None it falls back to base."""
    sizes = ADD_SIZES.get(variant, [])
    idx = lots - 1
    if idx < 0 or not sizes:
        return 0.0

    if variant == "Pe-winscale":
        # gain-conditional, same for every add index; requires both price inputs.
        base = sizes[0]  # 300.0
        if entry_price is None or close is None or entry_price <= 0:
            scaled = base
        elif close >= entry_price * 1.10:
            scaled = 600.0
        elif close >= entry_price * 1.05:
            scaled = 500.0
        else:
            scaled = base
        if uncapped:
            return scaled
        return scaled if idx < len(sizes) else 0.0

    if uncapped and variant == "Pe-rampup":
        return 200.0 * (idx + 1)  # unbounded by index — grows with each add
    if uncapped and variant == "Pe-conviction":
        return max(sizes[idx] if idx < len(sizes) else 100.0, 100.0)  # floor at 100
    if uncapped and variant in ("Pc", "Pe"):
        return sizes[min(idx, len(sizes) - 1)]
    return sizes[idx] if idx < len(sizes) else 0.0


def should_add(
    variant: str,
    lots: int,
    *,
    entry_price: float,
    close: float,
    entry_atr: float | None = None,
    daily_tr: float | None = None,
    vol_20d_avg: float | None = None,
    tk_cross: bool = False,
    uncapped: bool = False,
) -> bool:
    """
    Decide whether to add the next lot now. `lots` is the current lot count
    (>=1). Caller enforces the lot ceiling (max_ticker_risk_usd) + breakeven guards.
    uncapped (Pc/Pe): extend the technique to unlimited lots — Pe fires on every
    fresh cross; Pc fires at each successive +N*ATR multiple.
    """
    idx = lots - 1  # which add this would be (0-based)
    if idx < 0:
        return False

    if uncapped and variant in ("Pe", "Pe-rampup", "Pe-conviction", "Pe-winscale"):
        return bool(tk_cross)  # fire on every fresh cross; size differs by variant
    if uncapped and variant == "Pc":
        if entry_atr is None or entry_atr <= 0:
            return False
        return close >= entry_price + lots * entry_atr  # next ATR multiple (+1,+2,+3,...)

    if variant in _PRICE_THRESH:
        thr = _PRICE_THRESH[variant]
        if idx >= len(thr) or entry_price <= 0:
            return False
        return close >= entry_price * (1.0 + thr[idx])

    if variant in _ATR_MULT:
        mult = _ATR_MULT[variant]
        if idx >= len(mult) or entry_atr is None or entry_atr <= 0:
            return False
        return close >= entry_price + mult[idx] * entry_atr

    if variant == "Pd":  # volatility-confirmed momentum day
        if idx >= len(ADD_SIZES["Pd"]):
            return False
        if daily_tr is None or vol_20d_avg is None or vol_20d_avg <= 0:
            return False
        return daily_tr > 1.5 * vol_20d_avg

    if variant in ("Pe", "Pe-rampup", "Pe-conviction", "Pe-winscale"):  # fresh Tenkan>Kijun cross
        if idx >= len(ADD_SIZES[variant]):  # capped: bound by this variant's ADD_SIZES length
            return False
        return bool(tk_cross)

    return False
