#!/usr/bin/env python3
"""
Collect QC backtest results into table format.
"""

import os
import json
import sys
import base64
import hashlib
import time
import subprocess
import urllib.request

def get_cred(service, account):
    """Fetch credential from macOS keychain."""
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True
    )
    return r.stdout.strip()

def qc_post(path, body, user_id, api_token):
    """QC API POST request with auth."""
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{api_token}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{user_id}:{h}".encode()).decode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Basic {creds}",
            "Timestamp": ts,
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def main():
    user_id = get_cred("qc-user-id", "kumo-qc")
    api_token = get_cred("qc-api-token", "kumo-qc")
    
    print("Collecting QC backtest results...")
    
    # Results table
    table = []
    
    projects = qc_post("/projects/read", {}, user_id, api_token)
    if projects.get("success"):
        for project in projects.get("projects", []):
            project_id = project.get("projectId")
            project_name = project.get("name", "")
            
            backtests = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
            if backtests.get("success"):
                for bt in backtests.get("backtests", []):
                    if bt.get("completed") == True:
                        # Extract window name
                        name = bt.get("name", "")
                        sharpe = bt.get("sharpeRatio", 0)
                        trades = bt.get("trades", 0)
                        net_profit = bt.get("netProfit", 0)
                        cagr = bt.get("compoundingAnnualReturn", 0)
                        max_dd = bt.get("drawdown", 0)
                        
                        # Check if it's a perf-W window
                        if name.startswith("perf-"):
                            window = name.split("-")[1]
                            table.append({
                                "Window": window,
                                "Sharpe": sharpe,
                                "Trades": trades,
                                "NetProfit": net_profit,
                                "CAGR": cagr,
                                "MaxDD": max_dd,
                                "Completed": True,
                                "Parameters": bt.get("parameterSet", {}),
                                "BacktestId": bt.get("backtestId")
                            })
                        elif name == "FY2025":
                            table.append({
                                "Window": "FY2025",
                                "Sharpe": sharpe,
                                "Trades": trades,
                                "NetProfit": net_profit,
                                "CAGR": cagr,
                                "MaxDD": max_dd,
                                "Completed": True,
                                "Parameters": bt.get("parameterSet", {}),
                                "BacktestId": bt.get("backtestId")
                            })
    
    # Print table
    print("\n=== Results Table ===")
    print("Window | Sharpe | Trades | NetProfit | CAGR | MaxDD | Completed")
    print("-" * 70)
    for row in sorted(table, key=lambda x: x["Window"]):
        completed_str = "✓" if row["Completed"] else "✗"
        print(f"{row['Window']} | {row['Sharpe']} | {row['Trades']} | {row['NetProfit']} | {row['CAGR']} | {row['MaxDD']} | {completed_str}")
    
    # Print pending/active backtests
    print("\n=== Active Backtests ===")
    for project in projects.get("projects", []):
        project_id = project.get("projectId")
        backtests = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
        if backtests.get("success"):
            for bt in backtests.get("backtests", []):
                if bt.get("completed") == False:
                    name = bt.get("name", "")
                    progress = bt.get("progress", 0)
                    print(f"{name}: progress {progress}, status: {bt.get('status', '')}")
    
    return table

if __name__ == "__main__":
    main()