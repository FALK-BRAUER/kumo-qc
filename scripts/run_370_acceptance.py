"""#370 acceptance — per window: trim+cache must (1) run ZERO WeeklyCacheGapError (crash-free, the NEW
property the complete cache unlocks) AND (2) produce BYTE-IDENTICAL orders to the full-warmup baseline
(parity — the newly-runnable crash-windows trade CORRECTLY, not just present).

MERGE GATE (HQ): crash-free-all-6 + byte-identical on the previously-CRASHING windows (Q1 = NVD@02-18,
the decisive one — it NEVER ran trim+cache before). Priority order runs FY + Q1 FIRST so the decisive
Q1-byte-identical lands ASAP; the rest confirm.

Per window, SEQUENTIAL (full-warmup baseline is cap-1 4.3GB): run S1 full-warmup (560) → baseline fills;
run S1 trim+cache (320, cache-armed) → trim fills + scan its log for WeeklyCacheGapError; compare.

Usage: python3 scripts/run_370_acceptance.py [window ...]   (default: fy q1 q3 q2 q4 w5 w6 — gate order)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
import os
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import PhaseChoice, SweepConfig, Window  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

_S1 = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)
BASELINE = SweepConfig(choices=_S1, continuous_weekly=True)                  # warmup_days=560 default
TRIM = SweepConfig(choices=_S1, continuous_weekly=True, warmup_days=320)     # trim+cache (armed <560)
_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"

FY = Window(name="fy2025_full", start="2025-01-01", end="2025-12-31")
_BY_NAME = {w.name: w for w in SIX_WINDOWS}
# gate-priority order: FY + Q1 (the decisive crash-window) first
_ALIAS = {"fy": FY, "q1": _BY_NAME["w1_2025q1"], "q2": _BY_NAME["w2_2025q2"],
          "q3": _BY_NAME["w3_2025q3"], "q4": _BY_NAME["w4_2025q4"],
          "w5": _BY_NAME["w5_2026q1"], "w6": _BY_NAME["w6_2026_feb_apr"]}
_DEFAULT = ["fy", "q1", "q3", "q2", "q4", "w5", "w6"]


def _fills(run_dir: Path) -> list[tuple]:
    """Sorted (symbol, time, fill_qty, fill_price) from the latest backtest's order-events."""
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not bts:
        return []
    oe = next(bts[0].glob("*-order-events.json"), None)
    if oe is None:
        return []
    ev = json.loads(oe.read_text())
    ev = ev.get("orderEvents", ev) if isinstance(ev, dict) else ev
    out = []
    for e in ev:
        if str(e.get("status", "")).lower() not in ("filled", "partiallyfilled"):
            continue
        s = e.get("symbol", {}); s = s.get("value", s) if isinstance(s, dict) else s
        out.append((str(s), str(e.get("time", e.get("utcTime", ""))),
                    round(float(e.get("fillQuantity", 0)), 6), round(float(e.get("fillPrice", 0)), 4)))
    out.sort()
    return out


def _threw(run_dir: Path) -> bool:
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not bts:
        return False
    # scan ALL text artifacts (not just *log*.txt) so a differently-named crash log can't hide a throw
    for p in bts[0].rglob("*"):
        if p.is_file() and p.suffix in (".txt", ".log", ".json"):
            try:
                if "WeeklyCacheGapError" in p.read_text(errors="ignore"):
                    return True
            except OSError:
                continue
    return False


def main() -> None:
    wins = sys.argv[1:] or _DEFAULT
    adapter = make_local_run(warmup_gate=None, ensure_weekly_cache_fp=_FP)  # pre-ensure complete cache
    runs = _ROOT / "sweeps" / "runs"
    results = []
    print(f"=== #370 ACCEPTANCE — {wins} (FY+Q1 first = merge gate) ===", flush=True)
    for alias in wins:
        w = _ALIAS[alias]
        print(f"\n--- {alias} ({w.name}) baseline(560) ---", flush=True)
        adapter(BASELINE, w)
        base_dir = runs / BASELINE.config_hash / w.name
        print(f"--- {alias} trim+cache(320) ---", flush=True)
        adapter(TRIM, w)
        trim_dir = runs / TRIM.config_hash / w.name
        threw = _threw(trim_dir)
        bf, tf = _fills(base_dir), _fills(trim_dir)
        # FAIL-LOUD (the 0-trade-window lesson): byte-identical must NOT vacuously pass [] == [].
        # PASS requires crash-free + NON-EMPTY baseline + count-match + every fill identical. An empty
        # baseline → parity unprovable (N/A, never PASS); a crashed/truncated trim → count mismatch → FAIL.
        identical = len(bf) > 0 and len(bf) == len(tf) and bf == tf
        results.append((alias, w.name, threw, identical, len(bf), len(tf)))
        if threw:
            verdict = "FAIL(threw)"
        elif len(bf) == 0:
            verdict = "N/A(empty baseline)"
        elif identical:
            verdict = "PASS"
        else:
            verdict = "FAIL"
        print(f"  {alias}: threw={threw} byte_identical={identical} "
              f"(baseline {len(bf)} fills, trim {len(tf)}) → {verdict}", flush=True)
        if alias in ("fy", "q1") and verdict == "PASS":
            print(f"  *** {alias.upper()} GATE PASS — crash-free + byte-identical ***", flush=True)

    print("\n=== #370 ACCEPTANCE SUMMARY ===", flush=True)
    for alias, name, threw, identical, nb, nt in results:
        print(f"  {alias:4} {name:16} zero_throw={not threw!s:5} byte_identical={identical!s:5} "
              f"({nb} vs {nt} fills)", flush=True)
    allpass = all(not t and i for _, _, t, i, _, _ in results)
    print(f"\nMERGE GATE: {'ALL PASS ✓' if allpass else 'NOT all pass — inspect'} "
          f"(crash-free + byte-identical). Q1 is the decisive crash-window.", flush=True)


if __name__ == "__main__":
    main()
