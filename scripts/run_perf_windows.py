#!/usr/bin/env python3
"""
Run W1-W6 + FY2025 backtests on performance_bct (project 32034565).
Polls until each completes, prints profit % + Sharpe per window.

Usage:
  python3 scripts/run_perf_windows.py
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565

WINDOWS = [
    ("W1", "2026-04-07", "2026-04-11"),
    ("W2", "2026-04-14", "2026-04-18"),
    ("W3", "2026-04-22", "2026-04-25"),
    ("W4", "2026-04-28", "2026-05-02"),
    ("W5", "2026-05-05", "2026-05-09"),
    ("W6", "2026-05-12", "2026-05-16"),
    ("FY2025", "2025-01-01", "2025-12-31"),
]


def qc_post(path, body):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}", data=data,
        headers={'Authorization': f'Basic {creds}', 'Timestamp': ts, 'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def compile_project():
    print("Compiling...")
    comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
    compile_id = comp.get('compileId')
    if not compile_id:
        sys.exit(f"Compile failed: {comp}")
    # Poll until not InQueue
    for _ in range(30):
        time.sleep(5)
        r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
        state = r.get('state', '')
        if state == 'BuildSuccess':
            print(f"  Compile OK: {compile_id[:16]}...")
            return compile_id
        elif state == 'BuildError':
            sys.exit(f"Build error: {r.get('logs', '')}")
        print(f"  Compile: {state}")
    sys.exit("Compile timeout")


def submit_backtest(name, start, end, compile_id):
    sy, sm, sd = start.split("-")
    ey, em, ed = end.split("-")
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': f"perf-{name}",
        'parameters': {
            'start_year': sy, 'start_month': sm, 'start_day': sd,
            'end_year': ey, 'end_month': em, 'end_day': ed,
        },
    })
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  {name}: submit failed — {json.dumps(r)[:200]}")
        return None
    print(f"  {name}: {bt_id[:16]}... submitted")
    return bt_id


def poll_backtest(name, bt_id):
    for i in range(120):
        time.sleep(15)
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', r)
        progress = bt.get('progress', 0) * 100
        completed = bt.get('completed', False)
        error = bt.get('error')
        if completed or error:
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
            # Net profit from statistics or result
            net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
            cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
            trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
            print(f"  {name} DONE: NetProfit={net_profit}  CAGR={cagr}  Sharpe={sharpe}  Trades={trades}  error={error}")
            return {'name': name, 'net_profit': net_profit, 'cagr': cagr, 'sharpe': sharpe, 'trades': trades, 'error': error}
        if i % 3 == 0:
            print(f"  {name}: {progress:.0f}%")
    print(f"  {name}: TIMEOUT")
    return {'name': name, 'error': 'timeout'}


def main():
    compile_id = compile_project()
    results = []

    for name, start, end in WINDOWS:
        print(f"\nStarting {name} ({start} → {end})...")
        bt_id = submit_backtest(name, start, end, compile_id)
        if bt_id:
            result = poll_backtest(name, bt_id)
            results.append(result)
        time.sleep(5)

    print("\n" + "=" * 60)
    print("PERFORMANCE RESULTS")
    print(f"{'Window':<10} {'NetProfit':<14} {'CAGR':<12} {'Sharpe':<10} {'Trades'}")
    print("-" * 60)
    for r in results:
        if r.get('error') and r['error'] != 'None':
            print(f"{r['name']:<10} ERROR: {r['error']}")
        else:
            print(f"{r['name']:<10} {str(r.get('net_profit','')):<14} {str(r.get('cagr','')):<12} {str(r.get('sharpe','')):<10} {r.get('trades','')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
