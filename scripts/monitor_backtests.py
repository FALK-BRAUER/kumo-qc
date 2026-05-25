#!/usr/bin/env python3
import os
import json
import sys
import base64
import hashlib
import time
import subprocess
import urllib.request

def get_cred(service, account):
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True
    )
    return r.stdout.strip()

def qc_post(path, body, user_id, api_token):
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

user_id = get_cred("qc-user-id", "kumo-qc")
api_token = get_cred("qc-api-token", "kumo-qc")

# List incomplete backtests
response = qc_post("/backtests/read", {"projectId": 32034565}, user_id, api_token)
if not response.get("success"):
    print(f"Error: {response.get('errors', ['unknown'])}")
    sys.exit(1)

backtests = response.get("backtests", [])
print(f"Incomplete backtests: {len(backtests)}")
for bt in backtests:
    print(f"  {bt.get('backtestId')}: {bt.get('name')} - completed={bt.get('completed')}")

# Known IDs
known_ids = [
    "be3e8b65c6d578d9e287edd0a2dde8ba",
    "3e7eba1118f70470a2ed6973a7861b7a",
    "24b9bc4ecad772cec83c41d07783da15",
    "0a064ccbb4395cc2fea647b909a46899",
    "c58e0e99e0322e6230b51a86e0179b43",
    "b166eed8d02c1581a2676875f7f2e3d2",
    "551a0a0283e161b0381387a0ce80e19a"
]

for bt_id in known_ids:
    response = qc_post("/backtests/read", {"projectId": 32034565, "backtestId": bt_id}, user_id, api_token)
    if not response.get("success"):
        print(f"  {bt_id}: not found")
        continue
    bt = response.get("backtest", {})
    completed = bt.get("completed", False)
    name = bt.get("name", "")
    print(f"  {bt_id} ({name}) - completed={completed}")