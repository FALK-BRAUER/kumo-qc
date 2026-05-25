#!/usr/bin/env python3
"""
Wait for FY2025 completion, record Sharpe/trades, delete W1, submit new W1.
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

def poll_backtest(bt_id):
    resp = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id, 'results': False})
    if resp.get('success'):
        bt = resp.get('backtest', resp)
        progress = bt.get('progress')
        completed = bt.get('completed')
        error = bt.get('error')
        name = bt.get('name')
        print(f"{name} progress={progress} completed={completed} error={error}")
        return bt
    else:
        print(f"Poll failed: {resp}")
        return None

def delete_backtest(bt_id):
    print(f"Deleting backtest {bt_id}")
    resp = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    if resp.get('success'):
        print(f"Deleted {bt_id}")
    else:
        print(f"Delete failed: {resp}")

def compile_and_submit(name, start_date, end_date, warmup_days):
    print(f"Compiling for {name}...")
    comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
    compile_id = comp.get('compileId')
    if not compile_id:
        print(f"Compile failed: {comp}")
        return None

    print(f"compileId: {compile_id}")
    # poll compile status
    for i in range(30):
        time.sleep(5)
        r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
        state = r.get('state', '')
        if state == 'BuildSuccess':
            print(f"Compile succeeded at iteration {i}")
            break
        elif state == 'BuildError':
            print(f"Compile error: {r}")
            return None
        print(f"Compile state {state}...")
    else:
        print("Compile timeout")
        return None

    # submit backtest
    print(f"Submitting {name} backtest...")
    submit = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': name,
        'parameters': {
            'start_year': start_date.split('-')[0],
            'start_month': start_date.split('-')[1],
            'start_day': start_date.split('-')[2],
            'end_year': end_date.split('-')[0],
            'end_month': end_date.split('-')[1],
            'end_day': end_date.split('-')[2],
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'warmup_days': str(warmup_days)
        }
    })
    backtest = submit.get('backtest')
    if not backtest:
        print(f"Submit failed: {submit}")
        return None
    backtest_id = backtest.get('backtestId')
    print(f"Backtest ID: {backtest_id}")
    print(f"Name: {name}")
    print(f"Start: {start_date}, End: {end_date}, warmup_days: {warmup_days}")
    return backtest_id

def main():
    fy2025_id = "1051b475c856baaf35973221512bf281"
    w1_id = "1a20f110b4974b69e2b224cca61ae4fe"
    
    # wait for FY2025 completion
    print(f"Waiting for FY2025 {fy2025_id}...")
    while True:
        bt = poll_backtest(fy2025_id)
        if bt is None:
            break
        if bt.get('completed'):
            # record Sharpe and trades
            stats = bt.get('statistics', {})
            total_performance = bt.get('totalPerformance', {})
            trade_stats = total_performance.get('tradeStatistics', {})
            sharpe = stats.get('Sharpe Ratio', '0')
            trades = trade_stats.get('totalNumberOfTrades', 0)
            print(f"FY2025 completed. Sharpe Ratio: {sharpe}, Trades: {trades}")
            break
        time.sleep(30)
    
    # delete W1 (zero trades due to ETF liquidation bug)
    delete_backtest(w1_id)
    
    # submit new W1
    compile_and_submit("perf-W1", "2026-04-07", "2026-04-11", 182)

if __name__ == "__main__":
    main()