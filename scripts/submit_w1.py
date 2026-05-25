#!/usr/bin/env python3
"""
Submit W1 with correct algorithm (ETF liquidation loop removed).
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
    # submit W1
    compile_and_submit("perf-W1", "2026-04-07", "2026-04-11", 182)

if __name__ == "__main__":
    main()