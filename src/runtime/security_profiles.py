"""Security profile loader for George-context runtime inputs.

The profile contract is deliberately small and source-aware: ticker -> sector, industry,
subindustry, proxy ETF, source, confidence. Runtime consumers get plain dictionaries so phases can
read them without importing this module.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.symbol_key import canonical_symbol_key


@dataclass(frozen=True, slots=True)
class SecurityProfile:
    ticker: str
    sector: str
    industry: str
    subindustry: str
    proxy_etf: str
    source: str
    confidence: float


def _clean(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    if value is None:
        return default
    return str(value).strip() or default


def _confidence(row: dict[str, Any]) -> float:
    raw = row.get("confidence", 1.0)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def read_security_profiles(path: str | Path) -> list[SecurityProfile]:
    """Read a CSV profile file.

    Required column: `ticker`. Optional columns: `sector`, `industry`, `subindustry`,
    `proxy_etf`, `source`, `confidence`. Missing sector/industry values become `unknown`.
    """
    rows: list[SecurityProfile] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = canonical_symbol_key(_clean(row, "ticker"))
            if not ticker:
                continue
            rows.append(
                SecurityProfile(
                    ticker=ticker,
                    sector=_clean(row, "sector", "unknown").lower(),
                    industry=_clean(row, "industry", "unknown").lower(),
                    subindustry=_clean(row, "subindustry", "unknown").lower(),
                    proxy_etf=canonical_symbol_key(_clean(row, "proxy_etf")),
                    source=_clean(row, "source", "unknown"),
                    confidence=_confidence(row),
                )
            )
    return rows


def profile_maps(profiles: list[SecurityProfile]) -> dict[str, Any]:
    """Return runtime maps consumed by phases and diagnostics."""
    by_ticker = {p.ticker: p for p in profiles}
    return {
        "security_profiles": {
            t: {
                "sector": p.sector,
                "industry": p.industry,
                "subindustry": p.subindustry,
                "proxy_etf": p.proxy_etf,
                "source": p.source,
                "confidence": p.confidence,
            }
            for t, p in by_ticker.items()
        },
        "industry_by_ticker": {t: p.industry for t, p in by_ticker.items()},
        "sector_by_ticker": {t: p.sector for t, p in by_ticker.items()},
        "proxy_by_ticker": {t: p.proxy_etf for t, p in by_ticker.items() if p.proxy_etf},
    }


def load_security_profile_maps(path: str | Path) -> dict[str, Any]:
    return profile_maps(read_security_profiles(path))
