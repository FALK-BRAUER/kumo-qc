#!/usr/bin/env python3
"""
Cancel W1 backtest ID 1a20f110b4974b69e2b224cca61ae4fe.
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
    
    backtest_id = "1a20f110b4974b69e2b224cca61ae4fe"
    project_id = 32034565
    
    print(f"Canceling backtest {backtest_id} in project {project_id}...")
    
    delete_response = qc_post(
        "/backtests/delete",
        {"projectId": project_id, "backtestId": backtest_id},
        user_id,
        api_token
    )
    print(json.dumps(delete_response, indent=2))

if __name__ == "__main__":
    main()