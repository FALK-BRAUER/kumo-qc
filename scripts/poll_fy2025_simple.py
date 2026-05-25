#!/usr/bin/env python3
import os
import json
import subprocess

USER_ID = os.environ.get('QC_USER_ID')
API_TOKEN = os.environ.get('QC_API_TOKEN')

if not USER_ID or not API_TOKEN:
    raise ValueError('QC credentials missing')

backtest_id = "0a064ccbb4395cc2fea647b909a46899"
url = f"https://www.quantconnect.com/api/v2/backtests/{backtest_id}"
cmd = [
    "curl",
    "-s",
    "-H", f"Authorization: Bearer {API_TOKEN}",
    url
]

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode == 0:
    data = json.loads(result.stdout)
    print(f"FY2025 Status:")
    print(f"  Name: {data.get('name', 'N/A')}")
    print(f"  Progress: {data.get('progress', 'N/A')}%")
    print(f"  Sharpe: {data.get('statistics', {}).get('Sharpe Ratio', 'N/A')}")
    print(f"  Completed: {data.get('completed', False)}")
else:
    print(f"Error polling FY2025: {result.stderr}")