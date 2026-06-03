"""THE canonical symbol-key form — single source of truth, shared across engine + phases + runtime.

Extracted from runtime/lean_entry.py (#276b-1 FIX3 migration) so the hot trading-path keying sites —
candidate injection, sizing/FIRE_ENTRIES, the intraday confirm gates, and the snapshot — can ALL
resolve symbols through ONE normalizer instead of open-coding `.value` (UPPERCASE) vs `.value.lower()`
(LOWERCASE) per site. Lives in `engine/` (the shared base both phases and runtime already depend on)
so it imports without a layering inversion — engine never imports phases.
"""
from typing import Any


def canonical_symbol_key(sym: Any) -> str:
    """THE canonical symbol-key form (single source of truth). The coarse/universe path stores
    tickers LOWERCASE (coarse_to_dollar_volume / coarse_to_close lower `c.symbol.value` to the
    zip-stem / qc._active.value.lower() convention) → `_ranked_today` holds LOWERCASE tickers. A QC
    Symbol's `.value` is UPPERCASE. Any lookup that keys a QC Symbol against a coarse-derived store
    (or vice versa) MUST normalize through THIS function or it silently misses (the rank=None
    cloud-omit bug, #276b-1 FIX3 — the SAME bug class as the earlier inject .lower()-vs-FIRE .value
    case mismatch). Accepts either a QC Symbol (reads `.value`) or a raw string.
    """
    val = getattr(sym, "value", sym)
    return str(val).lower()
