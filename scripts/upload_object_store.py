#!/usr/bin/env python3
"""Upload LEAN equity data to QC Object Store for project 32099988.

Uses QC API v2: POST /api/v2/object/set with multipart form data.
Resumable: tracks progress in data/upload_progress.json.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Paths
DATA_BASE = Path("/Users/falk/projects/kumo-qc/data/equity/usa")
DAILY_DIR = DATA_BASE / "daily"
MAP_DIR = DATA_BASE / "map_files"
FACTOR_DIR = DATA_BASE / "factor_files"
PROGRESS_FILE = Path("/Users/falk/projects/kumo-qc/data/upload_progress.json")

# QC
ORG_ID = "8167a04384265855060312cc22fdbdc6"
PROJECT_ID = 32099988


def get_cred(service: str, account: str) -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def qc_post_multipart(path: str, fields: dict, files: dict, user_id: str, api_token: str) -> dict:
    """POST multipart form data to QC API."""
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{api_token}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{user_id}:{h}".encode()).decode()

    boundary = "----WebKitFormBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
    body = io.BytesIO()

    for name, value in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f"{value}\r\n".encode())

    for name, (filename, file_data) in files.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(file_data)
        body.write(b"\r\n")

    body.write(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        f"https://www.quantconnect.com/api/v2{path}",
        data=body.getvalue(),
        headers={
            "Authorization": f"Basic {creds}",
            "Timestamp": ts,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def qc_object_set(key: str, data: bytes, user_id: str, api_token: str) -> dict:
    """Upload raw bytes to QC Object Store under key."""
    return qc_post_multipart(
        "/object/set",
        {
            "organizationId": ORG_ID,
            "projectId": str(PROJECT_ID),
            "key": key,
        },
        {"objectData": (key.split("/")[-1], data)},
        user_id,
        api_token,
    )


def qc_object_list(user_id: str, api_token: str) -> list[str]:
    """List all keys in project Object Store."""
    ts = str(int(time.time()))
    h = hashlib.sha256(f"{api_token}:{ts}".encode()).hexdigest()
    creds = base64.b64encode(f"{user_id}:{h}".encode()).decode()
    req = urllib.request.Request(
        "https://www.quantconnect.com/api/v2/object/list",
        data=json.dumps({"organizationId": ORG_ID, "projectId": PROJECT_ID}).encode(),
        headers={
            "Authorization": f"Basic {creds}",
            "Timestamp": ts,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("success"):
        print(f"List error: {result.get('errors')}")
        return []
    return [obj["key"] for obj in result.get("objects", [])]


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(progress: dict) -> None:
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def upload_file(key: str, path: Path, user_id: str, api_token: str) -> bool:
    data = path.read_bytes()
    result = qc_object_set(key, data, user_id, api_token)
    if result.get("success"):
        return True
    print(f"  ERROR uploading {key}: {result.get('errors')}")
    return False


def main() -> None:
    user_id = get_cred("qc-user-id", "kumo-qc")
    api_token = get_cred("qc-api-token", "kumo-qc")
    if not user_id or not api_token:
        print("Missing QC credentials")
        sys.exit(1)

    # Load or init progress
    progress = load_progress()
    done = set(progress.get("uploaded", []))
    errors = progress.get("errors", {})

    # Gather all files to upload
    files_to_upload: list[tuple[str, Path]] = []

    # Daily zips
    for p in sorted(DAILY_DIR.glob("*.zip")):
        key = f"equity/usa/daily/{p.name}"
        if key not in done:
            files_to_upload.append((key, p))

    # Map files
    for p in sorted(MAP_DIR.glob("*.csv")):
        key = f"equity/usa/map_files/{p.name}"
        if key not in done:
            files_to_upload.append((key, p))

    # Factor files
    for p in sorted(FACTOR_DIR.glob("*.csv")):
        key = f"equity/usa/factor_files/{p.name}"
        if key not in done:
            files_to_upload.append((key, p))

    total = len(files_to_upload) + len(done)
    remaining = len(files_to_upload)
    print(f"Total: {total} | Already done: {len(done)} | Remaining: {remaining}")

    if remaining == 0:
        print("All files already uploaded.")
        return

    # Upload loop
    uploaded_this_run = 0
    start = time.time()
    for key, path in files_to_upload:
        if upload_file(key, path, user_id, api_token):
            done.add(key)
            uploaded_this_run += 1
        else:
            errors[key] = errors.get(key, 0) + 1
            if errors[key] >= 3:
                print(f"  SKIPPING {key} after 3 failures")
                done.add(key)

        # Save progress every 10 files
        if uploaded_this_run % 10 == 0:
            progress["uploaded"] = sorted(done)
            progress["errors"] = errors
            save_progress(progress)
            elapsed = time.time() - start
            rate = uploaded_this_run / elapsed * 60 if elapsed > 0 else 0
            print(f"  Progress: {len(done)}/{total} | Rate: {rate:.1f} files/min")

    # Final save
    progress["uploaded"] = sorted(done)
    progress["errors"] = errors
    save_progress(progress)
    elapsed = time.time() - start
    rate = uploaded_this_run / elapsed * 60 if elapsed > 0 else 0
    print(f"DONE: {len(done)}/{total} uploaded | This run: {uploaded_this_run} | Rate: {rate:.1f} files/min")


if __name__ == "__main__":
    main()
