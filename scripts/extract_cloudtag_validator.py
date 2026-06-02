"""Extract the CLOUD-SIDE of the (c) primary validator (HQ 2026-06-02).

The #303 mine's phase-2 counterfactual is scored by the lab from its 5-min substrate (one
consistent vendor — the local-daily generator is DEAD, over-counts ~6x). To keep that honest,
the MANDATORY validator cross-checks the lab's 5-min 8-condition score against the CLOUD-TAG's
score on the traded names (the only names with a deployed-cloud ground truth). The cloud-tag
conditions live per-row in each run's trades.jsonl.gz (cond_0..7, decision_score). This flattens
them across all committed regimes into one joinable table so the cross-check is a single join,
not a re-dig.

Output: results/archive/<config_hash>/cloudtag_validator.csv — one row per traded name per run,
the cloud-side ground truth the lab joins its 5-min scores against. Re-runnable; reads only the
committed archive (no cloud, no network).
"""
import csv, gzip, json, sys
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "results" / "archive"
COND = [f"cond_{i}" for i in range(8)]
COLS = (["backtest_id", "symbol", "entry_dt", "year", "decision_score", *COND,
         "decision_gap", "decision_vol", "decision_rank", "decision_tdist",
         "exit_reason", "censored", "context_status", "ret", "pnl", "m2m_ret", "m2m_source"])


def _year(entry_dt):
    if not entry_dt:
        return ""
    return str(entry_dt)[:4]


def extract(config_hash):
    root = ARCHIVE / config_hash
    if not root.is_dir():
        raise SystemExit(f"no archive dir for config_hash {config_hash}: {root}")
    rows = []
    skipped_dirs, bad_lines = [], 0
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        tj = run_dir / "trades.jsonl.gz"
        if not tj.exists():
            skipped_dirs.append(run_dir.name)
            continue
        bid = run_dir.name
        with gzip.open(tj, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    # one malformed row must not zero the whole table — skip + count, never crash
                    bad_lines += 1
                    continue
                rows.append({
                    "backtest_id": bid,
                    "symbol": t.get("symbol", ""),
                    "entry_dt": t.get("entry_dt", ""),
                    "year": _year(t.get("entry_dt")),
                    "decision_score": t.get("decision_score", ""),
                    **{c: t.get(c, "") for c in COND},
                    "decision_gap": t.get("decision_gap", ""),
                    "decision_vol": t.get("decision_vol", ""),
                    "decision_rank": t.get("decision_rank", ""),
                    "decision_tdist": t.get("decision_tdist", ""),
                    "exit_reason": t.get("exit_reason", ""),
                    "censored": t.get("censored", ""),
                    "context_status": t.get("context_status", ""),
                    "ret": t.get("ret", ""),
                    "pnl": t.get("pnl", ""),
                    "m2m_ret": t.get("m2m_ret", ""),
                    "m2m_source": t.get("m2m_source", ""),
                })
    out = root / "cloudtag_validator.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    n_ok = sum(1 for r in rows if r["context_status"] == "OK")
    years = sorted({r["year"] for r in rows if r["year"]})
    print(f"wrote {out}: {len(rows)} traded rows ({n_ok} context_status==OK) across years {years}")
    if skipped_dirs:
        print(f"  skipped {len(skipped_dirs)} dir(s) with no trades.jsonl.gz: {skipped_dirs}")
    if bad_lines:
        print(f"  WARNING: skipped {bad_lines} malformed JSONL line(s)")
    return out


if __name__ == "__main__":
    extract(sys.argv[1] if len(sys.argv) > 1 else "fd8248b34265")
