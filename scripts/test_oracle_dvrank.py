"""#322 LEARNED-SIGNAL local test — DvRankPredictor vs plain-screen baseline (2021-2025 substrate).

The phase-1 mine found the DV-rank edge; this BUILDS a signal from it (DvRankPredictor: BCT pool +
DV-rank edge) and SEES IF IT BEATS the baseline (plain score≥7) — on the committed 2021-2025 traded
substrate, no cloud, no paste. The test drives the ACTUAL predictor code (imported from the
OracleSignal phase) over each trade's committed features, then compares the outcomes of the trades
the predictor FIRES vs the full screened set.

Selection-test semantics: the substrate = the names the plain screen ALREADY traded (all score≥7).
The DV-rank signal fires a SUBSET (rank ≤ rank_cap). So the question is: does that subset have a
better win-rate / mean-ret than the full set? (A real signal also changes which names enter on
cloud; this committed-data test isolates the SELECTION effect — the honest first-cut, hypothesis-
grade. Rigorous confirmation needs the counterfactual = Falk's paste.)

Outcome (survivorship-aware, == the mine): realized ret (closed) | m2m_ret (censored). Only
2021-2025 (FY2018-20 dropped — no censored m2m). Trades with no decision_rank are excluded (the
edge can't be evaluated). Read-only over the committed archive.
"""
import glob
import gzip
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "src")]
from phases.signal.oracle_signal.oracle_signal import (  # noqa: E402
    CandidateFeatures,
    DvRankPredictor,
)

ARCHIVE = _ROOT / "results" / "archive" / "fd8248b34265"
VALID = {"2021", "2022", "2023", "2024", "2025"}


def _yr(t):
    return str(t.get("entry_dt", ""))[:4]


def _outcome(t):
    return t.get("ret") if not t.get("censored") else t.get("m2m_ret")


def _features(t):
    """Build the CandidateFeatures the predictor consumes from a committed trade row."""
    conds = tuple(bool(t.get(f"cond_{i}")) for i in range(8))
    return CandidateFeatures(
        ticker=t.get("symbol", ""),
        price=float(t.get("entry_px") or 0.0),
        conditions=conds,
        bct_score=int(t.get("decision_score") or 0),
        roc13=None,
        dollar_vol=0.0,
        rank=int(t["decision_rank"]),
    )


def load():
    rows = []
    for tj in glob.glob(str(ARCHIVE / "*" / "trades.jsonl.gz")):
        with gzip.open(tj, "rt") as f:
            for line in f:
                t = json.loads(line)
                if (t.get("context_status") == "OK" and _yr(t) in VALID
                        and _outcome(t) is not None and t.get("decision_rank") is not None):
                    rows.append(t)
    return rows


def metrics(trades):
    if not trades:
        return (0, 0.0, 0.0)
    outs = [_outcome(t) for t in trades]
    wr = sum(1 for o in outs if o > 0) / len(outs) * 100
    return (len(trades), wr, st.mean(outs) * 100)


def main():
    rows = load()
    base_n, base_wr, base_ret = metrics(rows)
    print(f"BASELINE (plain score≥7, all rank-known 2021-2025): n={base_n}  win-rate={base_wr:.0f}%  mean_ret={base_ret:+.1f}%\n")

    print("DvRankPredictor — fired subset vs baseline, sweeping rank_cap:")
    print(f"  {'rank_cap':>8} {'n_fired':>7} {'win%':>6} {'mean_ret%':>9}  {'Δwin':>6} {'Δret':>6}")
    for cap in (100, 150, 200, 250, 300, 400, 500):
        pred = DvRankPredictor(min_score=7, rank_cap=cap)
        fired = [t for t in rows if pred.predict(_features(t)).fire]
        n, wr, ret = metrics(fired)
        print(f"  {cap:>8} {n:>7} {wr:>5.0f}% {ret:>+8.1f}%  {wr-base_wr:>+5.0f} {ret-base_ret:>+5.1f}")

    # per-regime at a representative cap (the median-ish DV ceiling)
    CAP = 250
    print(f"\nper-regime @ rank_cap={CAP} (DV-signal fired vs that regime's baseline):")
    pred = DvRankPredictor(min_score=7, rank_cap=CAP)
    by = defaultdict(lambda: ([], []))
    for t in rows:
        by[_yr(t)][0].append(t)
        if pred.predict(_features(t)).fire:
            by[_yr(t)][1].append(t)
    for yr in sorted(by):
        allt, fired = by[yr]
        bn, bwr, bret = metrics(allt)
        fn, fwr, fret = metrics(fired)
        print(f"  {yr}: baseline n={bn} win={bwr:.0f}% ret={bret:+.1f}%  →  DV-signal n={fn} win={fwr:.0f}% ret={fret:+.1f}%  (Δwin {fwr-bwr:+.0f}pp, Δret {fret-bret:+.1f}pp)")


if __name__ == "__main__":
    main()
