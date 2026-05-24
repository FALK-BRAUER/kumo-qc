#!/usr/bin/env python3
"""
Run only W4 parity test (2026-04-28 to 2026-05-02) using lean-api.json config.
Target Sharpe: 16.118 with 10 trades (QC cloud W4 results).
"""

import subprocess
import time
from pathlib import Path
import json

ALGO_PATH = Path("algorithm/performance_bct")
W4_WINDOW = ("W4", "2026-04-28", "2026-05-02")

def check_lean_installed():
    try:
        subprocess.run(["lean", "--version"], capture_output=True, timeout=2)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def run_w4():
    """Run single lean backtest for W4 window."""
    name, start, end = W4_WINDOW
    result_dir = Path("results") / name
    result_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "lean", "backtest", str(ALGO_PATH),
        "--output", str(result_dir),
        "--lean-config", "lean-api.json",
        "--parameter", "start_year", str(start.split("-")[0]),
        "--parameter", "start_month", str(start.split("-")[1]),
        "--parameter", "start_day", str(start.split("-")[2]),
        "--parameter", "end_year", str(end.split("-")[0]),
        "--parameter", "end_month", str(end.split("-")[1]),
        "--parameter", "end_day", str(end.split("-")[2]),
    ]

    print(f"[{name}] Starting: {start} → {end}")
    print(f"[{name}] Command: {cmd}")
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        stdout_lines = []
        stderr_lines = []
        
        while True:
            line = proc.stdout.readline()
            if line:
                stdout_lines.append(line.strip())
                print(f"[{name}] {line.strip()}")
            
            err_line = proc.stderr.readline()
            if err_line:
                stderr_lines.append(err_line.strip())
                print(f"[{name}] [ERROR] {err_line.strip()}")
            
            status = proc.poll()
            if status is not None:
                break
            
            time.sleep(0.1)
        
        stdout_remain, stderr_remain = proc.communicate(timeout=5)
        stdout_lines.extend(stdout_remain.splitlines())
        stderr_lines.extend(stderr_remain.splitlines())
        
        # Find results.json
        backtests_dir = result_dir / "backtests"
        results_json = None
        if backtests_dir.exists():
            for timestamp_dir in backtests_dir.iterdir():
                if timestamp_dir.is_dir():
                    results_path = timestamp_dir / "output" / "results.json"
                    if results_path.exists():
                        results_json = results_path
                        break
        
        if results_json:
            with open(results_json) as f:
                data = json.load(f)
            stats = data.get("statistics", {})
            sharpe = stats.get("Sharpe Ratio", stats.get("SharpeRatio", "n/a"))
            trades = stats.get("Total Trades", stats.get("TotalOrders", "n/a"))
            net_profit = stats.get("Total Net Profit", stats.get("Net Profit", "n/a"))
            
            print(f"\n[{name}] RESULTS:")
            print(f"  Sharpe Ratio: {sharpe}")
            print(f"  Total Trades: {trades}")
            print(f"  Net Profit: {net_profit}")
            print(f"\nQC Cloud W4 baseline: Sharpe 16.118, 10 trades")
            
            # Compare
            target_sharpe = 16.118
            target_trades = 10
            
            if isinstance(sharpe, (int, float)):
                sharpe_match = abs(float(sharpe) - target_sharpe) <= 0.1
                trades_match = int(trades) == target_trades if isinstance(trades, int) else trades == target_trades
                
                print(f"\nPARITY CHECK:")
                print(f"  Sharpe diff: {float(sharpe) - target_sharpe}")
                print(f"  Sharpe match: {sharpe_match}")
                print(f"  Trades match: {trades_match}")
                print(f"  Parity achieved: {sharpe_match and trades_match}")
        
        print(f"[{name}] Completed with exit code {status}")
        
    except Exception as e:
        print(f"[{name}] ERROR: {e}")

def main():
    if not check_lean_installed():
        print("ERROR: lean CLI not found")
        return
    
    print("Running W4 parity test (QC cloud Sharpe 16.118, 10 trades)")
    print("Algorithm path: {}".format(ALGO_PATH))
    
    Path("results").mkdir(exist_ok=True)
    run_w4()

if __name__ == "__main__":
    main()