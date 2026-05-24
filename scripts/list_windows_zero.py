#!/usr/bin/env python3
"""
List QC backtest IDs for W1-W6 runs with 0 trades (rows 13-20 in INDEX.md).
"""
import json, hashlib, time, base64, subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565

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

def list_backtests():
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    backtests = r.get('backtests', [])
    zero_trade_names = [
        "perf-FY2025", "perf-W6", "perf-W5", "perf-W4", "perf-W3", "perf-W2", "perf-W1", "perf-FY2025"
    ]
    for bt in backtests:
        name = bt.get('name')
        if name in zero_trade_names:
            progress = bt.get('progress', 0) * 100
            completed = bt.get('completed')
            bt_id = bt.get('backtestId')
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
            trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
            error = bt.get('error')
            print(f"{name}: id={bt_id}, progress={progress:.1f}%, completed={completed}, Sharpe={sharpe}, trades={trades}, error={error}")

if __name__ == "__main__":
    list_backtests()