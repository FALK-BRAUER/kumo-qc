#!/usr/bin/env python3
"""Upload polygon universe JSON to QC as a project file for cloud BT."""

import argparse
import json
import hashlib
import base64
import time
import subprocess
import urllib.request
from pathlib import Path


def qc_api_call(path: str, body: dict, user_id: str, api_token: str) -> dict:
    """Make authenticated QC API call."""
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{api_token}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{user_id}:{h}".encode()).decode()
    data = json.dumps(body).encode()
    
    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}",
        data=data,
        headers={
            'Authorization': f'Basic {creds}',
            'Timestamp': ts,
            'Content-Type': 'application/json'
        },
        method='POST'
    )
    
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def upload_universe_file(json_path: str, project_id: str, user_id: str, api_token: str):
    """Upload universe JSON as a project file (cloud equivalent of local file)."""
    with open(json_path) as f:
        data = json.load(f)
    
    # Extract all unique tickers
    tickers = set()
    for date_tickers in data.values():
        tickers.update(date_tickers)
    tickers = sorted(tickers)
    
    print(f"Uploading {len(tickers)} tickers as project file for project {project_id}")
    
    # Create/update a file named 'bctuniverse.json' in the project
    result = qc_api_call(
        '/projects/files/create',
        {
            'projectId': project_id,
            'name': 'bctuniverse.json',
            'content': json.dumps(tickers),
        },
        user_id,
        api_token
    )
    
    print(f"Upload complete: {result.get('success', False)}")
    return tickers, result


def main():
    parser = argparse.ArgumentParser(
        description="Upload polygon universe JSON to QC as project file"
    )
    parser.add_argument(
        "--json-path",
        default="algorithm/performance_bct/polygon_universe_equity200_fy2025.json",
        help="Path to universe JSON file"
    )
    parser.add_argument(
        "--project-id",
        default="32033824",
        help="QC project ID"
    )
    args = parser.parse_args()
    
    # Read API credentials from keychain
    print("Reading QC credentials from keychain...")
    user_id = subprocess.check_output(
        ["security", "find-generic-password", "-s", "qc-user-id", "-w"],
        text=True,
    ).strip()
    
    api_token = subprocess.check_output(
        ["security", "find-generic-password", "-s", "qc-api-token", "-w"],
        text=True,
    ).strip()
    
    # Resolve path
    json_path = Path(args.json_path)
    if not json_path.is_absolute():
        # Assume running from repo root
        repo_root = Path(__file__).parent.parent
        json_path = repo_root / json_path
    
    print(f"Reading universe from: {json_path}")
    if not json_path.exists():
        print(f"ERROR: File not found: {json_path}")
        exit(1)
    
    tickers, result = upload_universe_file(
        str(json_path),
        args.project_id,
        user_id,
        api_token
    )
    
    print(f"Successfully uploaded {len(tickers)} tickers")
    print(f"Tickers sample: {tickers[:5]}...")


if __name__ == "__main__":
    main()
