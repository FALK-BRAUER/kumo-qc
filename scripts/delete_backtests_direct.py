#!/usr/bin/env python3
"""
Delete all backtests to free capacity.
"""
import json, hashlib, time, base64, subprocess, sys
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-a', 'kumo-qc', '-w']).decode().strip()
PROJECT_ID = 32034565

def qc_post(path, body):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{API_TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER_ID}:{h}".encode()).decode()
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}", data=data,
        headers={'Authorization': f'Basic {creds}', 'Timestamp': ts, 'Content-Type': 'application/json'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def delete_all_backtests():
    """Delete all backtests."""
    r = qc_post('/backtests/read', {'projectId': PROJECT_ID})
    if not r.get('success'):
        print(f"Failed to get backtests: {r}")
        return
    
    bt_list = r.get('backtests', [])
    print(f"Found {len(bt_list)} backtests")
    
    for bt in bt_list:
        bt_id = bt.get('backtestId')
        name = bt.get('name')
        status = bt.get('status')
        progress = bt.get('progress')
        if bt_id:
            print(f"Deleting {name} ({bt_id[:16]}...) status={status}, progress={progress}")
            try:
                result = qc_post('/backtests/delete', {'projectId': PROJECT_ID, 'backtestId': bt_id})
                if result.get('success'):
                    print(f"  ✓ Deleted")
                else:
                    print(f"  ✗ Failed: {result}")
            except Exception as e:
                print(f"  ✗ Error: {e}")

if __name__ == "__main__":
    delete_all_backtests()