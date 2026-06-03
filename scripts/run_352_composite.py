"""#352 L1 — regime-conditional composite, offline OOS-ranking grade (NO backtest).

The #353 finding: no single feature is robust across regimes, but room-to-run + return-to-support +
continuous_growth are the strongest BEAR-pair signals (they reverse in bull). This L1 step asks the
cheap, offline question that decides whether L2 (a gated backtest) is worth building:

  Does an INTERPRETABLE composite of those 3 bear features RANK winners above losers
  OUT-OF-SAMPLE within the bear regime?

It is a SELECTION RE-RANKER, not a reject gate. L1 grades RANKING power (Spearman + quartile-AUC of
composite-score vs forward FY-return on a held-out bear quarter). It never vetoes names — that is the
critical distinction from the rejected #342 index gate, which vetoed candidates in bear and killed the
winners (HOOD Jan +175). The composite would only ever re-prioritise the candidate set; here we just
measure whether that prioritisation has out-of-sample signal.

Method (overfit-guarded by construction — see regime_composite.py):
  - fit_composite on ONE bear quarter only (Q1) → frozen per-feature (mean, std, sign).
  - score + grade the OTHER bear quarter (Q4), held out — the fit never sees a test row.
  - symmetric fit-Q4 → test-Q1.
  - bull no-harm: fit on both bear quarters → score the bull quarters (Q2, Q3); expect weak/negative,
    confirming WHY the lever is gated OFF in bull (the #353 bull-reversal), not applied there.

NO look-ahead (features as-of scored date, from the #353 panel); FY-horizon label; fail-loud on a
missing trace or a degenerate fit. Usage: python3 scripts/run_352_composite.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

import run_353_manual as r353  # reuse the loader + the no-look-ahead feature panel
from regime_composite import fit_composite, oos_evaluate

# Falk's #353-proven bear cluster (the auto-panel-missed features that read correctly on HOOD-vs-MRVL).
BEAR_FEATURES = ["dist_ath", "dist_to_prior_high", "continuous_growth"]


def load_quarters() -> dict[str, list[dict]]:
    """Load the per-quarter DECISIONTRACE candidate rows (ticker, FY-label, feats). Fail-loud on a
    missing trace — never grade on a partial set."""
    perq: dict[str, list[dict]] = {}
    for q, (regime, rel) in r353._QUARTERS.items():
        log = r353._latest_log(rel)
        if log is None:
            raise SystemExit(f"{q}: no trace log under sweeps/runs/{rel} — run the trace first (fail-loud)")
        perq[q] = r353._rows(log)
    return perq


def l1_oos(perq: dict[str, list[dict]]) -> dict[str, dict]:
    """The L1 OOS-ranking grades. Pure over the loaded rows (no I/O) → unit-testable.

    Returns: {'bear_Q1_to_Q4', 'bear_Q4_to_Q1'} (the held-out bear grades) +
    {'bull_to_Q2', 'bull_to_Q3'} (the no-harm confirms: fit on both bear quarters, score each bull
    quarter). Each value is regime_composite.oos_evaluate's dict (fit / spearman / auc / n_test).
    """
    bear_all = perq["Q1"] + perq["Q4"]
    return {
        "bear_Q1_to_Q4": oos_evaluate(perq["Q1"], perq["Q4"], BEAR_FEATURES),
        "bear_Q4_to_Q1": oos_evaluate(perq["Q4"], perq["Q1"], BEAR_FEATURES),
        "bull_to_Q2": oos_evaluate(bear_all, perq["Q2"], BEAR_FEATURES),
        "bull_to_Q3": oos_evaluate(bear_all, perq["Q3"], BEAR_FEATURES),
    }


def _fmt(v: float | None) -> str:
    return f"{v:+.3f}" if v is not None else "  n/a"


def main() -> None:
    perq = load_quarters()
    for q in r353._QUARTERS:
        print(f"=== {q} ({r353._QUARTERS[q][0]}): {len(perq[q])} candidates ===", flush=True)

    res = l1_oos(perq)

    print("\n=== #352 L1 — bear-composite OUT-OF-SAMPLE ranking grade (FY label) ===")
    print(f"features (re-ranker, NOT a veto): {BEAR_FEATURES}")
    print(f"{'fit→test':18}{'regime':>8}{'Sp(OOS)':>10}{'AUC':>8}{'n_test':>8}   fit signs")
    rows = [
        ("Q1→Q4", "bear", "bear_Q1_to_Q4"),
        ("Q4→Q1", "bear", "bear_Q4_to_Q1"),
        ("Q1+Q4→Q2", "bull", "bull_to_Q2"),
        ("Q1+Q4→Q3", "bull", "bull_to_Q3"),
    ]
    for label, regime, key in rows:
        r = res[key]
        signs = {f: r["fit"].stats[f][2] for f in BEAR_FEATURES} if r.get("fit") else {}
        sign_s = " ".join(f"{f.split('_')[0]}{'+' if s >= 0 else '-'}" for f, s in signs.items())
        print(f"{label:18}{regime:>8}{_fmt(r['spearman']):>10}{_fmt(r['auc']):>8}{r['n_test']:>8}   {sign_s}")

    bear = [res["bear_Q1_to_Q4"], res["bear_Q4_to_Q1"]]
    bear_sp = [r["spearman"] for r in bear if r["spearman"] is not None]
    bear_auc = [r["auc"] for r in bear if r["auc"] is not None]
    bull = [res["bull_to_Q2"], res["bull_to_Q3"]]
    bull_sp = [r["spearman"] for r in bull if r["spearman"] is not None]

    print("\n=== L1 VERDICT ===")
    if len(bear_sp) == 2 and len(bear_auc) == 2:
        ranks_oos = all(s > 0 for s in bear_sp) and all(a > 0.5 for a in bear_auc)
        print(f"bear OOS ranking: Sp {[round(s,3) for s in bear_sp]} (need both >0), "
              f"AUC {[round(a,3) for a in bear_auc]} (need both >0.5) → "
              f"{'RANKS OOS ✓' if ranks_oos else 'does NOT rank OOS ✗'}")
    else:
        print("bear OOS ranking: insufficient data (fail)")
    if bull_sp:
        print(f"bull no-harm (fit-bear→score-bull): Sp {[round(s,3) for s in bull_sp]} "
              f"(expect weak/negative → confirms gate-OFF in bull)")
    print("\nL1 passes → bring Falk the L2 (gated-backtest floor-proxy) build decision. "
          "L1 fails → entry-lever exhausted, bank the #353 ML-vs-stop verdict.")


if __name__ == "__main__":
    main()
