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

# W2 parameters
start_date = "2026-05-12"
end_date = "2026-05-16"
name = "perf-W6"
warmup_days = 200  # short window warmup

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

# compile
print("Compiling...")
comp = qc_post('/compile/create', {'projectId': project_id})
compile_id = comp.get('compileId')
if not compile_id:
    print(f"Compile failed: {comp}")
    exit(1)

print(f"compileId: {compile_id}")

# poll compile status
for i in range(30):
    time.sleep(5)
    r = qc_post('/compile/read', {'projectId': project_id, 'compileId': compile_id})
    state = r.get('state', '')
    if state == 'BuildSuccess':
        print(f"Compile succeeded at iteration {i}")
        break
    elif state == 'BuildError':
        print(f"Compile error: {r}")
        exit(1)
    print(f"Compile state {state}...")
else:
    print("Compile timeout")
    exit(1)

# submit backtest
print("Submitting W2 backtest...")
submit = qc_post('/backtests/create', {
    'projectId': project_id,
    'compileId': compile_id,
    'backtestName': name,
    'parameters': {
        'start_year': '2026',
        'start_month': '05',
        'start_day': '12',
        'end_year': '2026',
        'end_month': '05',
        'end_day': '16',
        'cloud_exit': 'True',
        'weekly_kijun_exit': 'True',
        'warmup_days': warmup_days
    }
})
backtest_id = submit.get('backtestId')
if not backtest_id:
    print(f"Submit failed: {submit}")
    exit(1)
print(f"Backtest ID: {backtest_id}")
print(f"Name: {name}")
print(f"Start: {start_date}, End: {end_date}, warmup_days: {warmup_days}")
print("Check status via /backtests/read")