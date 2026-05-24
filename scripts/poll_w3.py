#!/usr/bin/env python3
"""
Poll W3 backtest status (backtestId 21196da82b6572eb185ffaef31e9c5c0).
"""
import json, hashlib, time, base64, subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = "21196da82b6572eb185ffaef31e9c5c0"

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

def poll_status():
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
        status = r.get('status')
        stats = r.get('statistics', {})
        print(f"W3 status: {status}")
        print(f"Statistics: {stats}")
        if status == 'Completed':
            trades = stats.get('Total Trades', 0)
            sharpe = stats.get('Sharpe Ratio', 0)
            cagr = stats.get('Compounding Annual Return', 0)
            print(f"Trades: {trades}, Sharpe: {sharpe}, CAGR: {cagr}")
            return True, trades, sharpe, cagr
        elif status == 'RuntimeError':
            print("W3 errored (RuntimeError)")
            return False, None, None, None
        else:
            print(f"W3 still in progress or other status")
            return False, None, None, None
    except Exception as e:
        print(f"Poll error: {e}")
        return False, None, None, None

if __name__ == "__main__":
    poll_status()
