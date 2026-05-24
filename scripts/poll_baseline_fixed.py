#!/usr/bin/env python3
"""
Poll baseline-fixed-2020-2026 (ETF fix applied) backtest status.
"""
import json, hashlib, time, base64, subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565
BACKTEST_ID = "98a49a59d4c5eaeee87496c1bc9112e9"  # baseline-fixed-2020-2026

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
    """Poll baseline-fixed status and return Sharpe, CAGR, trades, max DD when complete"""
    try:
        r = qc_post('/backtests/read', {'projectId': PROJECT_ID, 'backtestId': BACKTEST_ID})
        bt = r.get('backtest', r)
        progress = bt.get('progress', 0) * 100
        completed = bt.get('completed', False)
        error = bt['error']
        
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
            print("BASELINE-FIXED RESULTS (ETF bug fixed, COARSE_MAX 9999)")
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

if __name__ == "__main__":
    result = poll_status()
    print(json.dumps(result, indent=2))