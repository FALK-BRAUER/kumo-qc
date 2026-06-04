"""P1 hard-stop — runner-survival + loser-tail-cut per X (the second half of the deliverable).

A hard-stop WINS only if it cuts the realized-loser tail (MRVL/UAL-type closers) WITHOUT clipping the
runners (HOOD/KGC ran +175/+166 through en-route drawdowns). This reads each X's FY-full trade ledger
and reports, per X:
  - closed-loser tail: count + summed pnl of CLOSED losing trades (the tail the stop should cut)
  - winner pnl + censored (held-to-year-end = still-running winners)
  - RUNNER SURVIVAL: HOOD/KGC — did they stay held (censored=run-to-EOY = SURVIVED) or exit early via the
    stop (exit_reason set, earlier exit_dt = CLIPPED)? + their ret / mae (max adverse excursion en route).

mae is the tell: a name whose baseline mae <= -X would be clipped by the -X stop. The X-run ledger
confirms the actual outcome. Pending X (not yet run) are noted, not faked.

Usage: python3 scripts/hardstop_survival.py
"""
from __future__ import annotations

import datetime as _dt
import glob
import gzip
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
HASHES = {0.0: "65c0cf447168", 0.08: "691e18c60b27", 0.12: "b25cbe90de6d",
          0.15: "dec3db2384e0", 0.20: "f0a005b6ee33"}
RUNNERS = ("HOOD", "KGC")


def _fy_ledger(h: str) -> list[dict] | None:
    """Latest-mtime trades.jsonl.gz for hash h whose trade span looks FY-full (>180d). None if none."""
    cands = sorted(glob.glob(str(_ROOT / "results" / "archive" / h / "*" / "trades.jsonl.gz")),
                   key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for p in cands:
        rows = [json.loads(x) for x in gzip.decompress(Path(p).read_bytes()).decode().splitlines()]
        if not rows:
            continue
        ds = [_dt.date.fromisoformat(r["entry_dt"][:10]) for r in rows if r.get("entry_dt")]
        if ds and (max(ds) - min(ds)).days > 180:  # FY-full span (a quarter would be ~90d)
            return rows
    return None


def _summarize(rows: list[dict]) -> dict:
    closed = [r for r in rows if not r.get("censored")]
    losers = [r for r in closed if (r.get("ret") or 0) < 0]
    winners = [r for r in closed if (r.get("ret") or 0) > 0]
    censored = [r for r in rows if r.get("censored")]
    return {
        "n": len(rows), "closed": len(closed), "censored": len(censored),
        "closed_losers": len(losers), "closed_loser_pnl": sum(r.get("pnl") or 0 for r in losers),
        "closed_winners": len(winners), "closed_winner_pnl": sum(r.get("pnl") or 0 for r in winners),
        "censored_pnl": sum(r.get("pnl") or 0 for r in censored),
    }


def _runner_rows(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for r in rows:
        if r.get("symbol", "").upper() in RUNNERS:
            sym = r["symbol"].upper()
            # keep the largest-pnl leg per runner (the main position, not a tiny re-entry)
            if sym not in out or abs(r.get("pnl") or 0) > abs(out[sym].get("pnl") or 0):
                out[sym] = r
    return out


def main() -> None:
    print("=== P1 HARD-STOP — runner-survival + loser-tail-cut per X ===\n")
    print(f"  {'X':>6} {'trades':>7} {'closed':>7} {'cens':>5} {'closeLoss':>10} {'lossPnl$':>11} "
          f"{'winPnl$':>11} {'censPnl$':>11}")
    ledgers = {}
    for x, h in HASHES.items():
        rows = _fy_ledger(h)
        ledgers[x] = rows
        tag = "base" if x == 0.0 else f"-{int(x*100)}%"
        if rows is None:
            print(f"  {tag:>6}  (pending — no FY ledger for {h} yet)")
            continue
        s = _summarize(rows)
        print(f"  {tag:>6} {s['n']:>7} {s['closed']:>7} {s['censored']:>5} {s['closed_losers']:>10} "
              f"{s['closed_loser_pnl']:>+11.0f} {s['closed_winner_pnl']:>+11.0f} {s['censored_pnl']:>+11.0f}")

    print("\n=== RUNNER SURVIVAL — HOOD / KGC per X (censored=held-to-EOY=SURVIVED; exit_reason=CLIPPED) ===")
    for x, h in HASHES.items():
        rows = ledgers.get(x)
        tag = "base" if x == 0.0 else f"-{int(x*100)}%"
        if rows is None:
            continue
        rr = _runner_rows(rows)
        for sym in RUNNERS:
            r = rr.get(sym)
            if not r:
                print(f"  X={tag:>5} {sym}: (not in pool)")
                continue
            surv = "SURVIVED(EOY)" if r.get("censored") else f"CLIPPED({r.get('exit_reason')})"
            mae = r.get("mae")
            print(f"  X={tag:>5} {sym}: ret={(r.get('ret') or 0):+.1%} pnl={r.get('pnl') or 0:+.0f} "
                  f"mae={mae if mae is None else f'{mae:+.1%}'} exit={r.get('exit_dt','?')[:10]} → {surv}")
    print("\nVERDICT RULE: a winning X cuts closed-loser-pnl (less negative) + KEEPS HOOD/KGC censored "
          "(survived). If HOOD/KGC flip to CLIPPED at some X → that X clips the runners (too tight).")


if __name__ == "__main__":
    main()
