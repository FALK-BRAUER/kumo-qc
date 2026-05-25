#!/usr/bin/env python3
"""
Poll W1 backtest until complete.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = "6e942fc72cb440b569fcc3292e5f28ac"

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
        return {'success': False, 'error': str(e)}

def main():
    for i in range(60):
        try:
            r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
            bt = r.get('backtest', r)
            if bt.get('completed'):
                stats = bt.get('statistics', {})
                sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
                net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
                cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
                trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
                print(f"W1 DONE: NetProfit={net_profit} CAGR={cagr} Sharpe={sharpe} Trades={trades}")
                return
            progress = bt.get('progress', 0) * 100
            print(f"W1: {progress:.0f}%")
        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(30)
    print("W1: timeout after 30 minutes")

if __name__ == "__main__":
    main()