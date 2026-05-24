#!/usr/bin/env python3
"""
Fetch backtest results.
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
        return {'error': str(e)}

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 get_backtest_results.py <backtest_id>")
        sys.exit(1)
    
    bt_id = sys.argv[1]
    print(f"Fetching backtest {bt_id[:16]}...")
    
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    bt = r.get('backtest', r)
    
    print(f"Status: {bt.get('status')}")
    print(f"Completed: {bt.get('completed')}")
    print(f"Progress: {bt.get('progress')}")
    print(f"Error: {bt.get('error')}")
    
    stats = bt.get('statistics', {})
    print("\nStatistics:")
    print(f"  Sharpe Ratio: {stats.get('Sharpe Ratio')}")
    print(f"  CAGR: {stats.get('CAGR')}")
    print(f"  Max Drawdown: {stats.get('Maximum Drawdown')}")
    print(f"  Trades: {stats.get('Total Trades')}")
    
    runtime = bt.get('runtimeStatistics', {})
    print("\nRuntime:")
    print(f"  Total Runtime: {runtime.get('TotalRuntime')}")
    
    perf = bt.get('totalPerformance', {})
    if perf:
        print(f"\nTotal Performance:")
        print(f"  NetProfit: {perf.get('NetProfit')}")
    
    print(json.dumps(r, indent=2))

if __name__ == "__main__":
    main()