"""
Live trading gate. Writes UNLOCKED/LOCKED to macOS keychain.
Usage:
  python3 scripts/gate.py unlock   — enables live trading
  python3 scripts/gate.py lock     — disables live trading
  python3 scripts/gate.py status   — prints current gate state
"""

import subprocess
import sys

SERVICE = "kumo-qc"
ACCOUNT = "qc-live-gate"


def _read() -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "LOCKED"


def _write(value: str):
    # Delete existing entry if present
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
        capture_output=True,
    )
    subprocess.run(
        ["security", "add-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w", value],
        check=True,
    )


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "unlock":
        _write("UNLOCKED")
        print("Gate UNLOCKED — paper live trading enabled")
        print("WARNING: Verify account ID is DUK434934 (paper) before deploying")
    elif cmd == "lock":
        _write("LOCKED")
        print("Gate LOCKED")
    elif cmd == "status":
        state = _read()
        print(f"Gate: {state}")
    else:
        print(f"Usage: gate.py unlock|lock|status")
        sys.exit(1)


if __name__ == "__main__":
    main()
