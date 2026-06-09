"""Catalog of sweepable ranking phases."""
from __future__ import annotations

from phases.ranking.george_industry_attention.george_industry_attention import GeorgeIndustryAttention
from phases.ranking.lambdamart_scanner_ranker.lambdamart_scanner_ranker import LambdamartScannerRanker

RANKING_PHASES = (GeorgeIndustryAttention, LambdamartScannerRanker)
