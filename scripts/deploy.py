"""
Deploy live_bct to QC cloud. Reads gate from keychain before proceeding.
Usage:
  python3 scripts/deploy.py          — deploys to paper (DUK434934)
  python3 scripts/deploy.py --dry    — prints commands without running
"""

import subprocess
import sys


SERVICE = "kumo-qc"
ACCOUNT = "qc-live-gate"


def _gate_status() -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else "LOCKED"


def _run(cmd: list[str], dry: bool):
    print(f"  $ {' '.join(cmd)}")
    if not dry:
        subprocess.run(cmd, check=True)


def main():
    dry = "--dry" in sys.argv

    gate = _gate_status()
    if gate != "UNLOCKED":
        print(f"ERROR: Gate is {gate}. Run 'python3 scripts/gate.py unlock' first.")
        sys.exit(1)

    print(f"Gate: UNLOCKED. Deploying live_bct to QC...")
    if dry:
        print("(dry run — no commands executed)")

    _run(["lean", "cloud", "push", "live_bct"], dry)
    _run(["lean", "cloud", "live", "live_bct", "--brokerage", "Interactive Brokers Brokerage",
          "--ib-account", "DUK434934", "--parameter", "live-gate", "UNLOCKED"], dry)

    if not dry:
        print("Deployed. Monitor at https://www.quantconnect.com/terminal/")


if __name__ == "__main__":
    main()
