#!/usr/bin/env python3
"""
Test W2 only to debug runtime error.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
PROJECT_ID = 32034565

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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def compile_project():
    print("Compiling...")
    comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
    compile_id = comp.get('compileId')
    if not compile_id:
        sys.exit(f"Compile failed: {comp}")
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
    
    warmup_days = 10
    
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': f"perf-{name}",
        'parameters': {
            'start_year': sy, 'start_month': sm, 'start_day': sd,
            'end_year': ey, 'end_month': em, 'end_day': ed,
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'warmup_days': str(warmup_days),
        },
    })
    print(f"Submit response: {json.dumps(r)}")
    if not r.get('success', False):
        errors = r.get('errors', [])
        if errors and errors[0].startswith('There are no spare nodes available'):
            print(f"  {name}: capacity error — cannot start")
            return None
        print(f"  {name}: submit failed — {json.dumps(r)[:200]}")
        return None
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  {names}: no backtestId — {json.dumps(r)[:200]}")
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
            print(f"  {name} completed: {completed}, error: {error}")
            print(f"  Full response: {json.dumps(bt)}")
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
            net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
            cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
            trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
            print(f"  {name} DONE: NetProfit={net_profit}  CAGR={cagr}  Sharpe={sharpe}  Trades={trades}  error={error}")
            return {'name': name, 'net_profit': net_profit, 'cagr': cagr, 'sharpe': sharpe, 'trades': trades, 'error': error}
        if i % 4 == 0:
            print(f"  {name}: {progress:.0f}%")
        if i >= 90 and progress < 1.0:
            print(f"  {name}: stuck at {progress:.0f}% after {i*15}s — deleting")
            try:
                qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            except:
                pass
            return {'name': name, 'error': 'stuck'}
    print(f"  {name}: timeout after 30 minutes")
    try:
        qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    except:
        pass
    return {'name': name, 'error': 'timeout'}

def main():
    compile_id = compile_project()
    
    name = "W2"
    start = "2026-04-14"
    end = "2026-04-18"
    
    print(f"\nStarting {name} ({start} → {end})...")
    bt_id = submit_backtest(name, start, end, compile_id)
    if bt_id:
        result = poll_backtest(name, bt_id)
        print(f"\nResult: {result}")
    else:
        print(f"\nFailed to submit")

if __name__ == "__main__":
    main()