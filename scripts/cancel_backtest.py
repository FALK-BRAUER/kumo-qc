#!/usr/bin/env python3
"""
Delete a backtest via QC API v2.
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

if len(sys.argv) < 2:
    print("Usage: python3 scripts/cancel_backtest.py <backtest-id>")
    sys.exit(1)

backtest_id = sys.argv[1]

print(f"Deleting backtest {backtest_id[:16]}...")
resp = qc_post('/backtests/delete', {
    'projectId': PROJECT_ID,
    'backtestId': backtest_id
})
print(resp)