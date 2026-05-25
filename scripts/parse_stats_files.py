#!/usr/bin/env python3
"""
Parse downloaded stats.json files and build table.
"""

import json
import os
import glob

def parse_stats_files():
    stats_files = glob.glob("/Users/falk/projects/kumo-qc/qc/**/*stats.json")
    
    table = []
    
    for stats_file in stats_files:
        with open(stats_file, 'r') as f:
            data = json.load(f)
            
            # Extract window name
            name = data.get("name", "")
            if "perf-" in name:
                window = name.split("-")[1]
            elif "FY2025" in name:
                window = "FY2025"
            else:
                continue  # Skip non-perf runs
            
            sharpe = data.get("sharpe", 0)
            trades = data.get("totalTrades", 0)
            net_profit = data.get("netProfit", 0)
            cagr = data.get("cagr", 0)
            max_dd = data.get("maxDrawdown", 0)
            completed = data.get("completed", False)
            backtest_id = data.get("backtestId", "")
            
            table.append({
                "Window": window,
                "Sharpe": sharpe,
                "Trades": trades,
                "NetProfit": net_profit,
                "CAGR": cagr,
                "MaxDD": max_dd,
                "Completed": completed,
                "BacktestId": backtest_id,
                "File": stats_file
            })
    
    return sorted(table, key=lambda x: x["Window"])

def main():
    table = parse_stats_files()
    
    print("\n=== Results Table (from downloaded files) ===")
    print("Window | Sharpe | Trades | NetProfit | CAGR | MaxDD | Completed | BacktestId")
    print("-" * 80)
    
    for row in table:
        completed_str = "✓" if row["Completed"] else "✗"
        print(f"{row['Window']} | {row['Sharpe']} | {row['Trades']} | {row['NetProfit']} | {row['CAGR']} | {row['MaxDD']} | {completed_str} | {row['BacktestId']}")
    
    # Summary
    print("\n=== Summary ===")
    completed_windows = [row["Window"] for row in table if row["Completed"]]
    pending_windows = [row["Window"] for row in table if not row["Completed"]]
    print(f"Completed: {len(completed_windows)} windows: {', '.join(sorted(completed_windows))}")
    print(f"Pending: {len(pending_windows)} windows: {', '.join(sorted(pending_windows))}")
    
    # Show duplicates
    windows = {}
    for row in table:
        window = row["Window"]
        if window not in windows:
            windows[window] = []
        windows[window].append(row["BacktestId"])
    
    duplicates = {k: v for k, v in windows.items() if len(v) > 1}
    if duplicates:
        print("\n=== Duplicate runs ===")
        for window, ids in duplicates.items():
            print(f"{window}: {ids}")

if __name__ == "__main__":
    main()