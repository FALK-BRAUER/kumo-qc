#!/usr/bin/env python3
import json
import time
import hashlib
import base64
import urllib.request
import subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()

project_id = 32034565  # performance_bct

# FY2025 parameters
start_date = "2025-01-01"
end_date = "2025-12-31"
name = "perf-FY2025"
warmup_days = 750

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

print(f"Submitting FY2025: {start_date} to {end_date}, warmup_days={warmup_days}")
response = qc_post('/backtests/create', {
    'projectId': project_id,
    'compileId': 'b7b9b7fbc78af8847a0219402a205398-711acac1dcbef0c71c1fba81d0f9a253',  # compile first
    'backtestName': name,
    'parameters': {
        'start_year': start_date.split('-')[0],
        'start_month': start_date.split('-')[1],
        'start_day': start_date.split('-')[2],
        'end_year': end_date.split('-')[0],
        'end_month': end_date.split('-')[1],
        'end_day': end_date.split('-')[2],
        'cloud_exit': 'True',
        'weekly_kijun_exit': 'True',
        'warmup_days': str(warmup_days),
    },
})

if not response.get('success', False):
    print(f"Failed: {json.dumps(response)[:200]}")
else:
    bt_id = response.get('backtestId') or (response.get('backtest', {}) or {}).get('backtestId')
    if bt_id:
        print(f"Backtest ID: {bt_id}")
        print(f"Success")
    else:
        print(f"No backtestId — {json.dumps(response)[:200]}")