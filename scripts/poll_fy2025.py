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

def poll_backtest(backtest_id):
    poll_interval = 15
    max_polls = 240  # 60 minutes
    
    for i in range(max_polls):
        status = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': backtest_id})
        print(f"Poll {i}: status={status.get('status', '')}, progress={status.get('progress', 0)}")
        
        if status.get('completed', False):
            print(f"Done: completed=True, error={status.get('error', None)}")
            return backtest_id
        
        if status.get('error'):
            print(f"Error: {status.get('error')}")
            return None
        
        if status.get('status', '').startswith('Runtime Error'):
            print(f"Runtime Error: {status.get('error')}")
            return None
        
        time.sleep(poll_interval)
    
    print(f"Timeout after {max_polls} polls")
    return None

if __name__ == "__main__":
    backtests = qc_post('/backtests/list', {'projectId': PROJECT_ID})
    fy2025_id = None
    for b in backtests.get('backtests', []):
        if "perf-FY2025" in b.get('name', ''):
            fy2025_id = b['backtestId']
            print(f"FY2025 ID: {fy2025_id}")
            poll_backtest(fy2025_id)
            break
    
    if fy2025_id is None:
        print("FY2025 backtest not found")