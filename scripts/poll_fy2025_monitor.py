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

def get_backtest_status(backtest_id):
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': backtest_id})
    bt = r.get('backtest', r)
    return bt

def list_backtests():
    r = qc_post('/backtests/list', {'projectId': PROJECT_ID})
    return r.get('backtests', [])

def monitor_fy2025():
    """Monitor FY2025 backtest progress"""
    
    # Find FY2025 backtest
    backtests = list_backtests()
    fy2025 = None
    for b in backtests:
        if 'perf-FY2025' in b.get('name', ''):
            fy2025 = b
            break
    
    if not fy2025:
        print("FY2025 not found")
        return
    
    bt_id = fy2025['backtestId']
    print(f"Monitoring FY2025: {bt_id[:12]}...")
    
    poll_interval = 30  # seconds
    max_polls = 240  # 60 minutes * 4 polls/min
    
    for i in range(max_polls):
        status = get_backtest_status(bt_id)
        progress = status.get('progress', 0)
        state = status.get('status', '')
        completed = status.get('completed', False)
        error = status.get('error', None)
        
        print(f"Poll {i}: progress={progress:.3f}%, status={state}, completed={completed}")
        
        if completed:
            print(f"FY2025 completed!")
            print(f"Error: {error}")
            print(f"Stats: {json.dumps(status.get('statistics', {}), indent=2)}")
            return
        
        if error:
            print(f"FY2025 error: {error}")
            return
        
        if state.startswith('Runtime Error'):
            print(f"FY2025 Runtime Error")
            return
        
        time.sleep(poll_interval)
    
    print(f"FY2025 timeout after {max_polls * poll_interval / 60} minutes")

if __name__ == "__main__":
    monitor_fy2025()