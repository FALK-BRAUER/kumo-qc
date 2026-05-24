#!/usr/bin/env python3
"""
Delete a specific backtest.
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def delete_backtest(name):
    # Get backtest list to find ID
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    for bt in r.get('backtests', []):
        if bt.get('name') == name:
            bt_id = bt.get('backtestId')
            print(f"Deleting {name} (ID: {bt_id})...")
            r2 = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            print(r2)
            return
    print(f"No backtest named {name} found")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        delete_backtest(sys.argv[1])
    else:
        print("Usage: python3 delete_backtest.py perf-W4")