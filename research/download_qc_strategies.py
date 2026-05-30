#!/usr/bin/env python3
"""
Download Python source files from top-100 QC community strategies.
Uses QC API with proper authentication (User ID + API Token).
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

# QC API credentials from keychain
QC_USER_ID = "499707"
QC_API_TOKEN = "f587ef18bc5084436eb4f992da00282cd5807991422c3c1485d7b1035fa7b477"

COMMUNITY_DIR = Path("qc/community")
OUTPUT_DIR = Path("research/qc_community_python")

def generate_api_hash():
    """Generate QC API authentication hash (timestamp + token SHA256)."""
    timestamp = str(int(time.time()))
    hash_input = QC_API_TOKEN + ":" + timestamp
    hash_output = hashlib.sha256(hash_input.encode()).hexdigest()
    return timestamp, hash_output

def get_project_files(project_id: int, name: str) -> list[dict]:
    """Fetch project files from QC API with proper authentication."""
    timestamp, api_hash = generate_api_hash()
    
    url = f"https://www.quantconnect.com/api/v2/projects/{project_id}/files"
    
    cmd = [
        "curl", "-s", "-L",
        "-H", f"Authorization: Basic {QC_USER_ID}:{api_hash}",
        "-H", f"Timestamp: {timestamp}",
        "-H", "Accept: application/json",
        "-H", "Content-Type: application/json",
        url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  Error: curl failed for {name} (ID: {project_id})")
            print(f"  stderr: {result.stderr[:200]}")
            return []
        
        data = json.loads(result.stdout)
        
        if "errors" in data:
            print(f"  API Error for {name}: {data.get('errors', ['Unknown'])[0][:100]}")
            return []
        
        if "files" in data:
            return data["files"]
        elif isinstance(data, list):
            return data
        else:
            print(f"  Unexpected response for {name}: {list(data.keys())[:5]}")
            return []
    except json.JSONDecodeError as e:
        print(f"  JSON parse error for {name}: {e}")
        print(f"  Response preview: {result.stdout[:200]}")
        return []
    except Exception as e:
        print(f"  Error fetching {name}: {e}")
        return []

def save_python_files(project_id: int, name: str, files: list[dict]) -> int:
    """Save Python files from project to output directory."""
    count = 0
    safe_name = name.replace(" ", "_").replace("/", "_")[:50]
    
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
            
        filename = file_info.get("name", "")
        content = file_info.get("content", "")
        
        if not filename or not content:
            continue
        
        # Only save Python files
        if filename.endswith(".py"):
            output_file = OUTPUT_DIR / f"{project_id:08d}_{safe_name}_{filename}"
            try:
                with open(output_file, "w") as f:
                    f.write(content)
                count += 1
                print(f"    Saved: {filename} ({len(content)} chars)")
            except Exception as e:
                print(f"    Error saving {filename}: {e}")
    
    return count

def main():
    print("QC Community Strategy Python Source Downloader (API Auth)")
    print("=" * 60)
    
    # Check community directory
    if not COMMUNITY_DIR.exists():
        print(f"ERROR: Community directory not found: {COMMUNITY_DIR}")
        sys.exit(1)
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR}")
    
    # Get all JSON files
    json_files = sorted(COMMUNITY_DIR.glob("*.json"))
    print(f"\nFound {len(json_files)} strategy metadata files")
    print("-" * 60)
    
    total_files = 0
    successful_projects = 0
    failed_projects = 0
    
    for i, json_file in enumerate(json_files, 1):
        try:
            with open(json_file) as f:
                data = json.load(f)
            
            summary = data.get("summary", {})
            project_id = summary.get("clone_project_id")
            name = summary.get("name", "Unknown")
            language = summary.get("language", "")
            rank = summary.get("rank", i)
            
            print(f"\n[{i}/100] Rank #{rank}: {name}")
            print(f"  Project ID: {project_id}, Language: {language}")
            
            if not project_id:
                print(f"  SKIPPED: No project ID")
                failed_projects += 1
                continue
            
            if language != "Python":
                print(f"  SKIPPED: Not Python ({language})")
                continue
            
            # Fetch files with API auth
            files = get_project_files(project_id, name)
            
            if not files:
                print(f"  No files found or error occurred")
                failed_projects += 1
                continue
            
            # Save Python files
            py_count = save_python_files(project_id, name, files)
            total_files += py_count
            
            if py_count > 0:
                successful_projects += 1
                print(f"  ✓ Downloaded {py_count} Python files")
            else:
                print(f"  No Python files in project")
                failed_projects += 1
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ERROR processing {json_file.name}: {e}")
            failed_projects += 1
            continue
    
    # Summary
    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"Total strategies processed: {len(json_files)}")
    print(f"Successful projects: {successful_projects}")
    print(f"Failed/Skipped: {failed_projects}")
    print(f"Total Python files downloaded: {total_files}")
    print(f"Output directory: {OUTPUT_DIR}")
    
    # List downloaded files
    downloaded = list(OUTPUT_DIR.glob("*.py"))
    print(f"\nDownloaded files: {len(downloaded)}")
    
    return total_files

if __name__ == "__main__":
    count = main()
    sys.exit(0 if count > 0 else 1)
