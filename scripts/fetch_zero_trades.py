#!/usr/bin/env python3
"""
Fetch QC backtests for project 32034565, find exits‑ON W1‑W6 runs (rows 13‑20).
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

def fetch_all():
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    backtests = r.get('backtests', [])
    zero_names = [
        "perf-FY2025",
        "perf-W6",
        "perf-W5",
        "perf-W4",
        "perf-W3",
        "perf-W2",
        "perf-W1"
    ]
    zero_trades_runs = []
    for bt in backtests:
        name = bt.get('name')
        if name in zero_names:
            bt_id = bt.get('backtestId')
            progress = bt.get('progress', 0) * 100
            completed = bt.get('completed')
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', stats.get('Sharpe Ratio', 'n/a')))
            trades = stats.get('Total Orders', stats.get('TotalTrades', stats.get('Total Orders', 'n/a')))
            error = bt.get('error')
            zero_trades_runs.append({
                'name': name,
                'backtestId': bt_id,
                'progress': progress,
                'completed': completed,
                'sharpe': sharpe,
                'trades': trades,
                'error': error
            })
    return zero_trades_runs

if __name__ == "__main__":
    runs = fetch_all()
    print(f"Found {len(runs)} zero-trade runs:")
    for r in runs:
        print(f"{r['name']}: id={r['backtestId'][:16]}..., progress={r['progress']:.1f}%, completed={r['completed']}, Sharpe={r['sharpe']}, trades={r['trades']}, error={r['error']}")
    
    print("\nChecking baseline-fixed-2020-2026:")
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': '98a49a59d4c5eaeee87496c1bc9112e9'})
        bt = r.get('backtest', r)
        print(f"Progress: {bt.get('progress', 0)*100:.1f}%")
        print(f"Completed: {bt.get('completed')}")
    except Exception as e:
        print(f"Error fetching baseline-fixed: {e}")