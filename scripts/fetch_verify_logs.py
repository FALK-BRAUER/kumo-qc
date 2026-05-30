#!/usr/bin/env python3
"""Fetch cloud BT e225154054 (project 32033824) — orders + logs for parity verdict."""
import os, json, base64, hashlib, time, subprocess, urllib.request

BT = "30cf2f13e84437edc7c8fbc344a9a768"
PROJECT = 32033824

def cred(s):
    return subprocess.run(["security","find-generic-password","-s",s,"-a","kumo-qc","-w"],
                          capture_output=True, text=True).stdout.strip()

USER = cred("qc-user-id"); TOKEN = cred("qc-api-token")

def post(path, body):
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{TOKEN}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{USER}:{h}".encode()).decode()
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Basic {creds}", "Timestamp": ts, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

print("=== BT READ ===")
bt = post("/backtests/read", {"projectId": PROJECT, "backtestId": BT})
if not bt.get("success"):
    print("ERR read:", bt.get("errors"));
else:
    b = bt.get("backtest", bt.get("backtests", [{}]))
    b = b[0] if isinstance(b, list) and b else b
    stats = b.get("statistics", {}) if isinstance(b, dict) else {}
    print("name:", b.get("name") if isinstance(b,dict) else "?")
    print("totalOrders:", (b.get("runtimeStatistics",{}) or {}).get("Total Orders") if isinstance(b,dict) else "?")
    for k in ("Sharpe Ratio","Net Profit","Total Trades","Total Orders"):
        if k in stats: print(f"  {k}: {stats[k]}")

print("\n=== ORDERS ===")
orders = post("/backtests/orders/read", {"projectId": PROJECT, "backtestId": BT, "start": 0, "end": 100})
if orders.get("success"):
    ol = orders.get("orders", [])
    print(f"order count: {len(ol)}")
    for o in ol:
        sym = (o.get("symbol",{}) or {}).get("value", o.get("symbol"))
        print(f"  {o.get('time','?')} {sym} qty={o.get('quantity')} fill={o.get('price')} status={o.get('status')} type={o.get('type')}")
else:
    print("ERR orders:", orders.get("errors"))

print("\n=== LOGS (grep GOOG/GOOGL/2025-02-05) ===")
logs = post("/backtests/read/logs", {"projectId": PROJECT, "backtestId": BT, "start": 0, "end": 20000})
if logs.get("success"):
    text = "\n".join(logs.get("logs", [])) if isinstance(logs.get("logs"), list) else str(logs.get("logs",""))
    hits = [ln for ln in text.splitlines() if ("GOOG" in ln or "02-05" in ln or "STOP" in ln or "kijun" in ln.lower())]
    print(f"total log lines: {len(text.splitlines())}, matched: {len(hits)}")
    for ln in hits[:60]:
        print("  ", ln)
else:
    print("ERR logs:", logs.get("errors"))
