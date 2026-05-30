#!/usr/bin/env python3
"""
Pe cloud validation driver — deploy Pe files to QC proj 32033824 + run windows.

`lean cloud push` is BROKEN → deploy via QC API /files/update (create if missing).
Marker verification is structural: after push we read the file back and confirm the
VERSION_MARKER is present in the deployed source, and every backtest is created with
the explicit Pe parameter set (echoed in the create call). No log-scraping needed.

Usage:
  python3 scripts/qc_pe_cloud.py deploy        # push 3 files + compile
  python3 scripts/qc_pe_cloud.py run <name> <start YYYY-MM-DD> <end YYYY-MM-DD>
  python3 scripts/qc_pe_cloud.py run-all       # FY2025 / 2026-YTD / 2020-2026
"""
import json, time, hashlib, base64, subprocess, sys, urllib.request

UID = subprocess.check_output(['security','find-generic-password','-s','qc-user-id','-a','kumo-qc','-w']).decode().strip()
TOK = subprocess.check_output(['security','find-generic-password','-s','qc-api-token','-a','kumo-qc','-w']).decode().strip()
PID = 32033824
SRC = "/Users/falk/projects/kumo-qc-p3b/algorithm/performance_bct"
FILES = ["main.py", "pyramid_engine.py", "resistance_support.py"]
MARKER = "pyramid_engine_v1"

# Pe param recipe — base defaults in main.py + these overrides.
PE_PARAMS = {
    "risk_amount": "500",
    "pyramid_enabled": "true",
    "pyramid_variant": "Pe",
    "pyramid_uncapped": "true",
    "max_ticker_risk_usd": "0",
    "warmup_days": "750",
    # exit-config: filled from local-repro recipe (see EXITS below)
}
# Set to True/False once local repro locks the exact exit-config that gives 1.00.
EXITS = {"cloud_exit": None, "weekly_kijun_exit": None}  # None = leave at main.py default


def post(path, body):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{TOK}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{UID}:{h}".encode()).decode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}", data=json.dumps(body).encode(),
        headers={'Authorization': f'Basic {creds}', 'Timestamp': ts, 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'success': False, 'error': str(e)}


def deploy():
    existing = {f['name'] for f in post('/files/read', {'projectId': PID}).get('files', [])}
    for fn in FILES:
        content = open(f"{SRC}/{fn}").read()
        if fn in existing:
            r = post('/files/update', {'projectId': PID, 'name': fn, 'content': content})
        else:
            r = post('/files/create', {'projectId': PID, 'name': fn, 'content': content})
        print(f"  {'update' if fn in existing else 'create'} {fn}: success={r.get('success')} {r.get('errors') or ''}")
        if not r.get('success'):
            sys.exit(f"deploy failed on {fn}: {r}")
    # read-back marker verification
    back = {f['name']: f.get('content', '') for f in post('/files/read', {'projectId': PID}).get('files', [])}
    if MARKER not in back.get('main.py', ''):
        sys.exit(f"MARKER '{MARKER}' NOT in deployed main.py — deploy unverified")
    print(f"  ✅ marker '{MARKER}' present in deployed main.py")
    return compile_project()


def compile_project():
    comp = post('/compile/create', {'projectId': PID})
    cid = comp.get('compileId')
    if not cid:
        sys.exit(f"compile create failed: {comp}")
    for _ in range(40):
        time.sleep(5)
        r = post('/compile/read', {'projectId': PID, 'compileId': cid})
        st = r.get('state', '')
        if st == 'BuildSuccess':
            print(f"  ✅ compile OK {cid[:20]}…")
            return cid
        if st == 'BuildError':
            sys.exit(f"BUILD ERROR: {r.get('logs','')}")
        print(f"  compile: {st}")
    sys.exit("compile timeout")


def params_for(start, end):
    sy, sm, sd = start.split("-")
    ey, em, ed = end.split("-")
    p = dict(PE_PARAMS)
    p.update({'start_year': sy, 'start_month': sm, 'start_day': sd,
              'end_year': ey, 'end_month': em, 'end_day': ed})
    for k, v in EXITS.items():
        if v is not None:
            p[k] = "true" if v else "false"
    return p


def run(name, start, end, compile_id=None):
    cid = compile_id or compile_project()
    p = params_for(start, end)
    print(f"  submit {name} [{start}→{end}] params={json.dumps(p)}")
    r = post('/backtests/create', {'projectId': PID, 'compileId': cid,
                                   'backtestName': name, 'parameters': p})
    if not r.get('success'):
        errs = r.get('errors', [])
        if errs and 'no spare nodes' in str(errs[0]).lower():
            print(f"  {name}: NO SPARE NODES — retry later"); return None
        sys.exit(f"submit failed: {json.dumps(r)[:300]}")
    bt = r.get('backtest', {})
    bid = bt.get('backtestId')
    print(f"  bt {bid} created — polling…")
    for _ in range(180):  # up to ~30 min
        time.sleep(10)
        rr = post('/backtests/read', {'projectId': PID, 'backtestId': bid})
        b = rr.get('backtest', {})
        if b.get('completed'):
            s = b.get('statistics', {}) or {}
            rs = b.get('runtimeStatistics', {}) or {}
            out = {
                'name': name, 'backtestId': bid,
                'sharpe': s.get('Sharpe Ratio'), 'net_profit': s.get('Net Profit'),
                'drawdown': s.get('Drawdown'), 'orders': s.get('Total Orders'),
                'win_rate': s.get('Win Rate'), 'psr': s.get('Probabilistic Sharpe Ratio'),
            }
            print(f"  ✅ DONE {name}: {json.dumps(out)}")
            return out
        err = b.get('error') or b.get('stacktrace')
        if err:
            print(f"  ❌ {name} ERROR: {str(err)[:300]}"); return None
        prog = b.get('progress', 0)
        print(f"  {name}: {prog*100:.0f}%")
    print(f"  {name}: poll timeout"); return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "deploy":
        deploy()
    elif cmd == "run":
        run(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "run-all":
        cid = deploy()
        results = []
        for nm, s, e in [("Pe-cloud-FY2025", "2025-01-01", "2025-12-31"),
                         ("Pe-cloud-2026YTD", "2026-01-01", "2026-05-29"),
                         ("Pe-cloud-2020-2026", "2020-01-01", "2026-05-29")]:
            results.append(run(nm, s, e, compile_id=cid))
        print("\n=== SUMMARY ===")
        for r in results:
            print(json.dumps(r))
    else:
        print(__doc__)
