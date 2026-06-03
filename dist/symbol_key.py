from typing import Any


def canonical_symbol_key(sym: Any) -> str:
    val = getattr(sym, "value", sym)
    return str(val).lower()
