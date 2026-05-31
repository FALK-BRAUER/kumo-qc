"""Leaderboard (#214 component 6) — rank scored configs by the D5 composite.

Sorts ScoredConfigs by composite DESC (stability minus complexity minus knife-edge penalty,
per ADR-0001 D5) and emits a stable, deterministic ranking. Ties break on (1) higher
stability, (2) fewer free params (Occam — prefer the simpler at a tie), (3) config_hash
(total order, so the same input always yields byte-identical output — the #182 determinism
discipline applied to the leaderboard).

Emits both a structured leaderboard (list of rows) and a CSV/Markdown rendering carrying the
metrics trio (Sharpe / Ret% / DD%) on every row (MEMORY: result-table-format — never Sharpe
alone), the complexity column (D5.3), and the config-hash for provenance.
"""
from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sweeps.score import ScoredConfig

LEADERBOARD_COLUMNS = (
    "rank",
    "config_hash",
    "composite",
    "stability",
    "sharpe_mean",
    "sharpe_std",
    "ret_pct_mean",
    "dd_pct_mean",
    "dd_pct_worst",
    "free_params",
    "complexity_penalty",
    "robustness_penalty",
    "over_dof_budget",
    "n_windows",
)


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    """One ranked entry — a ScoredConfig plus its 1-based rank."""

    rank: int
    scored: ScoredConfig

    @property
    def config_hash(self) -> str:
        return self.scored.config_hash


def _sort_key(s: ScoredConfig) -> tuple[float, float, int, str]:
    # composite DESC, stability DESC, free_params ASC (Occam tie-break), hash ASC (total order).
    return (-s.composite, -s.stability, s.total_free_params, s.config_hash)


def build_leaderboard(scored: Iterable[ScoredConfig]) -> list[LeaderboardRow]:
    """Rank scored configs by the D5 composite (DESC), deterministic tie-breaking.

    Returns 1-based-ranked rows. Rank-by-composite operationalises rank-by-stability-not-peak
    (D5.2): the composite's dominant term is stability, and the complexity / knife-edge
    penalties only ever DEMOTE a config — so a steady simple config outranks a peaky complex
    one even when the latter has a higher best-window Sharpe.
    """
    ordered = sorted(scored, key=_sort_key)
    return [LeaderboardRow(rank=i + 1, scored=s) for i, s in enumerate(ordered)]


def _row_values(row: LeaderboardRow) -> tuple[object, ...]:
    s = row.scored
    agg = s.aggregate
    return (
        row.rank,
        s.config_hash,
        round(s.composite, 4),
        round(s.stability, 4),
        round(agg.sharpe.mean, 4),
        round(agg.sharpe.std, 4),
        round(agg.ret_pct.mean, 4),
        round(agg.dd_pct.mean, 4),
        round(agg.dd_pct.worst, 4),
        s.total_free_params,
        round(s.complexity_penalty, 4),
        round(s.robustness_penalty, 4),
        s.over_dof_budget,
        agg.n_windows,
    )


def to_csv(rows: Sequence[LeaderboardRow]) -> str:
    """Render the leaderboard as CSV (header + one row per config). Metrics trio on every row."""
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LEADERBOARD_COLUMNS)
    for row in rows:
        writer.writerow(_row_values(row))
    return buf.getvalue()


def to_markdown(rows: Sequence[LeaderboardRow]) -> str:
    """Render the leaderboard as a Markdown table (human-readable report)."""
    header = "| " + " | ".join(LEADERBOARD_COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in LEADERBOARD_COLUMNS) + " |"
    lines = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(v) for v in _row_values(row)) + " |")
    return "\n".join(lines) + "\n"
