#!/usr/bin/env python3
"""Record backtest result to kumo-qc.db SQLite store."""

import json
import sys
import os
import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Path to the SQLite database
DB_PATH = Path(__file__).parent.parent / "data" / "kumo-qc.db"


def get_db_connection() -> sqlite3.Connection:
    """Get SQLite database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database schema if not exists."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bt_runs (
        bt_id TEXT PRIMARY KEY,
        submitted_at TEXT,
        commit_sha TEXT,
        window TEXT,
        warmup_days INTEGER,
        parameters TEXT,
        status TEXT,
        net_profit REAL,
        sharpe REAL,
        trades INTEGER,
        win_rate REAL,
        notes TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_window_commit ON bt_runs(window, commit_sha)
    ''')
    
    conn.commit()
    conn.close()


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
    """Record a backtest result to the SQLite store."""
    
    init_db()
    
    record = {
        "bt_id": bt_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": get_git_commit_sha(),
        "window": window,
        "warmup_days": warmup_days,
        "parameters": json.dumps(parameters) if parameters else "{}",
        "status": status,
        "net_profit": net_profit,
        "sharpe": sharpe,
        "trades": trades,
        "win_rate": win_rate,
        "notes": notes,
    }
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR REPLACE INTO bt_runs 
    (bt_id, submitted_at, commit_sha, window, warmup_days, parameters, status, 
     net_profit, sharpe, trades, win_rate, notes)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        record["bt_id"],
        record["submitted_at"],
        record["commit_sha"],
        record["window"],
        record["warmup_days"],
        record["parameters"],
        record["status"],
        record["net_profit"],
        record["sharpe"],
        record["trades"],
        record["win_rate"],
        record["notes"],
    ))
    
    conn.commit()
    conn.close()
    
    return record


def check_existing_result(window: str, commit_sha: str | None = None) -> dict[str, Any] | None:
    """Check if a completed result exists for the given window and commit."""
    if commit_sha is None:
        commit_sha = get_git_commit_sha()
    
    init_db()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT * FROM bt_runs 
    WHERE window = ? AND commit_sha = ? AND status = 'completed'
    LIMIT 1
    ''', (window, commit_sha))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def get_all_results(window: str | None = None, commit_sha: str | None = None) -> list[dict[str, Any]]:
    """Get all results, optionally filtered by window and/or commit."""
    init_db()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM bt_runs WHERE 1=1"
    params = []
    
    if window:
        query += " AND window = ?"
        params.append(window)
    
    if commit_sha:
        query += " AND commit_sha = ?"
        params.append(commit_sha)
    
    query += " ORDER BY submitted_at DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def main():
    """CLI entry point for recording backtest results."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Record backtest result to SQLite store")
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
    parser.add_argument("--list", action="store_true", help="List all results for window")
    
    args = parser.parse_args()
    
    if args.list:
        # List mode: show all results for window
        results = get_all_results(window=args.window)
        if results:
            print(f"Found {len(results)} result(s) for {args.window}:")
            for r in results:
                status_icon = "✓" if r["status"] == "completed" else "✗"
                print(f"  [{status_icon}] {r['bt_id'][:12]}... ({r['commit_sha'][:8]}) "
                      f"Sharpe: {r['sharpe']:.2f}, Trades: {r['trades']}")
        else:
            print(f"No results found for {args.window}")
        sys.exit(0)
    
    elif args.check:
        # Check mode: verify if result exists
        existing = check_existing_result(args.window)
        if existing:
            print(f"EXISTS: {existing['bt_id']} (Sharpe: {existing['sharpe']:.2f}, Trades: {existing['trades']})")
            sys.exit(0)
        else:
            print("NOT_FOUND")
            sys.exit(1)
    
    else:
        # Record mode: insert/update row in database
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
        print(f"  Sharpe: {record['sharpe']:.2f}, Trades: {record['trades']}, Status: {record['status']}")


if __name__ == "__main__":
    main()
