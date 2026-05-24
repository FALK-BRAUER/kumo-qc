#!/usr/bin/env python3
"""
Submit baseline-fixed (2020-2026) with ETF bug fix + COARSE_MAX 9999.
Cancel stuck baseline-exits-on-2020-2026 via web UI if needed.
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

def compile_project():
    print("Compiling baseline-fixed...")
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

def submit_baseline(compile_id):
    """Submit baseline-fixed (2020-2026) with ETF bug fix"""
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': "baseline-fixed-2020-2026",
        'parameters': {
            'start_year': '2020', 'start_month': '1', 'start_day': '1',
            'end_year': '2026', 'end_month': '12', 'end_day': '31',
            'cloud_exit': 'true',
            'weekly_kijun_exit': 'true',
        },
    })
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  baseline-fixed submit failed — {json.dumps(r)[:200]}")
        return None
    print(f"  baseline-fixed: {bt_id[:16]}... submitted")
    return bt_id

def poll_status():
    """Poll baseline-exits-on-2020-2026 to see if it's still stuck"""
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
        backtests = r.get('backtests', [])
        for bt in backtests:
            name = bt.get('name')
            if name == 'baseline-exits-on-2020-2026':
                progress = bt.get('progress', 0) * 100
                completed = bt.get('completed')
                return progress, completed
        return None, None
    except Exception as e:
        print(f"API error: {e}")
        return None, None

def main():
    progress, completed = poll_status()
    if progress is not None:
        print(f"baseline-exits-on-2020-2026: {progress:.1f}% completed={completed}")
    
    compile_id = compile_project()
    bt_id = submit_baseline(compile_id)
    if bt_id:
        print(f"baseline-fixed-2020-2026 submitted: {bt_id}")
        print("Monitor progress at https://www.quantconnect.com/project/32034565/{bt_id}")
    else:
        print("Failed to submit baseline-fixed")

if __name__ == "__main__":
    main()