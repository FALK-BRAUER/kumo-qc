#!/usr/bin/env python3
"""
Filter duplicate results to show only most recent/latest runs.
"""

import json
import os
import glob

def filter_results():
    stats_files = glob.glob("/Users/falk/projects/kumo-qc/qc/**/*stats.json")
    
    # Group by window, keep only most recent (highest sharpe for completed)
    window_data = {}
    
    for stats_file in stats_files:
        with open(stats_file, 'r') as f:
            data = json.load(f)
            
            # Extract window name
            name = data.get("name", "")
            if "perf-" in name:
                window = name.split("-")[1]
            elif "FY2025" in name:
                window = "FY2025"
            elif name == "perf":
                window = "perf"
            else:
                continue
            
            sharpe_str = data.get("sharpe", 0)
            # Convert to float if possible
            if isinstance(sharpe_str, str):
                sharpe = float(sharpe_str) if sharpe_str.replace('.', '').isdigit() else 0
            else:
                sharpe = sharpe_str
            trades = data.get("totalTrades", 0)
            net_profit = data.get("netProfit", 0)
            cagr = data.get("cagr", 0)
            max_dd = data.get("maxDrawdown", 0)
            completed = data.get("completed", False)
            backtest_id = data.get("backtestId", "")
            
            # Keep best (highest sharpe) for completed runs
            if window not in window_data:
                window_data[window] = []
            
            window_data[window].append({
                "Sharpe": sharpe,
                "Trades": trades,
                "NetProfit": net_profit,
                "CAGR": cagr,
                "MaxDD": max_dd,
                "Completed": completed,
                "BacktestId": backtest_id,
                "File": stats_file
            })
    
    # Filter: pick completed runs first, then highest sharpe
    filtered = []
    for window, runs in window_data.items():
        completed_runs = [r for r in runs if r["Completed"]]
        if completed_runs:
            # Pick the one with highest Sharpe
            best = max(completed_runs, key=lambda x: x["Sharpe"])
            filtered.append({
                "Window": window,
                "Sharpe": best["Sharpe"],
                "Trades": best["Trades"],
                "NetProfit": best["NetProfit"],
                "CAGR": best["CAGR"],
                "MaxDD": best["MaxDD"],
                "Completed": True,
                "BacktestId": best["BacktestId"]
            })
        else:
            # Pick any pending run
            pending = runs[0]
            filtered.append({
                "Window": window,
                "Sharpe": pending["Sharpe"],
                "Trades": pending["Trades"],
                "NetProfit": pending["NetProfit"],
                "CAGR": pending["CAGR"],
                "MaxDD": pending["MaxDD"],
                "Completed": False,
                "BacktestId": pending["BacktestId"]
            })
    
    return sorted(filtered, key=lambda x: x["Window"])

def main():
    filtered = filter_results()
    
    print("\n=== Filtered Results Table (latest/most relevant) ===")
    print("Window | Sharpe | Trades | NetProfit | CAGR | MaxDD | Completed")
    print("-" * 60)
    
    for row in filtered:
        completed_str = "✓" if row["Completed"] else "✗"
        print(f"{row['Window']} | {row['Sharpe']} | {row['Trades']} | {row['NetProfit']} | {row['CAGR']} | {row['MaxDD']} | {completed_str}")
    
    # Show progress status
    print("\n=== Status Summary ===")
    windows_completed = [row["Window"] for row in filtered if row["Completed"]]
    windows_pending = [row["Window"] for row in filtered if not row["Completed"]]
    
    print(f"Completed windows: {', '.join(sorted(windows_completed))}")
    print(f"Pending windows: {', '.join(sorted(windows_pending))}")
    
    # Special: perf-W1 currently running (from API)
    print(f"Active: perf-W1 (progress 0.102)")
    
    return filtered

if __name__ == "__main__":
    main()