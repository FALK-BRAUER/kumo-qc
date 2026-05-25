#!/usr/bin/env python3
"""Record backtest result to cloud_bt_results.json store."""

import json
import sys
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Path to the results store
RESULTS_PATH = Path(__file__).parent.parent / "data" / "cloud_bt_results.json"


def get_git_commit_sha() -> str:
    """Get current git HEAD commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def load_results() -> list[dict[str, Any]]:
    """Load existing results from JSON file."""
    if not RESULTS_PATH.exists():
        return []
    
    try:
        with open(RESULTS_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_results(results: list[dict[str, Any]]) -> None:
    """Save results back to JSON file."""
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)


def record_result(
    bt_id: str,
    window: str,
    warmup_days: int,
    status: str,
    net_profit: float,
    sharpe: float,
    trades: int,
    win_rate: float,
    parameters: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Record a backtest result to the store."""
    
    record = {
        "bt_id": bt_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": get_git_commit_sha(),
        "window": window,
        "warmup_days": warmup_days,
        "parameters": parameters or {},
        "status": status,
        "metrics": {
            "net_profit": net_profit,
            "sharpe": sharpe,
            "trades": trades,
            "win_rate": win_rate,
        },
        "notes": notes,
    }
    
    results = load_results()
    results.append(record)
    save_results(results)
    
    return record


def check_existing_result(window: str, commit_sha: str | None = None) -> dict[str, Any] | None:
    """Check if a completed result exists for the given window and commit."""
    if commit_sha is None:
        commit_sha = get_git_commit_sha()
    
    results = load_results()
    
    for result in results:
        if result.get("window") == window and result.get("commit_sha") == commit_sha:
            if result.get("status") == "completed":
                return result
    
    return None


def main():
    """CLI entry point for recording backtest results."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Record backtest result to store")
    parser.add_argument("--bt-id", required=True, help="Backtest ID")
    parser.add_argument("--window", required=True, help="Window identifier (e.g., W1-2025)")
    parser.add_argument("--warmup-days", type=int, default=750, help="Warmup days parameter")
    parser.add_argument("--status", required=True, choices=["completed", "error", "cancelled"], help="Backtest status")
    parser.add_argument("--net-profit", type=float, default=0.0, help="Net profit")
    parser.add_argument("--sharpe", type=float, default=0.0, help="Sharpe ratio")
    parser.add_argument("--trades", type=int, default=0, help="Number of trades")
    parser.add_argument("--win-rate", type=float, default=0.0, help="Win rate (0-1)")
    parser.add_argument("--parameters", type=str, default="{}", help="JSON string of additional parameters")
    parser.add_argument("--notes", default="", help="Additional notes")
    parser.add_argument("--check", action="store_true", help="Check for existing result instead of recording")
    
    args = parser.parse_args()
    
    if args.check:
        # Check mode: verify if result exists
        existing = check_existing_result(args.window)
        if existing:
            print(f"EXISTS: {existing['bt_id']} (Sharpe: {existing['metrics']['sharpe']}, Trades: {existing['metrics']['trades']})")
            sys.exit(0)
        else:
            print("NOT_FOUND")
            sys.exit(1)
    else:
        # Record mode: append result to store
        params = json.loads(args.parameters) if args.parameters else {}
        
        record = record_result(
            bt_id=args.bt_id,
            window=args.window,
            warmup_days=args.warmup_days,
            status=args.status,
            net_profit=args.net_profit,
            sharpe=args.sharpe,
            trades=args.trades,
            win_rate=args.win_rate,
            parameters=params,
            notes=args.notes,
        )
        
        print(f"RECORDED: {record['bt_id']} @ {record['commit_sha'][:8]} ({record['window']})")
        print(f"  Sharpe: {record['metrics']['sharpe']}, Trades: {record['metrics']['trades']}")


if __name__ == "__main__":
    main()
