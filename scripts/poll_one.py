#!/usr/bin/env python3
"""
Poll a single backtest until completed, output stats.
"""
import json, hashlib, time, base64, subprocess, sys

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
        resp = urllib.request.urlopen(req).read()
        return json.loads(resp)
    except Exception as e:
        print(f"  API error: {e}")
        return {}

import urllib.request

def poll_until_done(bt_id):
    while True:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', {})
        if bt.get('completed'):
            stats = bt.get('statistics', {})
            return {
                'name': bt.get('name'),
                'sharpe': stats.get('Sharpe Ratio'),
                'net_profit': stats.get('Net Profit'),
                'trades': stats.get('Total Orders'),
                'cagr': stats.get('Compounding Annual Return')
            }
        print(f"  Progress {bt.get('progress', 0)}")
        time.sleep(30)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 poll_one.py <backtest_id>")
        sys.exit(1)
    bt_id = sys.argv[1]
    result = poll_until_done(bt_id)
    print(f"\nResult for {result.get('name')}:")
    print(f"Sharpe={result.get('sharpe')}")
    print(f"NetProfit={result.get('net_profit')}")
    print(f"CAGR={result.get('cagr')}")
    print(f"Trades={result.get('trades')}")