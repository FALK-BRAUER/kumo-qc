#!/usr/bin/env python3
"""
Fetch QC API details for zero Sharpe/trades runs (rows 13‑20).
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

zero_ids = [
    ("12_perf-FY2025", "99a65adba1cb3a77155198b980fcce1c"),
    ("13_perf-W6", "88cfe683fc71388521555a52534cc413"),
    ("14_perf-W5", "73a89b7206b749b5af79f4be8eb0b3e2"),
    ("15_perf-W4", "db9fa1dfe204e8d4386c6822020dd5fb"),
    ("16_perf-W3", "7ed19e108f47727fe67b632c8d3debdb"),
    ("17_perf-W2", "19b979ce251300439aef2226577f83c7"),
    ("18_perf-W1", "7dc36e882f10c1f45441c996066124a7"),
    ("19_perf-FY2025", "c37a226a4fad1e5a5038c3980e917c51"),
]

print("Zero Sharpe/trades runs:")
for name, bt_id in zero_ids:
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', r)
        completed = bt.get('completed')
        error = bt.get('error')
        stats = bt.get('statistics', {})
        sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', stats.get('Sharpe Ratio', 'n/a')))
        trades = stats.get('Total Orders', stats.get('TotalTrades', stats.get('Total Orders', 'n/a')))
        print(f"{name}: id={bt_id[:16]}, completed={completed}, error={error}, Sharpe={sharpe}, trades={trades}")
    except Exception as e:
        print(f"{name}: error fetching {e}")