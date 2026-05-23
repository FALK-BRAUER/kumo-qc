#!/usr/bin/env python3
"""
Fetch all files from a QC project via API.
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

def fetch_project_files(user_id, api_token, project_id):
    """Fetch all files from QC project."""
    response = qc_post("/files/read", {"projectId": project_id}, user_id, api_token)
    if not response.get("success"):
        print(f"Error fetching files for project {project_id}: {response.get('errors', ['unknown'])}")
        return []
    return response.get("files", [])

def main():
    # Fetch credentials
    user_id = get_cred("qc-user-id", "kumo-qc")
    api_token = get_cred("qc-api-token", "kumo-qc")
    
    if not user_id or not api_token:
        print("Error: Could not fetch QC credentials from keychain.")
        sys.exit(1)
    
    # Project 32034565 (performance_bct)
    project_id = 32034565
    files = fetch_project_files(user_id, api_token, project_id)
    
    print(f"Found {len(files)} files in project {project_id}")
    
    # Create directory
    target_dir = "/Users/falk/projects/kumo-qc/algorithm/performance_bct"
    os.makedirs(target_dir, exist_ok=True)
    
    # Write each file
    for file in files:
        name = file.get("name", "")
        content = file.get("content", "")
        print(f"  Saving {name}")
        
        # Write file
        with open(os.path.join(target_dir, name), "w") as f:
            f.write(content)
    
    # Create README.md
    readme_content = """# performance_bct QC Project

QuantConnect project ID: 32034565

Contains the full trading algorithm for Blue Cloud Trading (BCT) Ichimoku methodology, including portfolio orders, execution, and risk management.

Unlike `backtest_bct` (32033824), which performs signal audit only (no trades), `performance_bct` implements actual trading logic and portfolio construction.

Files downloaded via QC API `/files/read` endpoint.
"""
    
    with open(os.path.join(target_dir, "README.md"), "w") as f:
        f.write(readme_content)
    
    print(f"Files saved to {target_dir}")

if __name__ == "__main__":
    main()