#!/usr/bin/env python3

import json, hashlib, time, base64, subprocess, urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32033824  # FY2025 project (backtest_bct)
BACKTEST_ID = '1051b475c856baaf35973221512bf281'

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

def qc_get(path):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}",
        headers={'Authorization': f'Basic {creds}', 'Timestamp': ts},
        method='GET'
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

print(f"Fetching logs for FY2025 backtest {BACKTEST_ID}...")
logs = qc_post('/backtests/logs', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
for entry in logs.get('logs', []):
    print(entry)
print(f"Total entries: {len(logs.get('logs', []))}")

# Also fetch backtest stats
backtest = qc_get(f'/projects/{PROJECT_ID}/backtests/{BACKTEST_ID}')
print(f"\nBacktest details:")
print(json.dumps(backtest, indent=2))