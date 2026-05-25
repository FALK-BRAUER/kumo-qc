#!/usr/bin/env python3

import json, hashlib, time, base64, subprocess, urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = '24b9bc4ecad772ce...'  # truncated, need full ID

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

# First find the full backtest ID
ts = str(int(time.time()))
h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
req = urllib.request.Request(f'https://www.quantconnect.com/api/v2/projects/{PROJECT_ID}/backtests', headers={'Authorization': f'Basic {creds}', 'Timestamp': ts})
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.loads(r.read())

for bt in data.get('backtests', []):
    if bt['name'] == 'perf-W1':
        BACKTEST_ID = bt['backtestId']
        break

print(f"Fetching logs for {BACKTEST_ID}")

logs = qc_post('/backtests/logs', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
for entry in logs.get('logs', []):
    print(entry['message'])