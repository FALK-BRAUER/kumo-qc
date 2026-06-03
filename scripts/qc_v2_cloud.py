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
  - A clean backtest == the engine ran end-to-end. completed=True is NOT enough — QC marks a
    CRASHED partial completed=True/progress=1 with the error in bt['error'] (the #318 trap: a
    crashed -0.611 banked as a real result). assert_cloud_clean() is the gate (error is None AND
    progress==1 AND orders>0); run() error-checks BEFORE reading any result. A wiring/interop bug
    surfaces as a runtime ERROR (dv_rank_cap fail-loud, the #318 TradeBar interop crash). Run the
    `smoke` gate before any FY. Diff-ladder trades via /orders + the ACTIVE_SET logs.

`lean cloud push` is broken → deploy via the QC API /files/update (create if missing), same
auth as qc_pe_cloud.py. PID + the project-setup (new-project vs purge-old) are set per the
fintrack project ruling — see PID below.

Usage:
  python3 scripts/qc_v2_cloud.py deploy
  python3 scripts/qc_v2_cloud.py run <name> [poll_minutes]
  python3 scripts/qc_v2_cloud.py smoke                      # A.2 cloud-smoke interop gate (run before any FY)
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

# A.2 cloud-smoke window (#318 / CONVENTIONS §CloudSafety): a window DEEP ENOUGH to exercise the
# runtime LEAN-object construction paths (intraday/weekly/daily seed) across many post-warmup
# entrant rotations, so a .NET-interop crash detonates HERE (cheap) not in an expensive FY that
# then false-greens (the #313 trap). LESSON (#318 crash #2): the original 2-DAY smoke PASSED but
# the FY crashed at ~69% on a depth-dependent bar (float→Decimal on a deeper volume) — too shallow
# to be a real gate. Q1 span = ~3 months of rotations/seeds. The error-checked FY is the backstop.
SMOKE_WINDOW = "    START_DATE = (2025, 1, 1)\n    END_DATE = (2025, 3, 31)\n"


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


def smoke() -> None:
    """A.2 cloud-smoke GATE (#318 / CONVENTIONS §CloudSafety). Deploy + run a SHORT cloud BT over
    SMOKE_WINDOW that exercises the runtime LEAN-object construction paths post-warmup, then gate
    on assert_cloud_clean (inside run()). Catches a .NET-interop crash (the #318 TradeBar class) in
    minutes BEFORE the expensive FY. Run before ANY real cloud FY. Exits NONZERO on a dirty result."""
    global STEP_A_WINDOW
    STEP_A_WINDOW = SMOKE_WINDOW
    cid = deploy()
    out = run("cloud-smoke-interop", compile_id=cid)
    if out is None:
        sys.exit("❌ CLOUD-SMOKE FAILED — runtime/interop crash or not-clean. Do NOT run FY; fix first.")
    print(f"✅ CLOUD-SMOKE CLEAN: {json.dumps(out)} — interop construction paths OK; FY gated-open.")


def assert_cloud_clean(bt: dict, *, reread: Any = None,
                       reread_tries: int = 3, reread_delay: float = 6.0) -> tuple[bool, str]:
    """A cloud BT result is VALID only if it ran to a clean finish (#318 / CONVENTIONS §Parity).

    `completed=True` ALONE is NOT sufficient — QC marks a CRASHED partial as completed=True /
    progress=1 with the runtime error in `bt['error']` (or `bt['stacktrace']`). That is how a
    crashed -0.611 / 72-order partial got banked as a real "result" (the #313 false-green crash,
    masked twice). Require, in order:
      1. NO runtime error/stacktrace (the .NET-interop / fail-loud catch).
      2. progress == 1 (ran to the end, not a stalled partial).
      3. liveness: orders > 0 (a champion that decides daily must trade; 0 orders ⇒ the engine
         silently no-op'd — override only for a config that is legitimately flat).

    NULL-LIVENESS HARDENING (#326): QC populates statistics a beat AFTER `completed` flips → Total
    Orders comes back NULL at poll time. A null liveness field must NEVER pass as clean (the
    silent-zero-champion hole — it slid through once on the hold-confirm smoke). So on a null Total
    Orders, RE-READ via `reread()` — RETRY up to `reread_tries` with `reread_delay`s sleeps (the lag
    can exceed one immediate re-read — it FALSE-NEGATIVE'd a clean 94-order FY before this retry). If
    STILL null/missing OR unparseable after the retries, FAIL LOUD (unverifiable liveness = NOT
    clean — never pass null). Returns (clean, reason)."""
    err = bt.get("error") or bt.get("stacktrace")
    if err:
        return False, f"runtime error: {str(err)[:300]}"
    if bt.get("progress") != 1:
        return False, f"incomplete: progress={bt.get('progress')}"
    raw_orders = (bt.get("statistics", {}) or {}).get("Total Orders")
    if raw_orders is None and reread is not None:
        for _ in range(max(1, reread_tries)):   # stats lag `completed` → retry the re-read
            if reread_delay > 0:
                time.sleep(reread_delay)
            bt = reread() or bt
            raw_orders = (bt.get("statistics", {}) or {}).get("Total Orders")
            if raw_orders is not None:
                break
    if raw_orders is None:
        return False, ("liveness UNVERIFIABLE: Total Orders still null after re-read retries — null "
                       "!= clean (would silently pass a 0-entry champion); fail loud (#326/#277)")
    try:
        n = int(str(raw_orders).replace(",", ""))
    except (ValueError, TypeError):
        return False, f"liveness UNVERIFIABLE: unparseable Total Orders {raw_orders!r} — fail loud (#277)"
    if n <= 0:
        return False, "liveness: 0 orders (override only if the config is legitimately flat)"
    return True, "clean"


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
        # ERROR FIRST — #318: completed=True is set even on a crashed partial (QC marks a runtime
        # crash completed=True/progress=1 with the error in bt['error']). Checking completed first
        # banked a crashed -0.611 as a real result last session. assert_cloud_clean is the gate.
        err = b.get("error") or b.get("stacktrace")
        if err:
            # Runtime error = interop crash (#318 TradeBar) or wiring bug (dv_rank_cap fail-loud).
            print(f"  ❌ {name} ERROR (runtime): {str(err)[:400]}")
            return None
        if b.get("completed"):
            # #277: pass a re-read so assert_cloud_clean can recover a NULL Total Orders (stats lag
            # `completed`) — and FAIL LOUD if still unverifiable (never pass a null-liveness run).
            clean, reason = assert_cloud_clean(
                b, reread=lambda: post("/backtests/read",
                                       {"projectId": PID, "backtestId": bid}).get("backtest", {}))
            if not clean:
                print(f"  ❌ {name} INVALID (completed but not clean): {reason}")
                return None
            s = b.get("statistics", {}) or {}
            out = {"name": name, "backtestId": bid,
                   "sharpe": s.get("Sharpe Ratio"), "net_profit": s.get("Net Profit"),
                   "drawdown": s.get("Drawdown"), "orders": s.get("Total Orders"), "win_rate": s.get("Win Rate")}
            print(f"  ✅ DONE (clean): {json.dumps(out)}")
            return out
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
    elif cmd == "smoke":
        smoke()
    elif cmd == "stepA":
        cid = deploy()
        run("v2-stepA-2025-06-02_16", compile_id=cid)
    else:
        print(__doc__)
