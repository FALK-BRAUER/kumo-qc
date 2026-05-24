#!/usr/bin/env python3

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

def list_backtests():
    r = qc_post('/backtests/list', {'projectId': PROJECT_ID})
    return r.get('backtests', [])

def delete_backtest(backtest_id):
    r = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': backtest_id})
    return r.get('success', False)

def get_backtest_status(backtest_id):
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': backtest_id})
    bt = r.get('backtest', r)
    return bt

def test_fy2025():
    """Test FY2025 with warmup_days=182"""
    print("Testing FY2025 with warmup_days=182")
    
    # FY2025: Jan 1 2025-Dec 31 2025 (365 days)
    params = {
        "start_year": "2025",
        "start_month": "01",
        "start_day": "01",
        "end_year": "2025",
        "end_month": "12",
        "end_day": "31",
        "cloud_exit": "True",
        "weekly_kijun_exit": "True",
        "warmup_days": "182"
    }
    
    # Check if FY2025 already exists
    backtests = list_backtests()
    fy2025_exists = any("perf-FY2025" in b.get('name', '') for b in backtests)
    
    if fy2025_exists:
        print("FY2025 backtest already exists")
        for b in backtests:
            if "perf-FY2025" in b.get('name', ''):
                print(f"FY2025: {b['backtestId']}, status={b.get('status', '')}, progress={b.get('progress', 0)}")
                if b.get('status') == 'Completed.':
                    print("FY2025 already completed")
                    return b['backtestId']
    
    # Submit new FY2025
    compile_id = compile_project()
    
    print(f"Compile OK: {compile_id[:12]}...")
    
    # Delete auto-generated QC backtest after compile
    backtests = list_backtests()
    for b in backtests:
        if b.get('name', '').startswith('perf-') and b.get('completed', False) == False:
            print(f"Deleting auto-generated QC backtest: {b['backtestId'][:12]}...")
            delete_backtest(b['backtestId'])
    
    # Submit FY2025
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': 'perf-FY2025',
        'parameters': params,
    })
    print(f"Submit response: {json.dumps(r)}")
    if not r.get('success', False):
        print(f"Submit failed")
        return None
    
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    print(f"Backtest ID: {bt_id}")
    
    # Poll for completion
    poll_interval = 15
    max_polls = 240  # 60 minutes
    
    for i in range(max_polls):
        status = get_backtest_status(bt_id)
        print(f"Poll {i}: status={status.get('status', '')}, progress={status.get('progress', 0)}")
        
        if status.get('completed', False):
            print(f"Done: completed=True, error={status.get('error', None)}")
            return bt_id
        
        if status.get('error'):
            print(f"Error: {status.get('error')}")
            delete_backtest(bt_id)
            return None
        
        if status.get('status', '').startswith('Runtime Error'):
            print(f"Runtime Error: {status.get('error')}")
            delete_backtest(bt_id)
            return None
        
        time.sleep(poll_interval)
    


if __name__ == "__main__":
    test_fy2025()