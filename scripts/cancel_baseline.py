#!/usr/bin/env python3
"""
Cancel baseline-exits-on-2020-2026 via QC API /backtests/delete endpoint
"""
import json, hashlib, time, base64, subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = "3c2c5cc39c5cca5b9c4729bd07d17d1a"

def qc_post(path, body):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
    data = json.dumps(body).encode()
    import urllib.request
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}", data=data,
        headers={'Authorization': f'Basic {creds}', 'Timestamp': ts, 'Content-Type': 'application/json'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def delete_backtest():
    """Cancel baseline via /backtests/delete"""
    try:
        r = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
        print(f"Delete result: {r}")
        return r
    except Exception as e:
        print(f"Delete error: {e}")
        return {'error': str(e)}

if __name__ == "__main__":
    result = delete_backtest()
    print(json.dumps(result, indent=2))