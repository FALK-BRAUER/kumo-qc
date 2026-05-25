#!/usr/bin/env python3
"""
Poll FY2025 progress until completion.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
FY2025_ID = "1051b475c856baaf35973221512bf281"

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

def poll():
    resp = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': FY2025_ID, 'results': False})
    if resp.get('success'):
        bt = resp.get('backtest', resp)
        progress = bt.get('progress')
        completed = bt.get('completed')
        name = bt.get('name')
        print(f"{name} progress={progress} completed={completed}")
        if completed:
            sharpe = bt.get('statistics', {}).get('Sharpe Ratio', '0')
            trades = bt.get('totalPerformance', {}).get('tradeStatistics', {}).get('totalNumberOfTrades', 0)
            print(f"FY2025 Sharpe Ratio: {sharpe}, Trades: {trades}")
            return True
    return False

while True:
    if poll():
        break
    time.sleep(300)  # 5 minutes