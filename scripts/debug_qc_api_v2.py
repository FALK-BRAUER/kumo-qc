#!/usr/bin/env python3
"""
Debug QC API response shape — more comprehensive.
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
    
    print("Testing QC API for all backtests...")
    
    # Fetch all projects
    projects = qc_post("/projects/read", {}, user_id, api_token)
    if projects.get("success"):
        print(f"Found {len(projects.get('projects', []))} projects")
        
        for project in projects.get("projects", []):
            project_id = project.get("projectId")
            project_name = project.get("name", "")
            print(f"\nProject {project_id}: {project_name}")
            
            backtests = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
            if backtests.get("success"):
                for bt in backtests.get("backtests", []):
                    print(f"\nBacktest: {bt.get('name')}")
                    print(f"  Completed: {bt.get('completed')}")
                    print(f"  SharpeRatio: {bt.get('sharpeRatio')}")
                    print(f"  CompoundingAnnualReturn: {bt.get('compoundingAnnualReturn')}")
                    print(f"  Drawdown: {bt.get('drawdown')}")
                    print(f"  NetProfit: {bt.get('netProfit')}")
                    print(f"  LossRate: {bt.get('lossRate')}")
                    print(f"  WinRate: {bt.get('winRate')}")
                    print(f"  Trades: {bt.get('trades')}")
                    
                    # Print all fields for reference
                    print("  All fields:")
                    for key in bt.keys():
                        print(f"    {key}: {bt[key]}")
            else:
                print(f"Error fetching backtests: {backtests.get('errors', ['unknown'])}")
    else:
        print(f"Error listing projects: {projects.get('errors', ['unknown'])}")

if __name__ == "__main__":
    main()