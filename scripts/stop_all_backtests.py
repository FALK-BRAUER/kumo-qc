#!/usr/bin/env python3
"""
Stop all running QC backtests for performance_bct project 32034565.
"""
import os
import json
import requests
import sys

USER_ID = os.environ.get("QC_USER_ID")
API_TOKEN = os.environ.get("QC_API_TOKEN")
if not USER_ID or not API_TOKEN:
    print("Missing QC_USER_ID or QC_API_TOKEN env vars")
    sys.exit(1)

PROJECT_ID = "32034565"

base_url = "https://www.quantconnect.com/api/v2"
headers = {"Authorization": f"Bearer {API_TOKEN}"}

def get_backtests():
    """List all backtests for project."""
    resp = requests.get(f"{base_url}/projects/{PROJECT_ID}/backtests", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch backtests: {resp.status_code}")
        return []
    data = resp.json()
    return data.get("backtests", [])

def stop_backtest(backtest_id):
    """Stop a running backtest."""
    resp = requests.delete(f"{base_url}/projects/{PROJECT_ID}/backtests/{backtest_id}", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to stop {backtest_id}: {resp.status_code}")
        return False
    print(f"Stopped backtest {backtest_id}")
    return True

def main():
    backtests = get_backtests()
    if not backtests:
        print("No backtests found")
        return

    running = []
    for bt in backtests:
        if bt.get("status") == "running" or bt.get("status") == "In Progress...":
            running.append(bt["backtestId"])

    if not running:
        print("No running backtests")
        return

    print(f"Stopping {len(running)} running backtests")
    for bt_id in running:
        stop_backtest(bt_id)

if __name__ == "__main__":
    main()