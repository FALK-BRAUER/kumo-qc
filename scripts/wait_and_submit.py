#!/usr/bin/env python3
"""
Wait for current backtest to complete, then submit next window.
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
        'name': name,
        'backtest': {
            'startDate': start_date,
            'endDate': end_date,
            'parameters': {
                'cloud_exit': 'True',
                'weekly_kijun_exit': 'True',
                'warmup_days': warmup_days
            }
        }
    })
    backtest_id = submit.get('backtestId')
    if not backtest_id:
        print(f"Submit failed: {submit}")
        return None
    print(f"Backtest ID: {backtest_id}")
    print(f"Name: {name}")
    print(f"Start: {start_date}, End: {end_date}, warmup_days: {warmup_days}")
    return backtest_id

def main():
    # current backtest ID
    current_id = "d48a78c0fd79606fc0832d75b4a31f87"
    print(f"Waiting for {current_id}...")
    while True:
        bt = poll_backtest(current_id)
        if bt is None:
            break
        if bt.get('completed'):
            print(f"Completed with error={bt.get('error')}")
            break
        time.sleep(10)

    # submit W2
    compile_and_submit("perf-W2", "2026-04-14", "2026-04-18", 200)

if __name__ == "__main__":
    main()