#!/usr/bin/env python3
"""Submit B0d-honest 5-day backtest to QC cloud project 32033824."""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32033824
ORG_ID = "8167a04384265855060312cc22fdbdc6"

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

def get_files():
    """Read local algorithm files."""
    import os
    base = "/Users/falk/projects/kumo-qc/algorithm/performance_bct"
    files = {}
    for f in os.listdir(base):
        # Only push code and config files, NOT large universe JSONs
        if f.endswith('.py') or f == 'lean.json':
            with open(os.path.join(base, f)) as fh:
                files[f] = fh.read()
    return files

def push_files():
    """Push files to cloud project."""
    files = get_files()
    for name, content in files.items():
        r = qc_post('/files/update', {
            'projectId': PROJECT_ID,
            'name': name,
            'content': content,
        })
        print(f"  Push {name}: {r.get('success', False)}")
    return True

def compile_and_wait():
    """Compile and wait for success."""
    r = qc_post('/compile/create', {'projectId': PROJECT_ID})
    compile_id = r.get('compileId')
    if not compile_id:
        print(f"Compile create failed: {r}")
        return None
    print(f"Compile created: {compile_id[:16]}...")
    
    for i in range(60):
        time.sleep(5)
        r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
        state = r.get('state', '')
        if state == 'BuildSuccess':
            print(f"  Compile OK")
            return compile_id
        elif state == 'BuildError':
            logs = r.get('logs', [])
            print(f"  Build ERROR: {logs[:5] if isinstance(logs, list) else logs}")
            return None
        print(f"  Compile: {state} ({(i+1)*5}s)")
    print("Compile timeout")
    return None

def submit_backtest(compile_id):
    """Submit 5-day backtest."""
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': 'B0d-honest-5day-diff-20250203',
        'parameters': {
            'start_year': '2025', 'start_month': '2', 'start_day': '3',
            'end_year': '2025', 'end_month': '2', 'end_day': '7',
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'regime_gate_enabled': 'true',
            'warmup_days': '750',
        },
    })
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"Submit failed: {json.dumps(r)[:500]}")
        return None
    print(f"Backtest submitted: {bt_id}")
    return bt_id

def poll_backtest(bt_id):
    """Wait for backtest completion."""
    for i in range(120):  # 10 min max
        time.sleep(5)
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', {})
        progress = bt.get('progress', 0)
        state = 'running' if progress < 1 else 'done'
        print(f"  BT progress: {progress:.1%} ({(i+1)*5}s)")
        if progress >= 1:
            return bt
    print("BT poll timeout")
    return None

if __name__ == '__main__':
    print("Pushing files to cloud...")
    push_files()
    
    print("\nCompiling...")
    compile_id = compile_and_wait()
    if not compile_id:
        sys.exit(1)
    
    print("\nSubmitting backtest...")
    bt_id = submit_backtest(compile_id)
    if not bt_id:
        sys.exit(1)
    
    print("\nPolling backtest...")
    result = poll_backtest(bt_id)
    if result:
        orders = result.get('orders', [])
        print(f"\nCloud BT complete. Orders: {len(orders)}")
        # Save results
        with open('/tmp/cloud_bt_result.json', 'w') as f:
            json.dump(result, f, indent=2)
        print("Saved to /tmp/cloud_bt_result.json")
    else:
        sys.exit(1)
