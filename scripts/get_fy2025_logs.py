#!/usr/bin/env python3
import json, hashlib, time, base64, subprocess
import urllib.request

USER_ID = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-user-id', '-w']).decode().strip()
API_TOKEN = subprocess.check_output(['security', 'find-generic-password', '-s', 'qc-api-token', '-w']).decode().strip()

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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def main():
    # Get FY2025 orders
    fy2025_id = "0a064ccbb4395cc2fea647b909a46899"
    orders = qc_post('/backtests/orders', {'projectId': 32034565, 'backtestId': fy2025_id})
    print(f"FY2025 Orders count: {len(orders.get('orders', []))}")
    
    # Get W4 orders (51d12fd61053e818ae3a0c53a5257512)
    w4_id = "51d12fd61053e818ae3a0c53a5257512"
    orders = qc_post('/backtests/orders', {'projectId': 32034565, 'backtestId': w4_id})
    print(f"W4 Orders count: {len(orders.get('orders', []))}")
    
    # Get W5 orders (from peer table)
    w5_id = "2fb6c98b3293108e..."  # need ID
    # orders = qc_post('/backtests/orders', {'projectId': 32034565, 'backtestId': w5_id})
    # print(f"W5 Orders count: {len(orders.get('orders', []))}")

if __name__ == "__main__":
    main()