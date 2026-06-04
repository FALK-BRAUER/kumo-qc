"""#370 RIGOROUS gate checker — reads the persisted acceptance run dirs (baseline 560 + trim 320 per
window) and applies the FAIL-LOUD verdict the merge stakes on. Decoupled from run_370_acceptance.py so
it re-verifies from artifacts without re-running BTs.

The gate-integrity rule (HQ + the full-FY-parity / 0-trade-window lesson): byte-identical must NOT
vacuously pass an empty/truncated window (0 fills == 0 fills). A window PASSES only if:
  - the trim run did NOT throw WeeklyCacheGapError (crash-free), AND
  - the baseline produced a NON-EMPTY fill set (else parity is unprovable — N/A, never PASS), AND
  - trim fill COUNT == baseline count AND every fill byte-identical.
A crashed/truncated trim → 0 (or fewer) fills → count-mismatch → FAIL (the backstop, independent of
the crash-log scan). An empty baseline → N/A (flagged, never a green PASS).

Usage: python3 scripts/verify_370.py [window ...]   (default: fy q1 q3 q2 q4 w5 w6)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]

from sweeps.types import PhaseChoice, SweepConfig  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

_S1 = (
    PhaseChoice("protective_stop", "cloud_protective_stop", (), 0),
    PhaseChoice("exit_hard", "cloud_adherence_trail", (), 0),
    PhaseChoice("sizing", "flat_pct_heatcap", (("position_pct", 0.05),), 0),
)
BASELINE_HASH = SweepConfig(choices=_S1, continuous_weekly=True).config_hash
TRIM_HASH = SweepConfig(choices=_S1, continuous_weekly=True, warmup_days=320).config_hash
_BY = {w.name: w for w in SIX_WINDOWS}
_ALIAS = {"fy": "fy2025_full", "q1": "w1_2025q1", "q2": "w2_2025q2", "q3": "w3_2025q3",
          "q4": "w4_2025q4", "w5": "w5_2026q1", "w6": "w6_2026_feb_apr"}
_DEFAULT = ["fy", "q1", "q3", "q2", "q4", "w5", "w6"]


def _latest_bt(run_dir: Path) -> Path | None:
    bts = sorted((run_dir / "backtests").glob("*/"), key=lambda d: d.stat().st_mtime, reverse=True)
    return bts[0] if bts else None


def _fills(run_dir: Path) -> list[tuple] | None:
    """Sorted fills, or None if the run dir / order-events is ABSENT (run never produced output = crash/
    missing — distinct from an empty-but-present fill list)."""
    bt = _latest_bt(run_dir)
    if bt is None:
        return None
    oe = next(bt.glob("*-order-events.json"), None)
    if oe is None:
        return None
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
    """Scan ALL text artifacts in the latest bt dir for WeeklyCacheGapError (broadened from *log*.txt
    so a differently-named crash log can't hide a throw)."""
    bt = _latest_bt(run_dir)
    if bt is None:
        return False
    for p in bt.rglob("*"):
        if p.is_file() and p.suffix in (".txt", ".log", ".json"):
            try:
                if "WeeklyCacheGapError" in p.read_text(errors="ignore"):
                    return True
            except OSError:
                continue
    return False


def verify(alias: str) -> dict:
    name = _ALIAS[alias]
    base = _fills(_ROOT / "sweeps" / "runs" / BASELINE_HASH / name)
    trim = _fills(_ROOT / "sweeps" / "runs" / TRIM_HASH / name)
    threw = _threw(_ROOT / "sweeps" / "runs" / TRIM_HASH / name)
    nb = -1 if base is None else len(base)
    nt = -1 if trim is None else len(trim)
    if threw:
        verdict = "FAIL(threw WeeklyCacheGapError)"
    elif base is None:
        verdict = "MISSING(no baseline run)"
    elif trim is None:
        verdict = "FAIL(trim run missing/crashed — no order-events)"
    elif nb == 0:
        verdict = "N/A(empty baseline — parity unprovable, NOT a pass)"
    elif nb != nt:
        verdict = f"FAIL(count mismatch {nb}!={nt})"
    elif base == trim:
        verdict = "PASS(crash-free + byte-identical)"
    else:
        verdict = "FAIL(fills differ at same count)"
    return {"alias": alias, "name": name, "threw": threw, "nb": nb, "nt": nt, "verdict": verdict}


def main() -> None:
    wins = sys.argv[1:] or _DEFAULT
    print(f"=== #370 RIGOROUS GATE — baseline {BASELINE_HASH} vs trim {TRIM_HASH} ===")
    rows = [verify(a) for a in wins]
    for r in rows:
        print(f"  {r['alias']:4} {r['name']:16} threw={r['threw']!s:5} baseline={r['nb']:>4} "
              f"trim={r['nt']:>4} → {r['verdict']}")
    q1 = next((r for r in rows if r["alias"] == "q1"), None)
    passes = [r for r in rows if r["verdict"].startswith("PASS")]
    crashfree = all(not r["threw"] and not r["verdict"].startswith(("FAIL", "MISSING")) for r in rows)
    print(f"\n  crash-free-all: {crashfree}  |  byte-identical PASS: {len(passes)}/{len(rows)}")
    if q1:
        print(f"  *** Q1 (decisive merge-gate window): {q1['verdict']} ***")
    gate = crashfree and q1 is not None and q1["verdict"].startswith("PASS")
    print(f"\n  MERGE GATE (crash-free-all + Q1-byte-identical): {'PASS ✓' if gate else 'NOT YET / FAIL'}")


if __name__ == "__main__":
    main()
