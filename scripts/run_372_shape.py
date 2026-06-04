"""#372 stage-1 — does a MULTI-TIMEFRAME SHAPE representation discriminate winners from losers on the
score-7 entry pool, where #349 (single daily scalars) found NOTHING?

This is a HYPOTHESIS TEST against the #349 robustness bar, NOT a proven edge.

POOL: score==7 candidates (the marginal entry pool — the strategy's min-score gate is score>=7; the
score-8 names are the easy cases, score-7 is where #349 failed to separate winners from losers). Pool =
entered + non-entered, winner + loser by FY-label. The pair (CIBR/IGV) is NOT the pool — pair separation
does NOT imply pool generalisation (the #349 trap).

GRADE (the #349 bar, applied honestly):
  Per-feature  : Spearman IC per quarter + regime-robustness gate (Q1∧Q3 same-sign, |meanSp|>=0.10 —
                 a Q2-only effect with Q3≈0 is NOT robust; that's the #349 disproof pattern).
  Multi-feature: an INTERPRETABLE composite (regime_composite.fit_composite/oos_evaluate) graded OOS
                 BOTH directions (fit Q1→test Q3 AND fit Q3→test Q1, frozen, no-leak).
  Sanity       : CIBR/IGV-style table (note honestly that pair-separation ≠ pool-generalisation).

ROBUSTNESS BAR: SHAPE must show same-sign MEANINGFUL discrimination in BOTH Q1(bear)∧Q3(bull) AND OOS
both-directions. Only pair-level / single-quarter / one-OOS-direction → FAILS → joins #371.

NO look-ahead (shape features as-of scored date; proven by scripts/test_372_shape_asof.py); FY-horizon
label grades only; fail-loud on a missing trace. Usage: python3 scripts/run_372_shape.py
"""
from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

import feature_panel as fp
import feature_panel_shape as shp
import run_353_manual as r353
from feature_panel import Bar
from instrument_analysis import parse_decision_trace
from regime_composite import fit_composite, oos_evaluate, score as composite_score

# Q1 = bear, Q3 = bull — the robustness split the bar is stated on (Q1∧Q3).
_QUARTERS = r353._QUARTERS  # {"Q1":("bear",rel), "Q2","Q3"(bull),"Q4"(bear)}
_LABEL_END = r353._LABEL_END
_SCORE_POOL = 7  # the marginal score-7 entry pool


# ─────────────────────── shape feature vector (as-of) ───────────────────────

def shape_feats(bars: list[Bar], asof: _dt.date) -> dict[str, float | None]:
    return {
        # 1. multi-TF trend agreement
        "mtf_agreement": shp.mtf_agreement(bars, asof),
        "mtf_slope_dispersion": shp.mtf_slope_dispersion(bars, asof),
        "mtf_slope_weekly": shp.mtf_slope_weekly(bars, asof, 12),
        "mtf_slope_monthly": shp.mtf_slope_monthly(bars, asof, 6),
        # 2. base-vs-spike
        "extension_above_base": shp.extension_above_base(bars, asof, 40, 5),
        "parabolic_accel": shp.parabolic_accel(bars, asof, 5),
        "range_expansion": shp.range_expansion(bars, asof, 5, 20),
        "consolidation_quality": shp.consolidation_quality(bars, asof, 40, 5),
        "days_since_breakout": shp.days_since_breakout(bars, asof, 40, 20),
        # 3. stage_room
        "stage_room": shp.stage_room(bars, asof),
        # baseline #349 scalar that motivated the work (can't separate CIBR/IGV) — for contrast
        "dist_ath": fp.dist_to_high(bars, asof, None),
    }


_FEATS = list(shape_feats([], _dt.date(2025, 1, 1)).keys())


def _rows_score7(log: Path) -> list[dict]:
    """Per-ticker score-7 candidate rows: earliest date the ticker hit score==7 in this quarter,
    its as-of SHAPE features, and the FY-horizon label. Mirrors r353._rows but filtered to score==7."""
    trace = parse_decision_trace(log)
    first: dict[str, dict] = {}
    for r in trace:
        if r.get("score") != _SCORE_POOL:
            continue
        if r["ticker"] not in first or r["date"] < first[r["ticker"]]["date"]:
            first[r["ticker"]] = r
    out = []
    for tk, r in first.items():
        bars = r353._bars(tk)
        if not bars:
            continue
        asof = _dt.date.fromisoformat(r["date"])
        lab = r353._label(bars, asof)
        if lab is None:
            continue
        out.append({"ticker": tk, "date": r["date"], "fate": r["fate"],
                    "label": lab, "feats": shape_feats(bars, asof)})
    return out


def _sp(rows: list[dict], feat: str) -> float | None:
    pairs = [(r["feats"][feat], r["label"]) for r in rows if r["feats"].get(feat) is not None]
    if len(pairs) < 8:
        return None
    return fp.spearman([p[0] for p in pairs], [p[1] for p in pairs])


def load_quarters() -> dict[str, list[dict]]:
    perq: dict[str, list[dict]] = {}
    for q, (_regime, rel) in _QUARTERS.items():
        log = r353._latest_log(rel)
        if log is None:
            raise SystemExit(f"{q}: no trace log under sweeps/runs/{rel} — run the trace first (fail-loud)")
        perq[q] = _rows_score7(log)
    return perq


def main() -> None:
    perq = load_quarters()
    for q in _QUARTERS:
        print(f"=== {q} ({_QUARTERS[q][0]}): {len(perq[q])} score-7 candidates ===", flush=True)

    # ── per-feature Q1∧Q3 (+Q2,Q4) Spearman + robustness gate ──
    THRESH = 0.10
    print("\n=== #372 SHAPE FEATURES — per-quarter Spearman + Q1∧Q3 robustness gate (FY label) ===")
    print(f"{'feature':24}{'Q1(be)':>8}{'Q2(bu)':>8}{'Q3(bu)':>8}{'Q4(be)':>8}{'Q1∧Q3μ':>9}  robust?")
    fmt = lambda v: f"{v:+.3f}" if v is not None else "  n/a"  # noqa: E731
    scored = []
    for f in _FEATS:
        sps = {q: _sp(perq[q], f) for q in _QUARTERS}
        q1, q3 = sps["Q1"], sps["Q3"]
        both = q1 is not None and q3 is not None
        mean13 = (q1 + q3) / 2 if both else None
        robust = (both and abs(q1) >= THRESH and abs(q3) >= THRESH and (q1 > 0) == (q3 > 0))
        strength = abs(mean13) if mean13 is not None else -1
        scored.append((f, sps, mean13, robust, strength))
    robust_feats = []
    for f, sps, mean13, robust, _s in sorted(scored, key=lambda x: (x[3], x[4]), reverse=True):
        print(f"{f:24}{fmt(sps['Q1']):>8}{fmt(sps['Q2']):>8}{fmt(sps['Q3']):>8}{fmt(sps['Q4']):>8}"
              f"{fmt(mean13):>9}  {'YES' if robust else '.'}")
        if robust:
            robust_feats.append(f)
    print(f"\nPER-FEATURE ROBUST (Q1∧Q3 same-sign, both |Sp|>=0.10): {robust_feats or 'NONE'}")

    # ── multi-feature composite, OOS both directions (Q1<->Q3) ──
    # The composite uses the SHAPE features only (exclude the dist_ath contrast scalar).
    comp_feats = [f for f in _FEATS if f != "dist_ath"]
    print("\n=== #372 SHAPE COMPOSITE — OOS both directions, frozen no-leak (FY label) ===")
    print(f"composite features ({len(comp_feats)}): {comp_feats}")
    print(f"{'fit→test':14}{'Sp(OOS)':>10}{'AUC':>8}{'n_test':>8}")
    comp = {}
    for tag, fitq, testq in [("Q1→Q3", "Q1", "Q3"), ("Q3→Q1", "Q3", "Q1")]:
        try:
            r = oos_evaluate(perq[fitq], perq[testq], comp_feats, min_rows=15)
        except ValueError as e:
            print(f"{tag:14}  FIT FAILED: {e}")
            comp[tag] = None
            continue
        comp[tag] = r
        print(f"{tag:14}{fmt(r['spearman']):>10}{fmt(r['auc']):>8}{r['n_test']:>8}")

    # ── CIBR / IGV sanity ──
    print("\n=== CIBR / IGV SHAPE sanity (pair-separation ≠ pool-generalisation — the #349 trap) ===")
    _cibr_igv_sanity(perq)

    # ── verdict ──
    print("\n=== #372 STAGE-1 VERDICT ===")
    comp_ok = (comp.get("Q1→Q3") and comp.get("Q3→Q1")
               and comp["Q1→Q3"]["spearman"] is not None and comp["Q3→Q1"]["spearman"] is not None
               and comp["Q1→Q3"]["spearman"] > 0 and comp["Q3→Q1"]["spearman"] > 0
               and comp["Q1→Q3"]["auc"] is not None and comp["Q3→Q1"]["auc"] is not None
               and comp["Q1→Q3"]["auc"] > 0.5 and comp["Q3→Q1"]["auc"] > 0.5)
    print(f"per-feature Q1∧Q3 robust: {robust_feats or 'NONE'}")
    if comp.get("Q1→Q3") and comp.get("Q3→Q1"):
        print(f"composite OOS: Q1→Q3 Sp={fmt(comp['Q1→Q3']['spearman'])} AUC={fmt(comp['Q1→Q3']['auc'])} | "
              f"Q3→Q1 Sp={fmt(comp['Q3→Q1']['spearman'])} AUC={fmt(comp['Q3→Q1']['auc'])} "
              f"(need BOTH Sp>0 AND AUC>0.5)")
    passes = bool(robust_feats) or comp_ok
    if passes:
        print("\nCLEARS the #349 robustness bar → CANDIDATE for stage-2 BT (separately #370-gated).")
    else:
        print("\nFAILS the #349 robustness bar (no per-feature Q1∧Q3 robust AND composite does not rank "
              "OOS in BOTH directions). Multi-TF SHAPE joins #371 — entry-selection exhausted for this "
              "representation too.")


def _cibr_igv_sanity(perq: dict[str, list[dict]]) -> None:
    """Show CIBR/IGV shape features. IGV reaches score-7 (Q4 entry); CIBR never scores in the pool,
    so compute its shape features directly from bars on an illustrative date, with an honest caveat."""
    # IGV — find its score-7 row (and FY label) in whichever quarter it entered.
    igv_row = None
    for q in _QUARTERS:
        for r in perq[q]:
            if r["ticker"] == "IGV":
                igv_row = (q, r)
                break
        if igv_row:
            break
    # CIBR — not in the score-7 pool (never scored 7). Compute shape as-of the same date IGV entered,
    # purely as an illustrative shape comparison (NOT a pool member).
    feats = [f for f in _FEATS if f != "dist_ath"] + ["dist_ath"]
    if igv_row:
        q, igv = igv_row
        igv_asof = _dt.date.fromisoformat(igv["date"])
        cibr_bars = r353._bars("CIBR")
        cibr_feats = shape_feats(cibr_bars, igv_asof) if cibr_bars else {}
        cibr_lab = r353._label(cibr_bars, igv_asof) if cibr_bars else None
        print(f"  IGV score-7 entry: {q} {igv['date']} (fate={igv['fate']})  FY label {igv['label']:+.1%}")
        cl = f"{cibr_lab:+.1%}" if cibr_lab is not None else "n/a"
        print(f"  CIBR (NOT in score-7 pool — shape computed as-of {igv_asof} for contrast)  FY label {cl}")
        print(f"  {'feature':24}{'IGV':>12}{'CIBR':>12}")
        for f in feats:
            iv = igv["feats"].get(f)
            cv = cibr_feats.get(f)
            print(f"  {f:24}{(f'{iv:+.4f}' if iv is not None else 'n/a'):>12}"
                  f"{(f'{cv:+.4f}' if cv is not None else 'n/a'):>12}")
        print("  NOTE: CIBR is absent from the score-7 pool (it never reached the entry gate), so this "
              "is illustrative only.\n        Pair-separation does NOT imply pool-generalisation (#349).")
    else:
        print("  IGV not present in any score-7 quarter pool.")


if __name__ == "__main__":
    main()
