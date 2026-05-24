#!/usr/bin/env python3
"""
Test compile endpoint without submitting backtests.
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

print("Compiling...")
comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
compile_id = comp.get('compileId')
print(f"Compile ID: {compile_id}")
print(f"Full response: {json.dumps(comp)}")

# Wait for compile to complete
for _ in range(30):
    time.sleep(5)
    r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
    state = r.get('state', '')
    if state == 'BuildSuccess':
        print(f"  Compile OK: {compile_id[:16]}...")
        break
    elif state == 'BuildError':
        print(f"Build error: {r.get('logs', '')}")
        break
    print(f"  Compile: {state}")

print("Done compile test.")