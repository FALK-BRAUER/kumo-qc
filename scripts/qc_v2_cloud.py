#!/usr/bin/env python3
"""ARCH2 v2 cloud driver (#238) — deploy dist/ + run cloud BT (live-coarse universe model).

Adapted from qc_pe_cloud.py (Pe-hardwired) to the v2 phase engine:
  - SRC = dist/ (the built closure, 16 flat .py); deploy ALL of them via /files/update.
  - LIVE-COARSE UNIVERSE: the v2 engine computes its trading universe LIVE once-daily from QC's
    NATIVE coarse feed (cloud = ground truth). There is NO stored ObjectStore universe artifact
    and NO fingerprint-verify-on-file — both were RETIRED with the stored-universe mechanism.
    So this driver does NOT upload artifacts and does NOT reference fp-verify.
  - The v2 BctEngineAlgorithm reads START_DATE/END_DATE from CLASS ATTRS (not QC params),
    so the short window is BAKED INTO dist/main.py before deploy — run() passes no date params.
  - A COMPLETED backtest == the engine ran end-to-end (the live selection wired correctly).
    A wiring bug surfaces as a runtime ERROR (e.g. dv_rank_cap fail-loud), NOT a fingerprint
    check. Diff-ladder trades via /orders + the ACTIVE_SET logs.

`lean cloud push` is broken → deploy via the QC API /files/update (create if missing), same
auth as qc_pe_cloud.py. PID + the project-setup (new-project vs purge-old) are set per the
fintrack project ruling — see PID below.

Usage:
  python3 scripts/qc_v2_cloud.py deploy
  python3 scripts/qc_v2_cloud.py run <name> [poll_minutes]
  python3 scripts/qc_v2_cloud.py orders <backtestId>
  python3 scripts/qc_v2_cloud.py chart <backtestId> [chartName] [outPath]  # #243 chart-read
  python3 scripts/qc_v2_cloud.py stepA      # deploy + run short window
"""
import base64
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UID = subprocess.check_output(["security", "find-generic-password", "-s", "qc-user-id", "-a", "kumo-qc", "-w"]).decode().strip()
TOK = subprocess.check_output(["security", "find-generic-password", "-s", "qc-api-token", "-a", "kumo-qc", "-w"]).decode().strip()

# fintrack ruling: a CLEAN NEW project (no old-Pe contamination on the #182 check). Resolved
# at run-time by ensure_project() — create-or-find by name (idempotent; create is additive).
PROJECT_NAME = "arch2_champion_v2"
PID: int | None = None

DIST = Path(__file__).resolve().parents[1] / "dist"
MARKER = "champion-asis"  # present in dist/main.py STRATEGY_CONFIG name — deploy readback check

# Step A short window = local run 4's EXACT window (the #182 parity comparison point). v2
# BctEngineAlgorithm reads START_DATE/END_DATE class attrs; inject them into the DEPLOYED
# main.py content (keeps local dist clean — no throwaway file edit). None → full-year default.
# #243: nulled for the full-FY2025 chart-capture deploy (the BctEngineAlgorithm defaults
# to START=(2025,1,1)/END=(2025,12,31) when no window is injected). Set to the Step-A
# string again only for a short-window parity comparison.
STEP_A_WINDOW = None


def _inject_window(content: str) -> str:
    """Insert the Step-A window into the BCTAlgorithm subclass (after STRATEGY_CONFIG=...).
    Idempotent: skips if START_DATE already present."""
    if STEP_A_WINDOW is None or "START_DATE" in content.split("class BCTAlgorithm")[-1]:
        return content
    return content.replace(
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n",
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n" + STEP_A_WINDOW, 1)


def _auth_headers(ts: str, extra: dict[str, str]) -> dict[str, str]:
    h = hashlib.sha256(f"{TOK}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{UID}:{h}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Timestamp": ts, **extra}


def post(path: str, body: dict) -> dict:
    ts = str(int(time.time()))
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}", data=json.dumps(body).encode(),
        headers=_auth_headers(ts, {"Content-Type": "application/json"}), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"success": False, "error": str(e)}


def ensure_project() -> int:
    """Resolve PID: find the clean v2 project by name, else create it (additive, fintrack-OK).
    Idempotent — safe to call on every command. NO billable cost (project create is free)."""
    global PID
    if PID is not None:
        return PID
    listing = post("/projects/read", {})
    for p in listing.get("projects", []):
        if p.get("name") == PROJECT_NAME:
            PID = int(p["projectId"])
            print(f"  found project '{PROJECT_NAME}' → PID {PID}")
            return PID
    r = post("/projects/create", {"name": PROJECT_NAME, "language": "Py"})
    proj = (r.get("projects") or [r.get("project", {})])[0] if r.get("success") else {}
    if not r.get("success") or not proj.get("projectId"):
        sys.exit(f"project create failed: {json.dumps(r)[:300]}")
    PID = int(proj["projectId"])
    print(f"  created project '{PROJECT_NAME}' → PID {PID}")
    return PID


def _require_pid() -> None:
    ensure_project()


def deploy() -> str:
    _require_pid()
    existing = {f["name"] for f in post("/files/read", {"projectId": PID}).get("files", [])}
    files = sorted(p.name for p in DIST.glob("*.py"))
    if not files:
        sys.exit(f"no .py in {DIST} — build dist first")
    for fn in files:
        content = (DIST / fn).read_text()
        if fn == "main.py":
            content = _inject_window(content)  # bake Step-A window into the deployed main.py
        action = "update" if fn in existing else "create"
        r = post(f"/files/{action}", {"projectId": PID, "name": fn, "content": content})
        print(f"  {action} {fn}: success={r.get('success')} {r.get('errors') or ''}")
        if not r.get("success"):
            sys.exit(f"deploy failed on {fn}: {r}")
    back = {f["name"]: f.get("content", "") for f in post("/files/read", {"projectId": PID}).get("files", [])}
    if MARKER not in back.get("main.py", ""):
        sys.exit(f"MARKER '{MARKER}' not in deployed main.py — deploy unverified")
    print(f"  ✅ marker '{MARKER}' present; deployed {len(files)} files")
    return compile_project()


def compile_project() -> str:
    _require_pid()
    comp = post("/compile/create", {"projectId": PID})
    cid = comp.get("compileId")
    if not cid:
        sys.exit(f"compile create failed: {comp}")
    for _ in range(48):
        time.sleep(5)
        r = post("/compile/read", {"projectId": PID, "compileId": cid})
        st = r.get("state", "")
        if st == "BuildSuccess":
            print(f"  ✅ compile OK {cid[:20]}…")
            return cid
        if st == "BuildError":
            sys.exit(f"BUILD ERROR: {r.get('logs', '')}")
        print(f"  compile: {st}")
    sys.exit("compile timeout")


def run(name: str, poll_minutes: int = 30, compile_id: str | None = None) -> dict | None:
    _require_pid()
    cid = compile_id or compile_project()
    # No date params — v2 BctEngineAlgorithm uses START_DATE/END_DATE class attrs (baked in dist).
    r = post("/backtests/create", {"projectId": PID, "compileId": cid, "backtestName": name})
    if not r.get("success"):
        sys.exit(f"submit failed: {json.dumps(r)[:300]}")
    bid = r.get("backtest", {}).get("backtestId")
    print(f"  bt {bid} created — polling…")
    for _ in range(poll_minutes * 6):
        time.sleep(10)
        b = post("/backtests/read", {"projectId": PID, "backtestId": bid}).get("backtest", {})
        if b.get("completed"):
            s = b.get("statistics", {}) or {}
            out = {"name": name, "backtestId": bid,
                   "sharpe": s.get("Sharpe Ratio"), "net_profit": s.get("Net Profit"),
                   "drawdown": s.get("Drawdown"), "orders": s.get("Total Orders"), "win_rate": s.get("Win Rate")}
            print(f"  ✅ DONE: {json.dumps(out)}")
            return out
        err = b.get("error") or b.get("stacktrace")
        if err:
            # A runtime ERROR here = wiring bug (e.g. dv_rank_cap fail-loud), NOT a fingerprint check.
            print(f"  ❌ {name} ERROR (runtime): {str(err)[:400]}")
            return None
        print(f"  {name}: {b.get('progress', 0) * 100:.0f}%")
    print("  poll timeout")
    return None


def chart(bid: str, chart_name: str = "Universe", out_path: str | None = None) -> dict | None:
    """Read a custom chart's series via POST /backtests/chart/read (#243).

    ReadChartResponse.chart.series[].values = ascending [time, value] pairs (4000-pt/series
    cap). The endpoint is FLAKY → retry 5x with exponential backoff. Returns a dict of
    {seriesName: [[time, value], ...]} using the TRUE plotted int/float values; optionally
    dumps to out_path. Returns None if all retries fail (NEVER fabricates)."""
    _require_pid()
    last_err = ""
    for attempt in range(5):
        r = post("/backtests/chart/read", {
            "projectId": PID,
            "backtestId": bid,
            "name": chart_name,
            "count": 4000,
            "start": 0,
            "end": int(time.time()),
        })
        if r.get("success"):
            ch = r.get("chart") or {}
            series = ch.get("series") or {}
            # series may be a dict {name: {...,"values":[...]}} or a list of series objects.
            items = series.items() if isinstance(series, dict) else (
                (s.get("name", f"s{i}"), s) for i, s in enumerate(series))
            out: dict[str, list] = {}
            for name, s in items:
                vals = s.get("values") or []
                # values can be [[t,v],...] (line) or [{"x":t,"y":v},...]; normalize to [t, v].
                norm = []
                for v in vals:
                    if isinstance(v, dict):
                        norm.append([v.get("x"), v.get("y")])
                    elif isinstance(v, (list, tuple)) and len(v) >= 2:
                        norm.append([v[0], v[1]])
                out[name] = norm
            print(f"  ✅ chart '{chart_name}': {len(out)} series " +
                  ", ".join(f"{k}({len(v)})" for k, v in out.items()))
            if out_path:
                Path(out_path).write_text(json.dumps(
                    {"backtestId": bid, "chart": chart_name, "series": out}, indent=2))
                print(f"  wrote {out_path}")
            return out
        last_err = json.dumps(r)[:300]
        wait = 3 * (2 ** attempt)
        print(f"  chart-read attempt {attempt + 1}/5 failed ({last_err[:120]}); retry in {wait}s")
        time.sleep(wait)
    print(f"  ❌ chart-read '{chart_name}' FAILED after 5 retries: {last_err}")
    return None


def orders(bid: str) -> list[dict]:
    """Read ALL orders for a backtest. /backtests/orders/read only honors a window of <= 100
    indices per call — a wide window (start:0/end:1000) silently returns 0 orders (the silent-0
    trap that made this command report nothing for a 291-order BT). Paginate in 100-index
    windows until a short page; FAIL LOUD on an API error rather than reporting an empty list."""
    _require_pid()
    all_orders: list[dict] = []
    start = 0
    while True:
        r = post("/backtests/orders/read",
                 {"projectId": PID, "backtestId": bid, "start": start, "end": start + 100})
        if not r.get("success", True):
            sys.exit(f"orders read failed at start={start}: {json.dumps(r)[:300]}")
        batch = r.get("orders", [])
        all_orders.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    print(f"  {len(all_orders)} orders")
    for o in all_orders:
        print(f"    {o.get('time')} {o.get('symbol', {}).get('value')} qty={o.get('quantity')} {o.get('type')} status={o.get('status')}")
    return all_orders


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "deploy":
        deploy()
    elif cmd == "run":
        run(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 30)
    elif cmd == "orders":
        orders(sys.argv[2])
    elif cmd == "chart":
        chart(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "Universe",
              sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "stepA":
        cid = deploy()
        run("v2-stepA-2025-06-02_16", compile_id=cid)
    else:
        print(__doc__)
