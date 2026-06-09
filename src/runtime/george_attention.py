"""George attention-prior loader.

Attention inputs are confidence-weighted priors from research data, not trades by themselves. The
loader keeps source roles visible so transcript/video discussion, scanner candidate, and actual trade
rows can be analyzed separately.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.symbol_key import canonical_symbol_key


@dataclass(frozen=True, slots=True)
class GeorgeAttentionRow:
    ticker: str
    industry: str
    source_role: str
    attention_score: float
    confidence: float


def _clean(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key, default)
    if value is None:
        return default
    return str(value).strip() or default


def _float(row: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def read_george_attention(path: str | Path) -> list[GeorgeAttentionRow]:
    """Read ticker/industry attention rows from CSV.

    Required: either `ticker` or `industry`. Optional: `source_role`, `attention_score`,
    `confidence`. Confidence is clamped to [0, 1]; attention defaults to 1.0.
    """
    rows: list[GeorgeAttentionRow] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticker = canonical_symbol_key(_clean(row, "ticker"))
            industry = _clean(row, "industry", "").lower()
            if not ticker and not industry:
                continue
            confidence = max(0.0, min(1.0, _float(row, "confidence", 1.0)))
            rows.append(
                GeorgeAttentionRow(
                    ticker=ticker,
                    industry=industry,
                    source_role=_clean(row, "source_role", "unknown"),
                    attention_score=_float(row, "attention_score", 1.0),
                    confidence=confidence,
                )
            )
    return rows


def attention_maps(rows: list[GeorgeAttentionRow]) -> dict[str, Any]:
    ticker_scores: defaultdict[str, float] = defaultdict(float)
    industry_scores: defaultdict[str, float] = defaultdict(float)
    source_counts: Counter[str] = Counter()
    for row in rows:
        weighted = row.attention_score * row.confidence
        source_counts[row.source_role] += 1
        if row.ticker:
            ticker_scores[row.ticker] += weighted
        if row.industry:
            industry_scores[row.industry] += weighted
    return {
        "ticker_attention": dict(ticker_scores),
        "industry_attention": dict(industry_scores),
        "source_role_counts": dict(source_counts),
    }


def load_george_attention_maps(path: str | Path) -> dict[str, Any]:
    return attention_maps(read_george_attention(path))
