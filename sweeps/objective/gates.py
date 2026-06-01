"""Trade-count gates + window weighting + the robustness (W5-concentration) guard (#323 B.4).

Three hard filters applied BEFORE scoring (a config that fails any is REJECTED, kept on the
leaderboard with its reject reason for transparency):

  1. TRADE-COUNT gate (fixes #266 trade-starvation):
       - total trades >= MIN_TOTAL_TRADES (50) across the panel, AND
       - >= MIN_TRADES_PER_WINDOW (10) trades in MORE THAN HALF the windows (>= 4 of 6).
     A config that fires too rarely has no statistical sample — its Sharpe is luck.

  2. ROBUSTNESS / W5-CONCENTRATION guard (the #323 single-window-carried rejection):
       A config whose POSITIVE blend comes from ONE window is NOT robust — it "wins" because
       a single window (the analysis' W5 sep-oct) carried it. Reject if:
         - any single window contributes > MAX_SINGLE_WINDOW_SHARE (0.60) of the total
           positive return, OR
         - fewer than MIN_NONNEG_WINDOWS (most: >= n_windows-1, i.e. all-but-one) windows are
           positive-or-flat, OR
         - the OOS / holdout window is negative.
     Require positive-or-flat across MOST windows + positive OOS — the windows-AND-FY
     consistency that is the real robustness signal.

  3. WINDOW WEIGHTING: w = min(1, T_w / T_target) so a trade-starved window contributes
     proportionally LESS to the weighted panel Sharpe (a lucky 3-trade window can't dominate
     the mean). T_target ~= 30 trades = a "full" sample.

Plus the EVENT-WINDOW builder: slice a trade series into spans of >= trades_per_window each,
so each window is a comparable statistical sample (an ADDITIONAL panel feeding the gate/DSR;
the calendar 6 stay the mandated headline panel — OQ-4).

All compute-free, mock-testable.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sweeps.types import TradeRecord, Window

MIN_TOTAL_TRADES = 50
MIN_TRADES_PER_WINDOW = 10
T_TARGET = 30
"""A "full" window sample size (trades). Windows with fewer are down-weighted."""

MAX_SINGLE_WINDOW_SHARE = 0.60
"""Max fraction of total POSITIVE return one window may contribute before it's "carried"."""


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """The pass/reject outcome of a gate. `reason` is None on PASS, else the reject string."""

    passed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WindowReturns:
    """Per-window evidence for the gates: the window, its trade count, and its return.

    `ret` is the window's net return (e.g. the BT Ret% for that window). `is_oos` flags the
    holdout / OOS window (FY2024) the robustness guard requires to be positive. `is_stress`
    flags the FY full-year stress window (evaluated for catastrophe, not equal-weight).
    """

    window: Window
    n_trades: int
    ret: float
    is_oos: bool = False
    is_stress: bool = False


def window_weight(n_trades: int, t_target: int = T_TARGET) -> float:
    """w = min(1, T / T_target) — a trade-starved window contributes proportionally less."""
    if t_target <= 0:
        raise ValueError("t_target must be > 0")
    if n_trades < 0:
        raise ValueError("n_trades must be >= 0")
    return min(1.0, n_trades / t_target)


def trade_count_gate(windows: Sequence[WindowReturns]) -> GateVerdict:
    """Reject trade-starved configs (#266). Panel windows only (stress excluded from the count).

    Total >= 50 across the panel AND >= 10 trades in > half the (non-stress) windows.
    """
    panel = [w for w in windows if not w.is_stress]
    if not panel:
        return GateVerdict(False, "REJECT-trades: no panel windows")
    total = sum(w.n_trades for w in panel)
    if total < MIN_TOTAL_TRADES:
        return GateVerdict(False, f"REJECT-trades: {total}<{MIN_TOTAL_TRADES} total trades")
    n_ge = sum(1 for w in panel if w.n_trades >= MIN_TRADES_PER_WINDOW)
    need = len(panel) // 2 + 1  # MORE than half
    if n_ge < need:
        return GateVerdict(
            False,
            f"REJECT-trades: only {n_ge} windows have >={MIN_TRADES_PER_WINDOW} trades "
            f"(need >{len(panel) // 2})",
        )
    return GateVerdict(True)


def concentration_guard(windows: Sequence[WindowReturns]) -> GateVerdict:
    """The W5-concentration robustness guard — reject a single-window-carried config.

    A config is NOT robust if its positive blend rests on ONE window. Reject when:
      - one window supplies > MAX_SINGLE_WINDOW_SHARE of the total POSITIVE return, OR
      - more than one (non-stress) window is strictly negative (require positive-or-flat across
        MOST windows — all-but-one), OR
      - the OOS / holdout window is negative.
    The stress window (FY full year) is excluded here — it has its OWN catastrophe check.
    """
    panel = [w for w in windows if not w.is_stress]
    if not panel:
        return GateVerdict(False, "REJECT-concentration: no panel windows")

    # OOS must be positive (if an OOS window is present).
    for w in panel:
        if w.is_oos and w.ret <= 0.0:
            return GateVerdict(
                False, f"REJECT-concentration: OOS window {w.window.name} ret={w.ret:.4f}<=0"
            )

    # Positive-or-flat across MOST windows (allow at most one strictly-negative window).
    negatives = [w for w in panel if w.ret < 0.0]
    if len(negatives) > 1:
        names = ",".join(w.window.name for w in negatives)
        return GateVerdict(
            False,
            f"REJECT-concentration: {len(negatives)} negative windows ({names}) — "
            "not positive-or-flat across most windows",
        )

    # Single-window dominance of the POSITIVE return.
    pos = [(w.window.name, w.ret) for w in panel if w.ret > 0.0]
    total_pos = sum(r for _, r in pos)
    if total_pos > 0.0:
        top_name, top_ret = max(pos, key=lambda x: x[1])
        share = top_ret / total_pos
        if share > MAX_SINGLE_WINDOW_SHARE:
            return GateVerdict(
                False,
                f"REJECT-concentration: window {top_name} supplies {share:.0%} of positive "
                f"return (> {MAX_SINGLE_WINDOW_SHARE:.0%}) — single-window-carried",
            )
    return GateVerdict(True)


def event_windows(
    trades: Sequence[TradeRecord], *, trades_per_window: int = T_TARGET
) -> list[Window]:
    """Slice a trade series (entry-time ordered) into spans of >= trades_per_window each.

    Each event-window is a comparable statistical sample (a calendar year can be trade-
    starved; an event-window always holds ~trades_per_window trades). The window's [start,
    end] is the first entry .. last exit of its span. A trailing remainder smaller than the
    target is MERGED into the previous window (so every window meets the >= target floor) —
    unless there is only one window, in which case the remainder stands alone.
    """
    if trades_per_window < 1:
        raise ValueError("trades_per_window must be >= 1")
    ordered = sorted(trades, key=lambda t: t.entry_dt)
    if not ordered:
        return []

    spans: list[list[TradeRecord]] = []
    cur: list[TradeRecord] = []
    for t in ordered:
        cur.append(t)
        if len(cur) >= trades_per_window:
            spans.append(cur)
            cur = []
    if cur:  # trailing remainder
        if spans:
            spans[-1].extend(cur)  # merge into the last full span
        else:
            spans.append(cur)

    windows: list[Window] = []
    for i, span in enumerate(spans):
        start = min(t.entry_dt for t in span)
        end = max(t.exit_dt for t in span)
        windows.append(
            Window(
                name=f"event_w{i + 1}",
                start=start.date().isoformat(),
                end=end.date().isoformat(),
            )
        )
    return windows
