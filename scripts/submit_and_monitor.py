#!/usr/bin/env python3
"""
Submit one window and wait for completion.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
PROJECT_ID = 32034565

WINDOWS = [
    ("W1", "2026-04-07", "2026-04-11"),
    ("W2", "2026-04-14", "2026-04-18"),
    ("W3", "2026-04-22", "2026-04-25"),
    ("W4", "2026-04-28", "2026-05-02"),
    ("W5", "2026-05-05", "2026-05-09"),
    ("W6", "2026-05-12", "2026-05-16"),
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'success': False, 'error': str(e)}

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

def submit_window(name, start, end):
    sy, sm, sd = start.split("-")
    ey, em, ed = end.split("-")
    
    compile_id = compile_project()
    
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': f"perf-{name}",
        'parameters': {
            'start_year': sy, 'start_month': sm, 'start_day': sd,
            'end_year': ey, 'end_month': em, 'end_day': ed,
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'warmup_days': '750',
        },
    })
    
    if not r.get('success', False):
        errors = r.get('errors', [])
        if errors and errors[0].startswith('There are no spare nodes available'):
            print(f"  {name}: capacity error — cannot start")
            return None
        print(f"  {name}: submit failed — {json.dumps(r)[:200]}")
        return None
    
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  {name}: no backtestId — {json.dumps(r)[:200]}")
        return None
    print(f"  {name}: {bt_id[:16]}... submitted")
    return bt_id

def poll_window(name, bt_id):
    for i in range(60):
        try:
            r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            bt = r.get('backtest', r)
            completed = bt.get('completed')
            error = bt.get('error')
            
            if completed or error:
                stats = bt.get('statistics', {})
                sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
                net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
                cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
                trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
                print(f"  {name} DONE: NetProfit={net_profit} CAGR={cagr} Sharpe={sharpe} Trades={trades}")
                return {'name': name, 'net_profit': net_profit, 'cagr': cagr, 'sharpe': sharpe, 'trades': trades, 'error': error}
            
            progress = bt.get('progress', 0) * 100
            if i % 2 == 0:
                print(f"  {name}: {progress:.0f}%")
                
        except Exception as e:
            print(f"  Poll error: {e}")
        time.sleep(60)
    print(f"  {name}: timeout after 60 minutes")
    return {'name': name, 'error': 'timeout'}

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 submit_and_monitor.py <window_number>")
        print("Window numbers: 1=W1, 2=W2, 3=W3, 4=W4, 5=W5, 6=W6")
        sys.exit(1)
    
    window_num = int(sys.argv[1])
    if window_num < 1 or window_num > len(WINDOWS):
        print(f"Window must be between 1 and {len(WINDOWS)}")
        sys.exit(2)
    
    name, start, end = WINDOWS[window_num - 1]
    print(f"\n--- Starting {name} ({start} → {end}) ---")
    
    bt_id = submit_window(name, start, end)
    if bt_id:
        result = poll_window(name, bt_id)
        print(f"\nResult: {result}")
    else:
        print(f"Failed to submit {name}")

if __name__ == "__main__":
    main()