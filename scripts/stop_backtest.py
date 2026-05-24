#!/usr/bin/env python3
"""
Stop a specific QC backtest via API.
Usage: python3 stop_backtest.py 51d12fd61053e818ae3a0c53a5257512
"""
import json, hashlib, time, base64, sys, subprocess
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

if len(sys.argv) != 2:
    print("Usage: python3 stop_backtest.py <backtestId>")
    sys.exit(1)

backtest_id = sys.argv[1]
print(f"Deleting backtest {backtest_id}...")
resp = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': backtest_id})
print(json.dumps(resp, indent=2))