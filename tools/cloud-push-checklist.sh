#!/bin/bash
# cloud-push-checklist.sh — Pre-push validation for QC cloud deployments
# Prevents ObjectStore regression and verifies gate configuration.
# Run before: lean cloud push algorithm/performance_bct
#
# Reads: QC credentials from macOS keychain
# Checks: algorithm/performance_bct/config.json for regime_gate_enabled=true
# Checks: ObjectStore for polygon_universe_equity200_fy2025.json
# Uploads: Missing ObjectStore key from local file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CONFIG_PATH="${REPO_ROOT}/algorithm/performance_bct/config.json"
UNIVERSE_FILE="${REPO_ROOT}/algorithm/performance_bct/polygon_universe_equity200_fy2025.json"
ORG_ID="8167a04384265855060312cc22fdbdc6"

# ── 1. QC credentials from keychain ─────────────────────────────────────────
echo "[1/5] Reading QC credentials from keychain..."
QC_USER=$(security find-generic-password -s "qc-user-id" -a "kumo-qc" -w 2>/dev/null || true)
QC_TOKEN=$(security find-generic-password -s "qc-api-token" -a "kumo-qc" -w 2>/dev/null || true)

if [[ -z "$QC_USER" || -z "$QC_TOKEN" ]]; then
    echo "FAIL: QC credentials not found in keychain (qc-user-id / qc-api-token)"
    exit 1
fi
echo "      OK — credentials retrieved"

# ── 2. config.json regime gate check ──────────────────────────────────────
echo "[2/5] Checking config.json for regime_gate_enabled=true..."
if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "FAIL: config.json not found at $CONFIG_PATH"
    exit 1
fi

REGIME_GATE=$(python3 -c "
import json, sys
with open('$CONFIG_PATH') as f:
    cfg = json.load(f)
params = cfg.get('parameters', {})
val = params.get('regime_gate_enabled', '').lower()
sys.stdout.write(val)
")

if [[ "$REGIME_GATE" != "true" ]]; then
    echo "FAIL: regime_gate_enabled is '$REGIME_GATE' (expected 'true')"
    exit 1
fi
echo "      OK — regime_gate_enabled=true"

# Read project ID from config.json
PROJECT_ID=$(python3 -c "
import json
with open('$CONFIG_PATH') as f:
    cfg = json.load(f)
print(cfg.get('cloud-id', cfg.get('project-id', '')))
")

if [[ -z "$PROJECT_ID" ]]; then
    echo "FAIL: No cloud-id or project-id in config.json"
    exit 1
fi
echo "      Project ID: $PROJECT_ID"

# ── 3. ObjectStore key check ──────────────────────────────────────────────
echo "[3/5] Checking ObjectStore for polygon_universe_equity200_fy2025.json..."

KEY_FOUND=$(python3 -c "
import base64, hashlib, json, sys, time, urllib.request

user_id = '$QC_USER'
api_token = '$QC_TOKEN'
org_id = '$ORG_ID'
project_id = '$PROJECT_ID'
ts = str(int(time.time()))
h = hashlib.sha256(f'{api_token}:{ts}'.encode()).hexdigest()
creds = base64.b64encode(f'{user_id}:{h}'.encode()).decode()

req = urllib.request.Request(
    'https://www.quantconnect.com/api/v2/object/list',
    data=json.dumps({'organizationId': org_id, 'projectId': project_id}).encode(),
    headers={
        'Authorization': f'Basic {creds}',
        'Timestamp': ts,
        'Content-Type': 'application/json',
    },
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get('success'):
        print(f'API_ERROR: {result.get(\"errors\")}', file=sys.stderr)
        sys.exit(1)
    keys = [obj['key'] for obj in result.get('objects', [])]
    target = 'polygon_universe_equity200_fy2025.json'
    if target in keys:
        sys.stdout.write('yes')
    else:
        sys.stdout.write('no')
except Exception as e:
    print(f'API_ERROR: {e}', file=sys.stderr)
    sys.exit(1)
")

if [[ "$KEY_FOUND" == "yes" ]]; then
    echo "      OK — ObjectStore key present"
else
    echo "      MISSING — will upload from local file"
fi

# ── 4. Upload if missing ──────────────────────────────────────────────────
if [[ "$KEY_FOUND" != "yes" ]]; then
    echo "[4/5] Uploading polygon_universe_equity200_fy2025.json to ObjectStore..."
    if [[ ! -f "$UNIVERSE_FILE" ]]; then
        echo "FAIL: Local universe file not found at $UNIVERSE_FILE"
        exit 1
    fi

    python3 -c "
import base64, hashlib, io, json, sys, time, urllib.request

user_id = '$QC_USER'
api_token = '$QC_TOKEN'
org_id = '$ORG_ID'
project_id = '$PROJECT_ID'
ts = str(int(time.time()))
h = hashlib.sha256(f'{api_token}:{ts}'.encode()).hexdigest()
creds = base64.b64encode(f'{user_id}:{h}'.encode()).decode()

boundary = '----WebKitFormBoundary' + hashlib.md5(str(time.time()).encode()).hexdigest()[:16]
body = io.BytesIO()

# fields
fields = {
    'organizationId': org_id,
    'projectId': project_id,
    'key': 'polygon_universe_equity200_fy2025.json',
}
for name, value in fields.items():
    body.write(f'--{boundary}\r\n'.encode())
    body.write(f'Content-Disposition: form-data; name=\"{name}\"\r\n\r\n'.encode())
    body.write(f'{value}\r\n'.encode())

# file
filename = 'polygon_universe_equity200_fy2025.json'
file_data = open('$UNIVERSE_FILE', 'rb').read()
body.write(f'--{boundary}\r\n'.encode())
body.write(f'Content-Disposition: form-data; name=\"objectData\"; filename=\"{filename}\"\r\n'.encode())
body.write(b'Content-Type: application/octet-stream\r\n\r\n')
body.write(file_data)
body.write(b'\r\n')
body.write(f'--{boundary}--\r\n'.encode())

req = urllib.request.Request(
    'https://www.quantconnect.com/api/v2/object/set',
    data=body.getvalue(),
    headers={
        'Authorization': f'Basic {creds}',
        'Timestamp': ts,
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    },
    method='POST',
)
with urllib.request.urlopen(req, timeout=120) as resp:
    result = json.loads(resp.read())

if not result.get('success'):
    print(f'FAIL: Upload error: {result.get(\"errors\")}', file=sys.stderr)
    sys.exit(1)
print('      OK — uploaded successfully')
"
else
    echo "[4/5] Skipped — ObjectStore key already present"
fi

# ── 5. Final status ───────────────────────────────────────────────────────
echo "[5/5] PRE-PUSH CHECKLIST PASSED"
echo ""
echo "Ready to push. Run:"
echo "  DOCKER_HOST=unix:///Users/falk/.docker/run/docker.sock lean cloud push algorithm/performance_bct"
echo ""
exit 0
