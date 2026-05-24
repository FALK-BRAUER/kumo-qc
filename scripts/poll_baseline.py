#!/usr/bin/env python3
"""
Poll baseline-exits-on-2020-2026 backtest status and report Sharpe, CAGR, trades.
Check if parity-cloud-2025 is still running (Sharpe mismatch 0.192 vs -0.7485).
"""
import json, hashlib, time, base64, subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = "3c2c5cc39c5cca5b9c4729bd07d17d1a"  # baseline-exits-on-2020-2026

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

def poll_status():
    """Poll backtest status and return Sharpe, CAGR, trades, max DD when complete"""
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
        bt = r.get('backtest', r)
        progress = bt.get('progress', 0) * 100
        completed = bt.get('completed', False)
        error = bt.get('error')
        
        print(f"Progress: {progress:.1f}%")
        print(f"Completed: {completed}")
        print(f"Error: {error}")
        
        if completed:
            stats = bt.get('statistics', {})
            sharpe = stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'n/a'))
            cagr = stats.get('Compounding Annual Return', stats.get('CAR', 'n/a'))
            trades = stats.get('Total Orders', stats.get('TotalTrades', 'n/a'))
            max_dd = stats.get('Maximum Drawdown', stats.get('Maximum Drawdown', 'n/a'))
            
            print("\n" + "=" * 60)
            print("BASELINE RESULTS (exits ON, 2020-2026)")
            print(f"Sharpe Ratio: {sharpe}")
            print(f"CAGR: {cagr}")
            print(f"Total Trades: {trades}")
            print(f"Maximum Drawdown: {max_dd}")
            print("=" * 60)
            
            return {
                'progress': progress,
                'completed': completed,
                'error': error,
                'sharpe': sharpe,
                'cagr': cagr,
                'trades': trades,
                'max_dd': max_dd
            }
        else:
            print("Backtest still running...")
            return {'progress': progress, 'completed': False}
    
    except Exception as e:
        print(f"API error: {e}")
        return {'error': str(e)}

def cancel_backtest():
    """Cancel baseline backtest if stuck"""
    try:
        r = qc_post('/backtests/stop', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
        print(f"Cancel attempt result: {r}")
        return r
    except Exception as e:
        print(f"Cancel error: {e}")
        return {'error': str(e)}

def list_all_backtests():
    """List all backtests for performance_bct to find parity-cloud-2025"""
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
        backtests = r.get('backtests', [])
        print("\nALL BACKTESTS:")
        for bt in backtests:
            name = bt.get('name')
            completed = bt.get('completed')
            progress = bt.get('progress', 0) * 100
            print(f"  {name}: {progress:.1f}% {completed}")
        return backtests
    except Exception as e:
        print(f"List error: {e}")
        return []

if __name__ == "__main__":
    print("Checking baseline status...")
    result = poll_status()
    print(json.dumps(result, indent=2))
    
    print("\nChecking all backtests...")
    all_backtests = list_all_backtests()
    
    # Find parity-cloud-2025
    parity = None
    for bt in all_backtests:
        if bt.get('name') == 'parity-cloud-2025':
            parity = bt
            break
    
    if parity:
        parity_progress = parity.get('progress', 0) * 100
        parity_completed = parity.get('completed')
        print(f"\nparity-cloud-2025: {parity_progress:.1f}% completed={parity_completed}")
        
        if not parity_completed and parity_progress < 100:
            print("parity-cloud-2025 could be cancelled to free node for baseline")
        else:
            print("parity-cloud-2025 already completed or done")
    
    # Cancel baseline if progress stuck
    baseline_progress = result.get('progress', 0)
    if baseline_progress < 50 and not result.get('completed'):
        print("\nbaseline-exits-on-2020-2026 stuck at {:.1f}% — cancelling".format(baseline_progress))
        cancel_result = cancel_backtest()
        print(f"Cancel response: {cancel_result}")