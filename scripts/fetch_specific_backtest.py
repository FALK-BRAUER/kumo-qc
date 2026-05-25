#!/usr/bin/env python3
"""
Fetch specific backtest ID via QC API.
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
    
    # Try fetching specific backtest ID mentioned by peer
    backtest_id = "81b25c9bce5d2860a222dbce0209b396"
    
    print(f"Fetching backtest {backtest_id}...")
    
    # Need to find which project it belongs to first
    projects = qc_post("/projects/read", {}, user_id, api_token)
    if projects.get("success"):
        for project in projects.get("projects", []):
            project_id = project.get("projectId")
            backtests = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
            if backtests.get("success"):
                for bt in backtests.get("backtests", []):
                    if bt.get("backtestId") == backtest_id:
                        print(f"Found backtest in project {project_id}")
                        print(json.dumps(bt, indent=2))
                        return
        print(f"Backtest {backtest_id} not found in any project")
    else:
        print(f"Error listing projects: {projects.get('errors', ['unknown'])}")

if __name__ == "__main__":
    main()