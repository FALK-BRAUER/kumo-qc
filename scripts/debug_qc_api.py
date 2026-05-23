#!/usr/bin/env python3
"""
Debug QC API response shape.
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
    
    print("Testing QC API for backtest stats...")
    
    # Fetch backtests for project 32034565 (performance_bct)
    backtests = qc_post("/backtests/read", {"projectId": 32034565}, user_id, api_token)
    if backtests.get("success"):
        print(f"Found {len(backtests.get('backtests', []))} backtests")
        
        # Look at first backtest's statistics
        if backtests.get("backtests"):
            first = backtests["backtests"][0]
            print("\nBacktest object:")
            print(json.dumps(first, indent=2))
            
            stats = first.get("statistics", {})
            print("\nStatistics keys:")
            for key in stats.keys():
                print(f"  {key}: {stats[key]}")
    else:
        print(f"Error: {backtests.get('errors', ['unknown'])}")

if __name__ == "__main__":
    main()