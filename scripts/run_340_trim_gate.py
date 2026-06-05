"""#340-B trim+cache GATE — prove trim+cache(320) Q1 is BYTE-IDENTICAL to the full-warmup(560) Q1 for
the PYRAMID (champion_pyramid). The cache is the weekly Ichimoku VALUES (strategy-independent), so the
pyramid's intraday adds shouldn't touch it — but PROVE it (HQ gate), don't assume. Only then can the
fast panel trust trim+cache.

Compares the new trim(320) run against the EXISTING full-warmup(560) Q1 (4c2fc8e40607 — post-rebase
hash unchanged, so the pre-rebase full-warmup Q1 is directly comparable). The adapter pre-ensures the
complete weekly cache (ensure_weekly_cache_fp). Mirrors run_370_acceptance's fill-by-fill check +
the FAIL-LOUD no-vacuous-[]==[] rule.

Usage: python3 scripts/run_340_trim_gate.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.sweep_build as sb  # noqa: E402

sb.build_sweep_dist.__kwdefaults__ = {**(sb.build_sweep_dist.__kwdefaults__ or {}),
                                      "base_module": "strategies.champion_pyramid"}

from sweeps.adapters.qc_local_prod import make_local_run  # noqa: E402
from sweeps.types import SweepConfig, Window  # noqa: E402
from sweeps.windows import SIX_WINDOWS  # noqa: E402

_FP = "90f2d7e3fb80d0a4d2eb286f6a43199e1519495a3ce9d787a4d7d0dfc70c535c"  # the universe weekly-cache fp
RUNS = _ROOT / "sweeps" / "runs_340pyramid"
Q1 = {w.name: w for w in SIX_WINDOWS}["w1_2025q1"]
FULL = SweepConfig(choices=(), continuous_weekly=True)                      # 4c2fc8e40607 (existing full-warmup)
TRIM = SweepConfig(choices=(), continuous_weekly=True, warmup_days=320)     # fb0e2fa2cb67 (trim+cache)


def _fills(run_dir: Path) -> list[tuple]:
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
    for p in bts[0].rglob("*"):
        if p.is_file() and p.suffix in (".txt", ".log", ".json"):
            try:
                if "WeeklyCacheGapError" in p.read_text(errors="ignore"):
                    return True
            except OSError:
                continue
    return False


def main() -> None:
    adapter = make_local_run(runs_root=RUNS, warmup_gate=None, ensure_weekly_cache_fp=_FP)
    print(f"=== #340-B trim+cache GATE — Q1 pyramid (full {FULL.config_hash} vs trim {TRIM.config_hash}) ===", flush=True)
    print(f"--- champion_pyramid {Q1.name} trim+cache(320) [cache pre-ensured] ---", flush=True)
    adapter(TRIM, Q1)
    trim_dir = RUNS / TRIM.config_hash / Q1.name
    full_dir = RUNS / FULL.config_hash / Q1.name
    bf, tf = _fills(full_dir), _fills(trim_dir)
    threw = _threw(trim_dir)
    identical = len(bf) > 0 and len(bf) == len(tf) and bf == tf
    verdict = "FAIL(threw)" if threw else ("N/A(empty full-warmup baseline)" if len(bf) == 0
                                           else ("PASS" if identical else "FAIL"))
    print(f"\n  Q1: threw={threw} byte_identical={identical} "
          f"(full-warmup {len(bf)} fills, trim+cache {len(tf)}) → {verdict}", flush=True)
    print(f"  full_dir={full_dir}\n  trim_dir={trim_dir}", flush=True)
    if verdict == "PASS":
        print("  *** Q1 GATE PASS — trim+cache byte-identical to full-warmup for the PYRAMID → fast panel OK ***", flush=True)


if __name__ == "__main__":
    main()
