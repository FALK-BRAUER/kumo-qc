#!/usr/bin/env python3
"""
List all backtests for project 32034565 with status.
"""
import json, hashlib, time, base64, sys
import urllib.request
import subprocess

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()
PROJECT_ID = 32034565


def qc_request(method, path, body=None):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
    if body:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"https://www.quantconnect.com/api/v2{path}",
            data=data,
            headers={
                'Authorization': f'Basic {creds}',
                'Timestamp': ts,
                'Content-Type': 'application/json'
            },
            method=method
        )
    else:
        req = urllib.request.Request(
            f"https://www.quantconnect.com/api/v2{path}",
            headers={'Authorization': f'Basic {creds}', 'Timestamp': ts},
            method=method
        )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"Request error: {e}")
        return {'errors': [str(e)], 'success': False}


def list_backtests():
    """Get all backtests for the project."""
    r = qc_request('POST', '/backtests/read', {'projectId': PROJECT_ID})
    if not r.get('success'):
        print(f"List failed: {r}")
        return []
    backtests = r.get('backtests', [])
    return backtests


def main():
    backtests = list_backtests()
    if not backtests:
        print("No backtests found")
        return
    print(f"Found {len(backtests)} backtests")
    for bt in backtests:
        print(f"{bt.get('name')} ({bt.get('backtestId')}): status={bt.get('status')}, progress={bt.get('progress')}")

if __name__ == "__main__":
    main()