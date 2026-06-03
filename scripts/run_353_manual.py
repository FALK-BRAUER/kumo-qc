"""#353 manual-feature grader — Falk's discretionary checklist, FY-label, regime-robustness (4 quarters).

Loads the DECISIONTRACE scored candidates from all 4 quarters (S1-base, signal-identical), computes the
FULL feature panel INCLUDING the panel-missed manual features (continuous_growth, dist_to_prior_high,
monthly momentum roc126/roc252) as-of each candidate's scored date, labels with FY-horizon return
(entry→year-end), grades per quarter (Spearman), and applies the REGIME-ROBUSTNESS gate: a feature
counts only if it discriminates with a CONSISTENT SIGN in BOTH the bear pair (Q1,Q4) AND the bull pair
(Q2,Q3). Reports the ranked manual-feature table + HOOD-vs-MRVL per feature.

NO look-ahead (features as-of scored date); FY-label grades only; fail-loud on missing data.
Usage: python3 scripts/run_353_manual.py
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
_LABEL_END = _dt.date(2025, 12, 31)
# (window → trace log). bear = Q1,Q4 ; bull = Q2,Q3 (the #349 robustness split).
_QUARTERS = {
    "Q1": ("bear", "65c0cf447168/w1_2025q1"),
    "Q2": ("bull", "65c0cf447168/w2_2025q2"),
    "Q3": ("bull", "a8c1014476af/w3_2025q3"),
    "Q4": ("bear", "65c0cf447168/w4_2025q4"),
}


def _latest_log(rel: str) -> Path | None:
    cands = sorted(Path("sweeps/runs", rel, "backtests").glob("*/log.txt"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _bars(t: str) -> list[Bar]:
    zp = _DAILY / f"{t.lower()}.zip"
    return [Bar(d, o, h, l, c, v) for d, o, h, l, c, v in read_daily_zip(zp)] if zp.exists() else []


_SPY = _bars("SPY")


def _features(bars: list[Bar], asof: _dt.date, score: int | None) -> dict[str, float | None]:
    sl = fp.trend_slope_r2(bars, asof, 63)
    return {
        # --- Falk's panel-MISSED manual features (the #353 focus) ---
        "continuous_growth": fp.continuous_growth(bars, asof, 12),
        "dist_to_prior_high": fp.dist_to_prior_high(bars, asof, 12, 2),
        "monthly_mom_6m": fp.roc(bars, asof, 126),
        "monthly_mom_12m": fp.roc(bars, asof, 252),
        # --- reused #349 panel ---
        "roc63": fp.roc(bars, asof, 63),
        "dist_52wk_high": fp.dist_to_high(bars, asof, 252),
        "dist_ath": fp.dist_to_high(bars, asof, None),
        "weekly_ichimoku_pos": fp.weekly_ichimoku_pos(bars, asof),
        "name_ichimoku_pos": fp.ichimoku_cloud_pos(bars, asof),
        "rs_spy_60d": fp.rs_vs_benchmark(bars, _SPY, asof, 60),
        "gap": fp.gap(bars, asof),
        "volume_surge": fp.volume_surge(bars, asof, 20),
        "trend_persistence": fp.trend_persistence(bars, asof, 20),
        "liquidity": fp.liquidity_dollar_vol(bars, asof, 20),
        "decision_score": float(score) if score is not None else None,
    }


def _label(bars: list[Bar], asof: _dt.date) -> float | None:
    w = [b for b in bars if b.d <= _LABEL_END]
    a = [b for b in w if b.d <= asof]
    if not a or not w or a[-1].c <= 0:
        return None
    return w[-1].c / a[-1].c - 1.0


def _rows(log: Path):
    trace = parse_decision_trace(log)
    first: dict[str, dict] = {}
    for r in trace:
        if r["ticker"] not in first or r["date"] < first[r["ticker"]]["date"]:
            first[r["ticker"]] = r
    out = []
    for tk, r in first.items():
        bars = _bars(tk)
        if not bars:
            continue
        asof = _dt.date.fromisoformat(r["date"])
        lab = _label(bars, asof)
        if lab is None:
            continue
        out.append({"ticker": tk, "label": lab, "feats": _features(bars, asof, r["score"])})
    return out


def _sp(rows, feat):
    pairs = [(r["feats"][feat], r["label"]) for r in rows if r["feats"].get(feat) is not None]
    if len(pairs) < 8:
        return None
    return fp.spearman([p[0] for p in pairs], [p[1] for p in pairs])


def main() -> None:
    feats = list(_features([], _dt.date(2025, 1, 1), 7).keys())
    perq = {}
    for q, (regime, rel) in _QUARTERS.items():
        log = _latest_log(rel)
        if log is None:
            raise SystemExit(f"{q}: no trace log under sweeps/runs/{rel} — run the trace first (fail-loud)")
        rows = _rows(log)
        perq[q] = rows
        print(f"=== {q} ({regime}): {len(rows)} candidates ===", flush=True)

    THRESH = 0.10
    scored = []
    for f in feats:
        sps = {q: _sp(perq[q], f) for q in _QUARTERS}
        bear = [sps["Q1"], sps["Q4"]]
        bull = [sps["Q2"], sps["Q3"]]
        bear_mean = sum(bear) / 2 if all(v is not None for v in bear) else None
        bull_mean = sum(bull) / 2 if all(v is not None for v in bull) else None
        robust = (bear_mean is not None and bull_mean is not None
                  and abs(bear_mean) >= THRESH and abs(bull_mean) >= THRESH
                  and (bear_mean > 0) == (bull_mean > 0))
        strength = (abs(bear_mean) + abs(bull_mean)) / 2 if (bear_mean is not None and bull_mean is not None) else -1
        scored.append((f, sps, bear_mean, bull_mean, robust, strength))

    print("\n=== #353 MANUAL FEATURES — per-quarter Spearman + regime-robustness (FY label) ===")
    print(f"{'feature':20}{'Q1(be)':>8}{'Q2(bu)':>8}{'Q3(bu)':>8}{'Q4(be)':>8}{'bearμ':>8}{'bullμ':>8}  robust?")
    fmt = lambda v: f"{v:+.3f}" if v is not None else "  n/a"  # noqa: E731
    for f, sps, bm, lm, robust, _s in sorted(scored, key=lambda x: (x[4], x[5]), reverse=True):
        print(f"{f:20}{fmt(sps['Q1']):>8}{fmt(sps['Q2']):>8}{fmt(sps['Q3']):>8}{fmt(sps['Q4']):>8}"
              f"{fmt(bm):>8}{fmt(lm):>8}  {'YES' if robust else '.'}")
    robust = [s[0] for s in scored if s[4]]
    print(f"\nROBUST (both regimes, |meanSp|>=0.10, same sign): {robust or 'NONE'}")

    # HOOD vs MRVL (Q1) with the manual features
    q1 = {r["ticker"]: r for r in perq["Q1"]}
    h, m = q1.get("HOOD"), q1.get("MRVL")
    print("\n=== HOOD vs MRVL @ Q1 entry (manual features) ===")
    if h and m:
        print(f"  FY label: HOOD {h['label']:+.1%}  MRVL {m['label']:+.1%}")
        for f in feats:
            hv, mv = h["feats"].get(f), m["feats"].get(f)
            hs = f"{hv:+.4f}" if hv is not None else "n/a"
            ms = f"{mv:+.4f}" if mv is not None else "n/a"
            print(f"  {f:20}{hs:>12}{ms:>12}")
    else:
        print("  HOOD/MRVL not both present.")


if __name__ == "__main__":
    main()
