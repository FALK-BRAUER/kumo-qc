#!/usr/bin/env python3
"""GH #269 confirm — is Settings.DailyPreciseEndTime the knob controlling local's
daily-bar delivery / entry-fill grid?

DIAGNOSTIC ONLY. Runs in the throwaway worktree kumo-qc-269confirm (branch
diag/269-confirm). Builds champion_asis into a throwaway lean project, runs a short
window (2025-01-01..2025-01-17, the 2025-01-02 rebalance fires 10+ entries), and
extracts the ENTRY (buy) order SUBMIT + FILL times from the order-events artifact.

Three variants, identical window+code except ONE line in lean_entry.initialize():
  A — BASELINE  : daily_precise_end_time UNSET (current default)
  B — True      : self.settings.daily_precise_end_time = True
  C — False     : self.settings.daily_precise_end_time = False

Usage:
  python scripts/confirm_269_daily_precise.py A      # apply variant A + build + run + extract
  python scripts/confirm_269_daily_precise.py B
  python scripts/confirm_269_daily_precise.py C
  python scripts/confirm_269_daily_precise.py extract <variant>   # re-extract last BT only

Every timestamp comes from a real BT order-events artifact — NEVER fabricated.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = os.environ.get("PY", "/Users/falk/projects/kumo-qc/.venv/bin/python")
LEAN_ENTRY = ROOT / "src" / "runtime" / "lean_entry.py"
PROJ = ROOT / "algorithm" / "v2_champion_asis"
DIST_ENTRY = PROJ / "lean_entry.py"

# The marker line we insert right after set_warmup in initialize().
ANCHOR = "        self.set_warmup(timedelta(days=self.WARMUP_DAYS))\n"
MARKER_RE = re.compile(r"^ *self\.settings\.daily_precise_end_time = .*\n", re.MULTILINE)

VARIANT_LINE = {
    "A": None,  # unset
    "B": "        self.settings.daily_precise_end_time = True  # GH269-DIAG\n",
    "C": "        self.settings.daily_precise_end_time = False  # GH269-DIAG\n",
}


def apply_variant(variant: str) -> None:
    """Edit src lean_entry.py: strip any prior marker, then insert the variant line
    (or none for A) immediately after set_warmup."""
    txt = LEAN_ENTRY.read_text()
    txt = MARKER_RE.sub("", txt)  # remove any existing marker first
    line = VARIANT_LINE[variant]
    if line is not None:
        assert ANCHOR in txt, "set_warmup anchor not found in lean_entry.py"
        txt = txt.replace(ANCHOR, ANCHOR + line, 1)
    LEAN_ENTRY.write_text(txt)
    print(f"[{variant}] src lean_entry.py edited (marker={'<unset>' if line is None else line.strip()})")


def build() -> str:
    """Build champion_asis into the throwaway project; return config_hash."""
    code = (
        "import sys;sys.path[:0]=['src','build'];"
        "from build.cloud_package import build;from pathlib import Path;"
        f"r=build('strategies.champion_asis',dist_dir=Path('{PROJ}'));print('CONFIG_HASH',r.config_hash)"
    )
    out = subprocess.run([PY, "-c", code], cwd=ROOT, capture_output=True, text=True)
    print(out.stdout)
    if out.returncode != 0:
        print(out.stderr)
        raise SystemExit(f"build failed rc={out.returncode}")
    # ensure config.json is python + has a local-id
    cfg = PROJ / "config.json"
    c = json.loads(cfg.read_text()) if cfg.exists() else {}
    c["algorithm-language"] = "Python"
    c.setdefault("parameters", {})
    c["local-id"] = 269000269
    cfg.write_text(json.dumps(c, indent=2))
    m = re.search(r"CONFIG_HASH (\S+)", out.stdout)
    return m.group(1) if m else "?"


def grep_dist(variant: str) -> None:
    """Confirm the built dist/lean_entry.py reflects the variant edit."""
    txt = DIST_ENTRY.read_text()
    hits = MARKER_RE.findall(txt)
    expect = VARIANT_LINE[variant]
    print(f"[{variant}] dist lean_entry.py daily_precise_end_time hits: {[h.strip() for h in hits]}")
    if expect is None:
        assert not hits, f"variant A expects NO marker in dist, found {hits}"
    else:
        assert len(hits) == 1 and expect.strip() in txt, f"variant {variant} marker missing in dist"
    print(f"[{variant}] dist confirmed.")


def run_backtest() -> None:
    env = dict(os.environ)
    env.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
    out = subprocess.run(["lean", "backtest", str(PROJ)], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    sys.stdout.write(out.stdout[-3000:])
    if out.returncode != 0:
        sys.stderr.write(out.stderr[-3000:])
        raise SystemExit(f"backtest failed rc={out.returncode}")


def latest_backtest_dir() -> Path:
    bts = sorted((PROJ / "backtests").glob("*/"), key=lambda p: p.stat().st_mtime)
    if not bts:
        raise SystemExit("no backtest dirs found")
    return bts[-1]


def utc(t: float) -> datetime:
    return datetime.fromtimestamp(t, tz=timezone.utc)


def extract(variant: str) -> dict:
    bt = latest_backtest_dir()
    oe_files = list(bt.glob("*-order-events.json"))
    if not oe_files:
        raise SystemExit(f"no order-events.json in {bt}")
    events = json.loads(oe_files[0].read_text())
    # entry buy orders. We group submit+fill per orderId, take BUY direction.
    by_order: dict[int, dict] = {}
    for e in events:
        oid = e.get("orderId")
        d = by_order.setdefault(oid, {})
        d["symbol"] = e.get("symbolValue", e.get("symbol"))
        d["direction"] = e.get("direction")
        st = e.get("status")
        t = e.get("time")
        if st == "submitted":
            d["submit"] = t
        if st == "filled":
            d["fill"] = t
            d["fillQty"] = e.get("fillQuantity")
    # buy entries (direction buy). Sort by submit time.
    buys = [d for d in by_order.values() if d.get("direction") == "buy"]
    buys.sort(key=lambda d: d.get("submit") or 0)
    print(f"\n===== VARIANT {variant} — entry (buy) orders from {bt.name} =====")
    rows = []
    for d in buys:
        sub = utc(d["submit"]) if d.get("submit") else None
        fil = utc(d["fill"]) if d.get("fill") else None
        rows.append({
            "symbol": d["symbol"],
            "submit_utc": sub.isoformat() if sub else None,
            "fill_utc": fil.isoformat() if fil else None,
            "fill_date": fil.date().isoformat() if fil else None,
            "fillQty": d.get("fillQty"),
        })
        print(f"  {d['symbol']:>6}  submit={sub}  fill={fil}  qty={d.get('fillQty')}")
    fill_dates = sorted({r["fill_date"] for r in rows if r["fill_date"]})
    print(f"  -> distinct entry FILL dates: {fill_dates}")
    return {"variant": variant, "bt_dir": bt.name, "rows": rows, "fill_dates": fill_dates}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "extract":
        v = sys.argv[2] if len(sys.argv) > 2 else "?"
        res = extract(v)
        (ROOT / f"/tmp/269_{v}.json").write_text(json.dumps(res, indent=2))
        return
    variant = cmd
    assert variant in VARIANT_LINE, f"unknown variant {variant}"
    apply_variant(variant)
    h = build()
    print(f"[{variant}] config_hash={h}")
    grep_dist(variant)
    run_backtest()
    res = extract(variant)
    Path(f"/tmp/269_{variant}.json").write_text(json.dumps(res, indent=2))
    print(f"[{variant}] saved /tmp/269_{variant}.json")


if __name__ == "__main__":
    main()
