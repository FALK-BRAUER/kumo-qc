#!/usr/bin/env python3
"""
Submit one window using given compile ID.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

WINDOWS = [
    ("W1", "2026-04-07", "2026-04-11"),
    ("W2", "2026-04-14", "2026-04-18"),
    ("W3", "2026-04-22", "2026-04-25"),
    ("W4", "2026-04-28", "2026-05-02"),
    ("W5", "2026-05-05", "2026-05-09"),
    ("W6", "2026-05-12", "2026-05-16"),
]

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
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
        },
    })
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  {name}: submit failed — {json.dumps(r)[:200]}")
        return None
    print(f"  {name}: {bt_id[:16]}... submitted")
    return bt_id

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 submit_window.py <window-number> [compile-id]")
        sys.exit(1)
    
    window_num = int(sys.argv[1])
    if window_num < 1 or window_num > len(WINDOWS):
        print(f"Window must be between 1 and {len(WINDOWS)}")
        sys.exit(2)
    
    name, start, end = WINDOWS[window_num - 1]
    compile_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    if compile_id is None:
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
                break
            elif state == 'BuildError':
                sys.exit(f"Build error: {r.get('logs', '')}")
            print(f"  Compile: {state}")
        else:
            sys.exit("Compile timeout")
    
    bt_id = submit_backtest(name, start, end, compile_id)
    if bt_id:
        print(f"Backtest ID: {bt_id}")
    else:
        print(f"{name}: submit failed")