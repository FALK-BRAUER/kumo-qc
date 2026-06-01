"""Robust-selection objective (#323) — DSR / PBO / CPCV + gates + the selector.

The #323 SELECTOR replaces the old D5 composite (sweeps/score.py) AS THE DECISION RULE
(the composite stays a diagnostic column). It is a lexicographic FILTER then a weighted
SCORE, computed entirely on the RETURN/TRADE series the sweep already produced — ZERO extra
backtests, fully mock-testable (the #214 compute boundary).

Modules:
  - dsr.py       Deflated Sharpe Ratio (Bailey & López de Prado 2014) — the multiple-trials
                 correction. PRIMARY selector.
  - pbo.py       Probability of Backtest Overfitting via CSCV (Bailey et al. 2017) — the
                 GLOBAL overfitting measure across the whole sweep.
  - cpcv.py      Combinatorial purged cross-validation + embargo — the OOS path estimator.
  - gates.py     Trade-count gates + window weighting + the W5-concentration robustness guard.
  - selector.py  The lexicographic filter -> weighted score -> champion-beat selector.
"""
from __future__ import annotations

from sweeps.objective.cpcv import CPCVSplit, cpcv_splits
from sweeps.objective.dsr import (
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe,
    sharpe_ratio,
)
from sweeps.objective.gates import (
    GateVerdict,
    WindowReturns,
    concentration_guard,
    event_windows,
    trade_count_gate,
    window_weight,
)
from sweeps.objective.pbo import PBOResult, cscv_pbo
from sweeps.objective.selector import (
    FILTER,
    WEIGHTS,
    ConfigEvidence,
    ObjectiveScore,
    select,
)

__all__ = [
    "CPCVSplit",
    "ConfigEvidence",
    "FILTER",
    "GateVerdict",
    "ObjectiveScore",
    "PBOResult",
    "WEIGHTS",
    "WindowReturns",
    "concentration_guard",
    "cpcv_splits",
    "cscv_pbo",
    "deflated_sharpe",
    "event_windows",
    "expected_max_sharpe",
    "probabilistic_sharpe",
    "select",
    "sharpe_ratio",
    "trade_count_gate",
    "window_weight",
]
