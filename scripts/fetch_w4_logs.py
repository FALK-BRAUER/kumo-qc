#!/usr/bin/env python3

import json, hashlib, time, base64, subprocess, urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = 'b8a59e92e5b7a7156d59ebd262ca5c44'  # W4

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

print(f"Fetching logs for W4 backtest {BACKTEST_ID}...")
logs = qc_post('/backtests/logs', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
print(f"Total entries: {len(logs.get('logs', []))}")
for entry in logs.get('logs', []):
    print(entry['message'])