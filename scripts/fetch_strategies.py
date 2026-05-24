#!/usr/bin/env python3
"""
QC Strategy Tracker
Fetch all QC backtests across all projects, create folder structure with tracking index.
"""

import os
import json
import sys
import base64
import hashlib
import time
import subprocess
import urllib.request
from datetime import datetime

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

def list_projects(user_id, api_token):
    """List all QC projects."""
    response = qc_post("/projects/read", {}, user_id, api_token)
    if not response.get("success"):
        print(f"Error listing projects: {response.get('errors', ['unknown'])}")
        return []
    return response.get("projects", [])

def list_backtests(user_id, api_token, project_id):
    """List backtests for a given project."""
    response = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
    if not response.get("success"):
        print(f"Error listing backtests for project {project_id}: {response.get('errors', ['unknown'])}")
        return []
    return response.get("backtests", [])

def fetch_backtest_stats(user_id, api_token, project_id, backtest_id):
    """Fetch detailed stats from individual backtest read."""
    response = qc_post("/backtests/read", {"projectId": project_id, "backtestId": backtest_id}, user_id, api_token)
    if not response.get("success"):
        print(f"Error fetching stats for backtest {backtest_id}: {response.get('errors', ['unknown'])}")
        return None
    return response.get("backtest", {})

def fetch_file(user_id, api_token, project_id, filename="main.py"):
    """Fetch algorithm code file."""
    response = qc_post("/files/read", {"projectId": project_id, "name": filename}, user_id, api_token)
    if not response.get("success"):
        print(f"Error fetching {filename} for project {project_id}: {response.get('errors', ['unknown'])}")
        return None
    return response.get("files", [])[0].get("content", "")

def extract_backtest_stats(user_id, api_token, backtest):
    """Extract key metrics from backtest object."""
    # First try stats from individual read
    detailed = fetch_backtest_stats(user_id, api_token, backtest.get("projectId"), backtest.get("backtestId"))
    if detailed:
        stats = detailed.get("statistics", {})
        sharpe_val = stats.get("Sharpe Ratio", 0)
        cagr_val = stats.get("Compounding Annual Return", 0)
        drawdown_val = stats.get("Drawdown", 0)
        trades_val = stats.get("Total Orders", 0)
        win_rate_val = stats.get("Win Rate", 0)
        net_profit_val = stats.get("Net Profit", 0)
        sparkline = detailed.get("sparkline", "")
    else:
        # Fallback to list stats (might be zero)
        sharpe_val = backtest.get("sharpeRatio", 0)
        cagr_val = backtest.get("compoundingAnnualReturn", 0)
        drawdown_val = backtest.get("drawdown", 0)
        trades_val = backtest.get("trades", 0)
        win_rate_val = backtest.get("winRate", 0)
        net_profit_val = backtest.get("netProfit", 0)
        sparkline = backtest.get("sparkline", "")
    
    # Convert numeric strings to floats if needed
    def to_number(val):
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return 0
        return val
    
    return {
        "name": backtest.get("name", ""),
        "backtestId": backtest.get("backtestId", ""),
        "projectId": backtest.get("projectId", ""),
        "sharpe": to_number(sharpe_val),
        "cagr": to_number(cagr_val),
        "maxDrawdown": to_number(drawdown_val),
        "totalTrades": to_number(trades_val),
        "winRate": to_number(win_rate_val),
        "netProfit": to_number(net_profit_val),
        "sparkline": sparkline,
        "completed": backtest.get("completed", False),
        "created": backtest.get("created", "")
    }

def create_folder_name(index, name):
    """Create folder name like 01_<backtest-name>."""
    # Clean name: remove special chars, limit length
    clean_name = name.replace("/", "_").replace(":", "_").replace("?", "_")
    clean_name = clean_name[:50]  # Limit length
    return f"{index:02d}_{clean_name}"

def write_index_file(all_stats):
    """Create INDEX.md in qc/ folder."""
    lines = []
    lines.append("# QC Strategy Index")
    lines.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d')}*")
    lines.append("")
    lines.append("| # | Name | Project | Sharpe | CAGR | Max DD | Trades | Win% | Status |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    
    for idx, stats in enumerate(all_stats):
        folder_name = create_folder_name(idx + 1, stats["name"])
        status = "✅ Downloaded" if stats.get("algorithm_downloaded", False) else "⏳ To process"
        lines.append(
            f"| {idx + 1:02d} | {stats['name']} | {stats['projectId']} | {stats['sharpe']} | {stats['cagr']} | {stats['maxDrawdown']} | {stats['totalTrades']} | {stats['winRate']} | {status} |"
        )
    
    lines.append("")
    lines.append("Status values: `✅ Downloaded` | `⏳ To process` | `❌ Failed`")
    
    return "\n".join(lines)

def write_strategy_readme(stats):
    """Create README.md for a single strategy."""
    lines = []
    lines.append(f"# {stats['name']}")
    lines.append(f"**Project:** {stats['projectId']}")
    lines.append(f"**Run date:** {stats['created']}")
    lines.append(f"**Backtest ID:** {stats['backtestId']}")
    lines.append("")
    lines.append("## Key Metrics")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Sharpe | {stats['sharpe']} |")
    lines.append(f"| CAGR | {stats['cagr']} |")
    lines.append(f"| Max Drawdown | {stats['maxDrawdown']} |")
    lines.append(f"| Total Trades | {stats['totalTrades']} |")
    lines.append(f"| Win Rate | {stats['winRate']} |")
    lines.append(f"| Net Profit | {stats['netProfit']} |")
    lines.append("")
    lines.append("## Conditions")
    lines.append("*To be filled after analysis*")
    
    return "\n".join(lines)

def main():
    print("Fetching QC credentials from macOS keychain...")
    user_id = get_cred("qc-user-id", "kumo-qc")
    api_token = get_cred("qc-api-token", "kumo-qc")
    
    if not user_id or not api_token:
        print("Error: Could not fetch QC credentials from keychain.")
        sys.exit(1)
    
    print(f"User ID: {user_id}")
    
    print("Listing projects...")
    projects = list_projects(user_id, api_token)
    print(f"Found {len(projects)} projects")
    
    all_backtests = []
    for project in projects:
        project_id = project.get("projectId")
        project_name = project.get("name", "")
        print(f"  Project {project_id}: {project_name}")
        
        backtests = list_backtests(user_id, api_token, project_id)
        for bt in backtests:
            stats = extract_backtest_stats(user_id, api_token, bt)
            stats["projectName"] = project_name
            all_backtests.append(stats)
    
    print(f"Total backtests found: {len(all_backtests)}")
    
    # Filter completed backtests only
    completed_backtests = [bt for bt in all_backtests if bt["completed"]]
    print(f"Completed backtests: {len(completed_backtests)}")
    
    # Sort by Sharpe desc (convert string to float if needed)
    sorted_backtests = sorted(completed_backtests, key=lambda x: float(x["sharpe"]) if isinstance(x["sharpe"], str) else x["sharpe"], reverse=True)
    top_backtests = sorted_backtests[:20]  # Top 20
    
    print("Top 20 backtests by Sharpe:")
    for idx, bt in enumerate(top_backtests):
        print(f"  #{idx+1}: {bt['name']} (Sharpe={bt['sharpe']})")
    
    # Create qc/ directory
    qc_dir = "/Users/falk/projects/kumo-qc/qc"
    if not os.path.exists(qc_dir):
        os.makedirs(qc_dir)
    
    # Download algorithm files for top backtests
    for idx, stats in enumerate(top_backtests):
        folder_name = create_folder_name(idx + 1, stats["name"])
        folder_path = os.path.join(qc_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        
        # Download algorithm.py
        algorithm_content = fetch_file(user_id, api_token, stats["projectId"])
        if algorithm_content:
            stats["algorithm_downloaded"] = True
            with open(os.path.join(folder_path, "algorithm.py"), "w") as f:
                f.write(algorithm_content)
            print(f"  Downloaded algorithm.py for {stats['name']}")
        else:
            stats["algorithm_downloaded"] = False
            print(f"  Failed to download algorithm.py for {stats['name']}")
        
        # Write stats.json
        with open(os.path.join(folder_path, "stats.json"), "w") as f:
            json.dump(stats, f, indent=2)
        
        # Write README.md
        readme_content = write_strategy_readme(stats)
        with open(os.path.join(folder_path, "README.md"), "w") as f:
            f.write(readme_content)
    
    # Write INDEX.md
    index_content = write_index_file(top_backtests)
    with open(os.path.join(qc_dir, "INDEX.md"), "w") as f:
        f.write(index_content)
    
    print(f"Index created at {qc_dir}/INDEX.md")
    print("Done.")

if __name__ == "__main__":
    main()