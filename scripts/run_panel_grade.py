"""#349 feature-panel RUNNER — grade every feature's winner/loser discrimination on Q1 + Q3.

Loads the DECISIONTRACE scored candidates (entered + non-entered) from the S1-base trace logs (Q1 =
the sample run; Q3 = the V1 run — signal-identical scored set, the SIGNAL phase is unchanged), computes
the feature_panel AS-OF each candidate's first-scored date from the daily zips (+ SPY for RS), labels
each with forward return (scored-date close → window-end close), grades each feature (Spearman + top/
bottom-quartile AUC) per window, applies the ROBUSTNESS GATE (consistent sign + separation in BOTH Q1
AND Q3), and prints the ranked table + the explicit HOOD-vs-MRVL verdict.

NO look-ahead: features as-of the scored date (feature_panel enforces); forward-return grades only.
Fail-loud: a feature that is None for a candidate is dropped from THAT feature's sample (counted), never
imputed. Usage: python3 scripts/run_panel_grade.py
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

import feature_panel as fp
from feature_panel import Bar
from instrument_analysis import parse_decision_trace
from sweeps.warmup_cache.table_builder import read_daily_zip

_DAILY = Path("/Users/falk/projects/kumo-qc/data/equity/usa/daily")
# Candidate SETS come from each window's trace; the LABEL horizon is FY-end (entry → year-end 2025) —
# the TRUE multi-month let-winners-run outcome, NOT the window-truncated stub (HQ #349: the window
# label censored HOOD at +5.5% vs its +175% FY run — re-grade on the real horizon).
_LABEL_END = _dt.date(2025, 12, 31)
_WINDOWS = {
    "Q1": Path("sweeps/runs/65c0cf447168/w1_2025q1/backtests/2026-06-03_13-31-12/log.txt"),
    "Q3": Path("sweeps/runs/a8c1014476af/w3_2025q3/backtests/2026-06-03_14-02-30/log.txt"),
}


def _bars(ticker: str) -> list[Bar]:
    zp = _DAILY / f"{ticker.lower()}.zip"
    if not zp.exists():
        return []
    return [Bar(d, o, h, l, c, v) for d, o, h, l, c, v in read_daily_zip(zp)]


_SPY = _bars("SPY")


def _features(bars: list[Bar], asof: _dt.date, score: int | None) -> dict[str, float | None]:
    sl = fp.trend_slope_r2(bars, asof, 63)
    return {
        "roc63": fp.roc(bars, asof, 63),
        "dist_52wk_high": fp.dist_to_high(bars, asof, 252),
        "dist_ath": fp.dist_to_high(bars, asof, None),
        "daily_open_close": fp.daily_open_close(bars, asof),
        "gap": fp.gap(bars, asof),
        "volume_surge": fp.volume_surge(bars, asof, 20),
        "trend_persistence": fp.trend_persistence(bars, asof, 20),
        "trend_slope": None if sl is None else sl[0],
        "trend_r2": None if sl is None else sl[1],
        "rs_spy_20d": fp.rs_vs_benchmark(bars, _SPY, asof, 20),
        "rs_spy_60d": fp.rs_vs_benchmark(bars, _SPY, asof, 60),
        "liquidity": fp.liquidity_dollar_vol(bars, asof, 20),
        "price_level": fp.price_level(bars, asof),
        "name_ichimoku_pos": fp.ichimoku_cloud_pos(bars, asof),
        "weekly_ichimoku_pos": fp.weekly_ichimoku_pos(bars, asof),
        "decision_score": float(score) if score is not None else None,
    }


def _label(bars: list[Bar], asof: _dt.date, wend: _dt.date) -> float | None:
    """Forward return: close on/after asof → close at/just-before window end."""
    w = [b for b in bars if b.d <= wend]
    a = [b for b in w if b.d <= asof]
    if not a or not w or a[-1].c <= 0:
        return None
    return w[-1].c / a[-1].c - 1.0


def _candidates(log: Path, wend: _dt.date):
    """First-scored (ticker → date, score). Compute features + label per candidate."""
    trace = parse_decision_trace(log)
    first: dict[str, dict] = {}
    for r in trace:
        tk = r["ticker"]
        if tk not in first or r["date"] < first[tk]["date"]:
            first[tk] = r
    rows = []
    for tk, r in first.items():
        bars = _bars(tk)
        if not bars:
            continue
        asof = _dt.date.fromisoformat(r["date"])
        lab = _label(bars, asof, wend)
        if lab is None:
            continue
        feats = _features(bars, asof, r["score"])
        rows.append({"ticker": tk, "date": r["date"], "label": lab, "feats": feats})
    return rows


def _grade(rows: list[dict], feat: str):
    pairs = [(r["feats"][feat], r["label"]) for r in rows if r["feats"].get(feat) is not None]
    if len(pairs) < 8:
        return None, None, len(pairs)
    fv = [p[0] for p in pairs]
    lv = [p[1] for p in pairs]
    return fp.spearman(fv, lv), fp.quartile_auc(fv, lv), len(pairs)


def main() -> None:
    feats = list(_features([], _dt.date(2025, 1, 1), 7).keys())
    graded: dict[str, dict] = {}
    per_window = {}
    for wname, log in _WINDOWS.items():
        rows = _candidates(log, _LABEL_END)
        per_window[wname] = rows
        print(f"=== {wname}: {len(rows)} candidates with features+label ===", flush=True)
        for f in feats:
            sp, auc, n = _grade(rows, f)
            graded.setdefault(f, {})[wname] = (sp, auc, n)

    THRESH = 0.10  # |spearman| robustness threshold
    print("\n=== RANKED FEATURE TABLE (robustness gate = both Q1 AND Q3, |spearman|>=0.10, same sign) ===")
    print(f"{'feature':20}{'Q1_sp':>8}{'Q1_auc':>8}{'Q3_sp':>8}{'Q3_auc':>8}  both?")
    scored = []
    for f in feats:
        q1 = graded[f].get("Q1", (None, None, 0))
        q3 = graded[f].get("Q3", (None, None, 0))
        sp1, sp3 = q1[0], q3[0]
        both = (sp1 is not None and sp3 is not None and abs(sp1) >= THRESH and abs(sp3) >= THRESH
                and (sp1 > 0) == (sp3 > 0))
        strength = (abs(sp1) + abs(sp3)) / 2 if (sp1 is not None and sp3 is not None) else -1
        scored.append((f, sp1, q1[1], sp3, q3[1], both, strength))
    for f, sp1, a1, sp3, a3, both, _s in sorted(scored, key=lambda x: (x[5], x[6]), reverse=True):
        fmt = lambda v: f"{v:+.3f}" if v is not None else "  n/a"  # noqa: E731
        print(f"{f:20}{fmt(sp1):>8}{fmt(a1):>8}{fmt(sp3):>8}{fmt(a3):>8}  {'YES' if both else '.'}")

    robust = [s[0] for s in scored if s[5]]
    print(f"\nROBUST discriminators (both regimes): {robust or 'NONE'}")

    # HOOD vs MRVL (Q1) — does any feature separate them?
    q1rows = {r["ticker"]: r for r in per_window["Q1"]}
    h = q1rows.get("HOOD") or q1rows.get("hood")
    m = q1rows.get("MRVL") or q1rows.get("mrvl")
    print("\n=== HOOD vs MRVL @ entry (Q1) — does ANY feature separate the +175% winner from the -37% loser? ===")
    if h and m:
        print(f"  label: HOOD {h['label']:+.2%}  MRVL {m['label']:+.2%}")
        print(f"  {'feature':20}{'HOOD':>12}{'MRVL':>12}  separates(in robust dir)?")
        for f in feats:
            hv, mv = h["feats"].get(f), m["feats"].get(f)
            sep = "" if (hv is None or mv is None) else ("DIFF" if abs(hv - mv) > 1e-9 else "same")
            hs = f"{hv:+.4f}" if hv is not None else "n/a"
            ms = f"{mv:+.4f}" if mv is not None else "n/a"
            print(f"  {f:20}{hs:>12}{ms:>12}  {sep}")
    else:
        print("  HOOD/MRVL not both in the Q1 candidate set — cannot compare.")


if __name__ == "__main__":
    main()
