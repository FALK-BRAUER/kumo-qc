#!/usr/bin/env python3
"""
Run W1-W3 sequentially with reduced warmup_days=10 to avoid Isolator timeout.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
PROJECT_ID = 32034565

WINDOWS = [
    ("W1", "2026-04-07", "2026-04-11"),
    ("W2", "2026-04-14", "2026-04-18"),
    ("W3", "2026-04-22", "2026-04-25"),
]


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

def compile_project():
    print("Compiling...")
    comp = qc_post('/compile/create', {'projectId': PROJECT_ID})
    compile_id = comp.get('compileId')
    if not compile_id:
        sys.exit(f"Compile failed: {comp}")
    # Poll until not InQueue
    for _ in range(30):
        time.sleep(5)
        r = qc_post('/compile/read', {'projectId': PROJECT_ID, 'compileId': compile_id})
        state = r.get('state', '')
        if state == 'BuildSuccess':
            print(f"  Compile OK: {compile_id[:16]}...")
            # Delete any auto-generated backtest
            delete_auto_backtest()
            return compile_id
        elif state == 'BuildError':
            sys.exit(f"Build error: {r.get('logs', '')}")
        print(f"  Compile: {state}")
    sys.exit("Compile timeout")

def delete_auto_backtest():
    """Delete any auto-generated backtest after compile."""
    backtests = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    if not backtests.get('success'):
        return
    bt_list = backtests.get('backtests', [])
    for bt in bt_list:
        bt_id = bt.get('backtestId')
        name = bt.get('name')
        # Delete ALL backtests except completed ones
        # QC creates default backtest automatically after compile
        if bt_id:
            print(f"  Deleting auto-generated backtest {name} ({bt_id[:16]}...)")
            try:
                qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            except Exception as e:
                print(f"  Delete failed: {e}")

def submit_backtest(name, start, end, compile_id):
    sy, sm, sd = start.split("-")
    ey, em, ed = end.split("-")
    
    # Use reduced warmup for short windows
    warmup_days = 10
    
    r = qc_post('/backtests/create', {
        'projectId': PROJECT_ID,
        'compileId': compile_id,
        'backtestName': f"perf-{name}",
        'parameters': {
            'start_year': sy, 'start_month': sm, 'start_day': sd,
            'end_year': ey, 'end_month': em, 'end_day': ed,
            'cloud_exit': 'True',
            'weekly_kijun_exit': 'True',
            'warmup_days': str(warmup_days),
        },
    })
    if not r.get('success', False):
        errors = r.get('errors', [])
        if errors and errors[0].startswith('There are no spare nodes available'):
            print(f"  {name}: capacity error — cannot start")
            return None
        print(f"  {name}: submit failed — {json.dumps(r)[:200]}")
        return None
    bt_id = r.get('backtestId') or (r.get('backtest', {}) or {}).get('backtestId')
    if not bt_id:
        print(f"  {name}: no backtestId — {json.dumps(r)[:200]}")
        return None
    print(f"  {name}: {bt_id[:16]}... submitted")
    return bt_id

def poll_backtest(name, bt_id):
    # Short windows should be faster
    for i in range(120):
        time.sleep(15)
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': bt_id})
        bt = r.get('backtest', r)
        progress = bt.get('progress', 0) * 100
        completed = bt.get('completed', False)
        error = bt.get('error')
        if completed or error:
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
            net_profit = stats.get('Net Profit', stats.get('TotalNetProfit', 'n/a'))
            cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
            trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
            print(f"  {name} DONE: NetProfit={net_profit}  CAGR={cagr}  Sharpe={sharpe}  Trades={trades}  error={error}")
            return {'name': name, 'net_profit': net_profit, 'cagr': cagr, 'sharpe': sharpe, 'trades': trades, 'error': error}
        if i % 4 == 0:
            print(f"  {name}: {progress:.0f}%")
        if i >= 90 and progress < 1.0:
            print(f"  {name}: stuck at {progress:.0f}% after {i*15}s — deleting")
            try:
                qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
            except:
                pass
            return {'name': name, 'error': 'stuck'}
    print(f"  {name}: timeout after 30 minutes")
    try:
        qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
    except:
        pass
    return {'name': name, 'error': 'timeout'}

def main():
    compile_id = compile_project()
    results = []

    for name, start, end in WINDOWS:
        print(f"\nStarting {name} ({start} → {end})...")
        bt_id = submit_backtest(name, start, end, compile_id)
        if bt_id:
            result = poll_backtest(name, bt_id)
            results.append(result)
        else:
            results.append({'name': name, 'error': 'failed submit'})
        time.sleep(5)

    print("\n" + "=" * 60)
    print("PERFORMANCE RESULTS")
    print(f"{'Window':<10} {'NetProfit':<14} {'CAGR':<12} {'Sharpe':<10} {'Trades'}")
    print("-" * 60)
    for r in results:
        if r.get('error') and r['error'] != 'None':
            print(f"{r['name']:<10} ERROR: {r['error']}")
        else:
            print(f"{r['name']:<10} {str(r.get('net_profit','')):<14} {str(r.get('cagr','')):<12} {str(r.get('sharpe','')):<10} {r.get('trades','')}")
    print("=" * 60)
    
    # Save results to qc/INDEX.md
    update_index(results)

def update_index(results):
    """Update qc/INDEX.md with W1-W3 results."""
    import os
    index_path = '/Users/falk/projects/kumo-qc/qc/INDEX.md'
    
    # Read existing content
    if os.path.exists(index_path):
        with open(index_path, 'r') as f:
            content = f.read()
    else:
        content = ""
    
    # Add results section
    timestamp = time.strftime("%Y-%m-%d %H:%M")
    new_section = f"\n## W1-W3 Short Window Results ({timestamp})\n\n"
    new_section += f"| Window | NetProfit | CAGR | Sharpe | Trades |\n"
    new_section += f"|--------|-----------|------|--------|--------|\n"
    
    for r in results:
        if r.get('error') and r['error'] != 'None':
            new_section += f"| {r['name']} | ERROR: {r['error']} | | | |\n"
        else:
            net_profit = r.get('net_profit', 'n/a')
            cagr = r.get('cagr', 'n/a')
            sharpe = r.get('sharpe', 'n/a')
            trades = r.get('trades', 'n/a')
            new_section += f"| {r['name']} | {net_profit} | {cagr} | {sharpe} | {trades} |\n"
    
    new_section += f"\n**Parameters:** warmup_days=10, cloud_exit=True, weekly_kijun_exit=True\n"
    
    # Append to file
    with open(index_path, 'a') as f:
        f.write(new_section)
    
    print(f"\nResults saved to {index_path}")

if __name__ == "__main__":
    main()