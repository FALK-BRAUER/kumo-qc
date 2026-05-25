#!/usr/bin/env python3
"""
Poll a specific backtest ID and return stats.
"""
import json, hashlib, time, base64, subprocess, sys, os
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def poll_backtest(bt_id):
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    bt = r.get('backtest', r)
    progress = bt.get('progress', 0) * 100
    completed = bt.get('completed', False)
    error = bt.get('error')
    stats = bt.get('statistics', {})
    sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
    net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
    cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
    trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
    return {'completed': completed, 'progress': progress, 'error': error,
            'net_profit': net_profit, 'cagr': cagr, 'sharpe': sharpe, 'trades': trades}

if __name__ == "__main__":
    bt_id = sys.argv[1]
    result = poll_backtest(bt_id)
    print(json.dumps(result, indent=2))