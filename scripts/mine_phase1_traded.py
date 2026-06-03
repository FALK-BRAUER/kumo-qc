"""#303 phase-1 FIRST-CUT mine on the TRADED substrate (winners-vs-losers).

Unblocked goal-work: the committed 8-regime traded set (results/archive/<hash>/*/trades.jsonl.gz)
already carries per-trade cloud-tag context (decision_score, cond_0..7, gap, vol, tdist, rank) +
outcomes — so the phase-1 question (which conditions/context separate winning trades from losing
ones) is answerable NOW, without the lab's Falk-gated 5-min phase-2 counterfactual. This is a
FIRST-CUT to hand the lab/Falk a head-start; hzgffl24 owns the rigorous version + the untraded
counterfactual.

SURVIVORSHIP HANDLING (the trap): closed-only is loser-biased (winners ride open via protective
stops → land as censored). Outcome = realized ret (closed) OR m2m_ret (censored, provisional).
A regime whose censored trades LACK m2m (FY2018-2020 — local daily absent) drops its open winners
→ artificial ~0% win-rate. So such regimes are EXCLUDED from the winner/loser analysis (entry-
context only). Read-only over the committed archive.
"""
import glob
import gzip
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "results" / "archive" / "fd8248b34265"


def _yr(t):
    return str(t.get("entry_dt", ""))[:4]


def _outcome(t):
    return t.get("ret") if not t.get("censored") else t.get("m2m_ret")


def load():
    rows = []
    for tj in glob.glob(str(ARCHIVE / "*" / "trades.jsonl.gz")):
        with gzip.open(tj, "rt") as f:
            for line in f:
                t = json.loads(line)
                if t.get("context_status") == "OK":
                    rows.append(t)
    return rows


def valid_regimes(rows):
    """A regime is valid for outcome analysis iff ALL its censored trades carry m2m (else the open
    winners are dropped = survivorship bias)."""
    cens = defaultdict(lambda: [0, 0])
    for t in rows:
        if t.get("censored"):
            cens[_yr(t)][0] += 1
            if t.get("m2m_ret") is not None:
                cens[_yr(t)][1] += 1
    return {y for y, (tot, have) in cens.items() if tot == have}, cens


def main():
    rows = load()
    valid, cens = valid_regimes(rows)
    print("censored m2m coverage by year:", {y: f"{h}/{t}" for y, (t, h) in sorted(cens.items())})
    print("VALID regimes (censored fully marked):", sorted(valid))
    lab = [(t, _outcome(t)) for t in rows if _yr(t) in valid and _outcome(t) is not None]
    W = [t for t, o in lab if o > 0]
    L = [t for t, o in lab if o <= 0]
    print(f"\nvalid-subset labeled: {len(lab)}  WINNERS {len(W)} ({len(W)/len(lab)*100:.0f}%)  LOSERS {len(L)}")

    print("\n=== feature separation (winner vs loser) ===")
    for f in ("decision_rank", "decision_gap", "decision_vol", "decision_tdist", "decision_score"):
        wv = [t[f] for t in W if t.get(f) is not None]
        lv = [t[f] for t in L if t.get(f) is not None]
        if wv and lv:
            print(f"  {f:15s} W_med={st.median(wv):+.3f} L_med={st.median(lv):+.3f}")

    print("\n=== 8-cond hit-rate — do George's conditions separate? ===")
    for i in range(8):
        wt = sum(1 for t in W if t.get(f"cond_{i}"))
        lt = sum(1 for t in L if t.get(f"cond_{i}"))
        print(f"  cond_{i}  W={wt/len(W)*100:.0f}%  L={lt/len(L)*100:.0f}%  Δ={wt/len(W)*100-lt/len(L)*100:+.0f}pp")

    print("\n=== rank-tercile win-rate (the candidate edge) ===")
    ranked = sorted(((t, o) for t, o in lab if t.get("decision_rank") is not None),
                    key=lambda x: x[0]["decision_rank"])
    th = len(ranked) // 3
    for name, seg in [("top-DV", ranked[:th]), ("mid", ranked[th:2 * th]), ("low-DV", ranked[2 * th:])]:
        wr = sum(1 for _, o in seg if o > 0) / len(seg) * 100
        print(f"  {name:8s} n={len(seg)} win-rate={wr:.0f}% mean_ret={st.mean([o for _, o in seg])*100:+.1f}%")


if __name__ == "__main__":
    main()
