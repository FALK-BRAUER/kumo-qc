#!/usr/bin/env python3
"""
List all backtests for performance_bct project with details.
"""
import json, hashlib, time, base64, subprocess, sys
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def main():
    resp = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    if resp.get('success'):
        bt_list = resp.get('backtests', [])
        for bt in bt_list:
            bt_id = bt.get('backtestId')
            name = bt.get('name')
            progress = bt.get('progress')
            completed = bt.get('completed')
            error = bt.get('error')
            state = bt.get('state')
            print(f"{bt_id[:16]} {name} progress={progress} completed={completed} error={error} state={state}")
            if completed:
                # fetch details
                detail = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
                if detail.get('success'):
                    bt_detail = detail.get('backtest', detail)
                    sharpe = bt_detail.get('statistics', {}).get('Sharpe Ratio', 'N/A')
                    net_profit = bt_detail.get('statistics', {}).get('Total Net Profit', 'N/A')
                    print(f"  Sharpe={sharpe}, NetProfit={net_profit}")
    else:
        print("Failed:", resp)

if __name__ == "__main__":
    main()