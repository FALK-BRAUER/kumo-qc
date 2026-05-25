#!/usr/bin/env python3
import os
import json
import subprocess

USER_ID = os.environ.get('QC_USER_ID')
API_TOKEN = os.environ.get('QC_API_TOKEN')

if not USER_ID or not API_TOKEN:
    USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-a', 'kumo-qc', '-w']).decode().strip()
    API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()

# Try to get all backtests
url = "https://www.quantconnect.com/api/v2/projects/32034565/backtests"
cmd = [
    "curl",
    "-s",
    "-H", f"Authorization: Bearer {API_TOKEN}",
    url
]

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("Error fetching backtests")
    exit(1)

data = json.loads(result.stdout)
print(f"Total backtests: {len(data.get('backtests', []))}")
for bt in data.get('backtests', []):
    name = bt.get('name', '')
    if 'FY2025' in name:
        print(f"FY2025 Backtest:")
        print(f"  ID: {bt.get('backtestId')}")
        print(f"  Progress: {bt.get('progress', 0) * 100:.2f}%")
        print(f"  Completed: {bt.get('completed', False)}")
        print(f"  Error: {bt.get('error', '')}")
        stats = bt.get('statistics', {})
        print(f"  Sharpe: {stats.get('Sharpe Ratio', stats.get('SharpeRatio', 'N/A'))}")
        print(f"  Net Profit: {stats.get('Net Profit', stats.get('TotalNetProfit', 'N/A'))}")
        print(f"  Total Orders: {stats.get('Total Orders', stats.get('TotalTrades', 'N/A'))}")