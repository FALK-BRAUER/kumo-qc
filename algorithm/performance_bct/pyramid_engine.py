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
}

# price-extension thresholds (fractional) for level-based variants, by add index
_PRICE_THRESH = {
    "Pa": [0.05, 0.10],
    "Pb": [0.10, 0.20],
}
# ATR multiples for Pc, by add index
_ATR_MULT = {"Pc": [1.0, 2.0]}

VARIANTS = ("Pa", "Pb", "Pc", "Pd", "Pe")


def add_dollars(variant: str, lots: int) -> float:
    """$-risk for the add creating lot `lots+1`. 0 if beyond the scheme."""
    sizes = ADD_SIZES.get(variant, [])
    idx = lots - 1
    return sizes[idx] if 0 <= idx < len(sizes) else 0.0


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
) -> bool:
    """
    Decide whether to add the next lot now. `lots` is the current lot count
    (>=1). Caller enforces MAX_LOTS and the breakeven/score guards.
    """
    idx = lots - 1  # which add this would be (0-based)
    if idx < 0:
        return False

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

    if variant == "Pe":  # fresh Tenkan>Kijun cross
        if idx >= len(ADD_SIZES["Pe"]):
            return False
        return bool(tk_cross)

    return False
