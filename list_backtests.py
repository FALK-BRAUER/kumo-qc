#!/usr/bin/env python3

import json, hashlib, time, base64, subprocess, urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565

ts = str(int(time.time()))
h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()

req = urllib.request.Request(f'https://www.quantconnect.com/api/v2/projects/{PROJECT_ID}/backtests', headers={'Authorization': f'Basic {creds}', 'Timestamp': ts})
with urllib.request.urlopen(req, timeout=30) as r:
    data = json.loads(r.read())

print(json.dumps(data, indent=2))