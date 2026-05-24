#!/usr/bin/env python3
"""
Test W3 with minimal warmup.
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
        time.sleep(2)
        r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
        state = r.get('state', '')
        if state == 'BuildSuccess':
            print(f"  Compile OK: {compile_id[:16]}...")
            return compile_id
        elif state == 'BuildError':
            sys.exit(f"Build error: {r.get('logs', '')}")
        print(f"  Compile: {state}")
    sys.exit("Compile timeout")

def submit_w3():
    compile_id = compile_project()
    
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': 'perf-W3',
        'parameters': {
            'start_year': '2026', 'start_month': '04', 'start_day': '22',
            'end_year': '2026', 'end_month': '04', 'end_day': '25',
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'warmup_days': '5',  # Even shorter warmup for 3-day window
        },
    })
    print(f"Submit response: {json.dumps(r)}")
    if not r.get('success', False):
        print(f"Submit failed")
        return None
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    print(f"Backtest ID: {bt_id}")
    return bt_id

def poll_w3(bt_id):
    for i in range(30):
        time.sleep(10)
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', r)
        print(f"Poll {i}: status={bt.get('status')}, progress={bt.get('progress')}")
        completed = bt.get('completed', False)
        error = bt.get('error')
        if completed or error:
            print(f"Done: completed={completed}, error={error}")
            return {'completed': completed, 'error': error}
    return {'error': 'timeout'}

def main():
    print("Testing W3 with warmup_days=5")
    bt_id = submit_w3()
    if bt_id:
        result = poll_w3(bt_id)
        print(f"Final result: {result}")

if __name__ == "__main__":
    main()