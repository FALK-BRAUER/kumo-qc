#!/usr/bin/env python3
"""
Poll W1 backtest until complete with longer wait.
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
        print(f"API error: {e}")
        return {'success': False, 'error': str(e)}

def main():
    bt_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not bt_id:
        # Submit new backtest
        print("Compiling...")
        comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
        compile_id = comp.get('compileId')
        if not compile_id:
            sys.exit(f"Compile failed: {comp}")
        for _ in range(30):
            time.sleep(5)
            r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
            state = r.get('state', '')
            if state == 'BuildSuccess':
                print(f"  Compile OK: {compile_id[:16]}...")
                break
            elif state == 'BuildError':
                sys.exit(f"Build error: {r.get('logs', '')}")
            print(f"  Compile: {state}")
        else:
            sys.exit("Compile timeout")
        
        # Submit W1
        r = qc_post('/backtests/create', {
            'projectId': PROJECT_ID,
            'compileId': compile_id,
            'backtestName': 'perf-W1',
            'parameters': {
                'start_year': '2026', 'start_month': '04', 'start_day': '07',
                'end_year': '2026', 'end_month': '04', 'end_day': '11',
                'cloud_exit': 'True',
                'weekly_kijun_exit': 'True',
                'warmup_days': '750',
            },
        })
        if not r.get('success', False):
            errors = r.get('errors', [])
            if errors and errors[0].startswith('There are no spare nodes available'):
                print("Capacity error — cannot start")
                sys.exit(1)
            print(f"Submit failed: {json.dumps(r)[:200]}")
            sys.exit(1)
        
        bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
        if not bt_id:
            print(f"No backtestId: {json.dumps(r)[:200]}")
            sys.exit(1)
        print(f"Backtest ID: {bt_id[:16]}... submitted")
    
    # Poll for up to 30 minutes
    for i in range(180):
        try:
            r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            bt = r.get('backtest', r)
            completed = bt.get('completed')
            error = bt.get('error')
            
            if completed or error:
                stats = bt.get('statistics', {})
                sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
                net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
                cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
                trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
                print(f"\nW1 DONE: NetProfit={net_profit} CAGR={cagr} Sharpe={sharpe} Trades={trades}")
                if error:
                    print(f"Error: {error}")
                sys.exit(0)
            
            progress = bt.get('progress', 0) * 100
            print(f"Progress: {progress:.0f}%")
                
        except Exception as e:
            print(f"Poll error: {e}")
        
        # Wait 60 seconds between polls
        time.sleep(60)
    
    print("Timeout after 180 minutes")
    sys.exit(1)

if __name__ == "__main__":
    main()