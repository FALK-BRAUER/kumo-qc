#!/usr/bin/env python3
"""
Poll W1 backtest (2defb29507199ccf) for runtime error details.
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

def main():
    bt_id = "2defb29507199ccf"
    print(f"Polling W1 backtest {bt_id[:16]}...")
    resp = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    bt = resp.get('backtest', resp)
    print(json.dumps(bt, indent=2))

if __name__ == "__main__":
    main()