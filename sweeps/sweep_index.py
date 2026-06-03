"""#10 storage-uniformity — the WORKTREE-LOCAL sweep index (bt-results.csv format).

DESIGN (HQ-approved option b, 2026-06-02): bt-results.csv is SINGLE-WRITER on `main` (a worktree
appending to it would diverge — the cross-branch drift the worktree-isolation discipline forbids).
So a sweep writes its per-(config,window) rows to a worktree-local `results/sweeps/<grid>/
sweep_index.csv` in the EXACT bt-results.csv column order; a main-side tool (`scripts/
merge_sweep_index.py`) dedup-appends them into bt-results.csv on demand. The archive stays the source
of truth — both the index and bt-results.csv are regenerable projections.

A sweep ledger row is PARTIAL vs a full bt-results row (the sweep scores off the equity-curve
statistics trio + order count, not closed-trade win-rate / fees / $-pnl). The missing columns are
emitted BLANK (never fabricated) and the `notes` column tags the row as a sweep cell + its provenance.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence

from sweeps.provenance import LedgerRow
from sweeps.types import Window

# The canonical bt-results.csv header — MUST match results/bt-results.csv exactly (single source).
BT_RESULTS_COLUMNS = (
    "date_run", "window", "period_start", "period_end", "commit", "branch", "environment",
    "sharpe", "net_profit_pct", "net_profit_usd", "total_orders", "win_rate_pct",
    "max_drawdown_pct", "total_fees_usd", "notes",
)


def sweep_index_rows(
    ledger: Sequence[LedgerRow],
    *,
    windows: Mapping[str, Window],
    branch: str,
    env: str,
    grid: str,
    date_run: str,
) -> list[dict[str, str]]:
    """Map sweep ledger rows → bt-results-format dict rows. `windows` maps window NAME → Window (for
    period_start/end; the ledger carries only the name). Missing-in-ledger columns (net_profit_usd /
    win_rate_pct / total_fees_usd) are BLANK — a sweep cell doesn't measure them, and we never fake.
    `notes` tags the sweep grid + config + bt_id + verdict so a reader knows it's a sweep cell."""
    rows: list[dict[str, str]] = []
    for r in ledger:
        w = windows.get(r.window)
        rows.append({
            "date_run": date_run,
            "window": r.window,
            "period_start": w.start if w else "",
            "period_end": w.end if w else "",
            "commit": r.commit,
            "branch": branch,
            "environment": env,
            "sharpe": f"{r.sharpe:.3f}",
            "net_profit_pct": f"{r.ret_pct:.3f}",
            "net_profit_usd": "",                      # not measured by the sweep
            "total_orders": str(r.orders),
            "win_rate_pct": "",                        # not measured by the sweep
            "max_drawdown_pct": f"{r.dd_pct:.3f}",
            "total_fees_usd": "",                      # not measured by the sweep
            "notes": f"sweep cell [{grid}] config={r.config_hash} bt={r.bt_id} verdict={r.verdict}",
        })
    return rows


def to_index_csv(rows: Sequence[Mapping[str, str]]) -> str:
    """Render rows as a bt-results-format CSV (header + rows), column order canonical + stable."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(BT_RESULTS_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in BT_RESULTS_COLUMNS})
    return buf.getvalue()
