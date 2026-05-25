#!/usr/bin/env python3
"""
Delete a specific backtest.
Usage: python3 delete_one.py <backtestId>
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"API error: {e}")
        return {'success': False}

def delete_backtest(bt_id):
    r = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    return r.get('success', False)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 delete_one.py <backtestId>")
        sys.exit(1)
    bt_id = sys.argv[1]
    success = delete_backtest(bt_id)
    print(f"Deleted: {success}")