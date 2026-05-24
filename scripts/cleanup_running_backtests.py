#!/usr/bin/env python3
"""
Check ALL QC projects for any running backtests.
Cancel "InProgress" or "In Progress..." backtests.
Delete completed/stuck backtests if needed.
Verify capacity is freed.

Usage:
  python3 scripts/cleanup_running_backtests.py --list      # Only list running backtests
  python3 scripts/cleanup_running_backtests.py --stop      # Stop running backtests
  python3 scripts/cleanup_running_backtests.py --delete     # Delete completed/stuck backtests
  python3 scripts/cleanup_running_backtests.py --all        # Stop + Delete all
"""

import os
import json
import sys
import base64
import hashlib
import time
import subprocess
import urllib.request
from datetime import datetime

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

def list_projects(user_id, api_token):
    """List all QC projects."""
    response = qc_post("/projects/read", {}, user_id, api_token)
    if not response.get("success"):
        print(f"Error listing projects: {response.get('errors', ['unknown'])}")
        return []
    return response.get("projects", [])

def list_backtests(user_id, api_token, project_id):
    """List backtests for a given project."""
    response = qc_post("/backtests/read", {"projectId": project_id}, user_id, api_token)
    if not response.get("success"):
        print(f"Error listing backtests for project {project_id}: {response.get('errors', ['unknown'])}")
        return []
    return response.get("backtests", [])

def stop_backtest(user_id, api_token, project_id, backtest_id):
    """Stop a running backtest using /backtests/stop endpoint."""
    response = qc_post("/backtests/stop", {"projectId": project_id, "backtestId": backtest_id}, user_id, api_token)
    return response

def delete_backtest(user_id, api_token, project_id, backtest_id):
    """Delete a backtest using /backtests/delete endpoint."""
    response = qc_post("/backtests/delete", {"projectId": project_id, "backtestId": backtest_id}, user_id, api_token)
    return response

def classify_backtest_status(backtest):
    """Classify backtest status based on completed flag and name."""
    name = backtest.get("name", "")
    completed = backtest.get("completed", False)
    progress = backtest.get("progress", 0)
    
    # Check for "In Progress..." or "InProgress" in name
    if "In Progress" in name or "InProgress" in name:
        return "running"
    # Check if completed flag is False (still running)
    elif not completed:
        return "running"
    # Completed but possibly stuck (progress < 1.0 but completed=True)
    elif completed and progress < 1.0:
        return "stuck"
    # Completed normally
    else:
        return "completed"

def main():
    print("QC Backtest Cleanup Script")
    print("=============================")
    
    # Get credentials
    user_id = get_cred("qc-user-id", "kumo-qc")
    api_token = get_cred("qc-api-token", "kumo-qc")
    
    if not user_id or not api_token:
        print("Error: Could not fetch QC credentials from keychain.")
        sys.exit(1)
    
    print(f"User ID: {user_id}")
    
    # Parse command line arguments
    do_list = "--list" in sys.argv
    do_stop = "--stop" in sys.argv
    do_delete = "--delete" in sys.argv
    do_all = "--all" in sys.argv
    
    if not any([do_list, do_stop, do_delete, do_all]):
        print("No action specified. Use one of: --list, --stop, --delete, --all")
        print("Defaulting to --list (show running backtests)")
        do_list = True
    
    # List all projects
    projects = list_projects(user_id, api_token)
    print(f"\nFound {len(projects)} projects")
    
    running_backtests = []
    stuck_backtests = []
    completed_backtests = []
    
    # Scan all projects
    for project in projects:
        project_id = project.get("projectId")
        project_name = project.get("name", "")
        
        print(f"\nProject {project_id}: {project_name}")
        
        backtests = list_backtests(user_id, api_token, project_id)
        print(f"  Found {len(backtests)} backtests")
        
        for bt in backtests:
            bt_id = bt.get("backtestId")
            bt_name = bt.get("name", "")
            completed = bt.get("completed", False)
            progress = bt.get("progress", 0)
            
            status = classify_backtest_status(bt)
            
            if status == "running":
                running_backtests.append({
                    "project_id": project_id,
                    "project_name": project_name,
                    "backtest_id": bt_id,
                    "backtest_name": bt_name,
                    "completed": completed,
                    "progress": progress
                })
                print(f"    ✋ RUNNING: {bt_name} (ID: {bt_id}, Progress: {progress:.1f})")
            
            elif status == "stuck":
                stuck_backtests.append({
                    "project_id": project_id,
                    "project_name": project_name,
                    "backtest_id": bt_id,
                    "backtest_name": bt_name,
                    "completed": completed,
                    "progress": progress
                })
                print(f"    🚨 STUCK: {bt_name} (ID: {bt_id}, Progress: {progress:.1f}, Completed={completed})")
            
            elif status == "completed":
                completed_backtests.append({
                    "project_id": project_id,
                    "project_name": project_name,
                    "backtest_id": bt_id,
                    "backtest_name": bt_name,
                    "completed": completed,
                    "progress": progress
                })
                print(f"    ✓ COMPLETED: {bt_name} (ID: {bt_id})")
    
    print(f"\nSummary:")
    print(f"  Total running backtests: {len(running_backtests)}")
    print(f"  Total stuck backtests: {len(stuck_backtests)}")
    print(f"  Total completed backtests: {len(completed_backtests)}")
    
    # Stop running backtests
    if do_stop or do_all:
        print("\nStopping running backtests...")
        for bt in running_backtests:
            print(f"  Stopping: {bt['backtest_name']} (Project: {bt['project_name']}, ID: {bt['backtest_id']})")
            result = stop_backtest(user_id, api_token, bt['project_id'], bt['backtest_id'])
            if result.get("success"):
                print(f"    ✓ Successfully stopped")
            else:
                print(f"    ✗ Error: {result.get('errors', ['unknown'])}")
    
    # Delete stuck/completed backtests
    if do_delete or do_all:
        print("\nDeleting stuck/completed backtests...")
        backtests_to_delete = stuck_backtests + completed_backtests
        
        for bt in backtests_to_delete:
            print(f"  Deleting: {bt['backtest_name']} (Project: {bt['project_name']}, ID: {bt['backtest_id']})")
            result = delete_backtest(user_id, api_token, bt['project_id'], bt['backtest_id'])
            if result.get("success"):
                print(f"    ✓ Successfully deleted")
            else:
                print(f"    ✗ Error: {result.get('errors', ['unknown'])}")
    
    # Verify capacity is freed (re-scan after cleanup)
    if do_stop or do_delete or do_all:
        print("\nVerifying cleanup...")
        
        remaining_running = []
        remaining_stuck = []
        
        # Re-scan all projects
        for project in projects:
            project_id = project.get("projectId")
            project_name = project.get("name", "")
            
            backtests = list_backtests(user_id, api_token, project_id)
            
            for bt in backtests:
                bt_id = bt.get("backtestId")
                bt_name = bt.get("name", "")
                completed = bt.get("completed", False)
                progress = bt.get("progress", 0)
                
                status = classify_backtest_status(bt)
                
                if status == "running":
                    remaining_running.append({
                        "project_id": project_id,
                        "project_name": project_name,
                        "backtest_id": bt_id,
                        "backtest_name": bt_name,
                        "completed": completed,
                        "progress": progress
                    })
                
                elif status == "stuck":
                    remaining_stuck.append({
                        "project_id": project_id,
                        "project_name": project_name,
                        "backtest_id": bt_id,
                        "backtest_name": bt_name,
                        "completed": completed,
                        "progress": progress
                    })
        
        print(f"  Remaining running backtests: {len(remaining_running)}")
        print(f"  Remaining stuck backtests: {len(remaining_stuck)}")
        
        if len(remaining_running) == 0 and len(remaining_stuck) == 0:
            print("  ✅ All backtests cleaned up!")
        else:
            print("  ⚠️ Some backtests remain:")
            for bt in remaining_running:
                print(f"    ✋ RUNNING: {bt['backtest_name']}")
            for bt in remaining_stuck:
                print(f"    🚨 STUCK: {bt['backtest_name']}")
    
    print("\nDone.")

if __name__ == "__main__":
    main()