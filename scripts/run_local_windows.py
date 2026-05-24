#!/usr/bin/env python3
"""
Parallel W1-W6 local runner script.

Runs all 6 weekly windows simultaneously using Python subprocess + lean CLI.
No data needed — pure scripting.

Usage:
  python3 scripts/run_local_windows.py
  python3 scripts/run_local_windows.py --fy  # FY2025 single backtest

Windows to run:
  W1 (2026-04-07 to 2026-04-11)
  W2 (2026-04-14 to 2026-04-18)
  W3 (2026-04-22 to 2026-04-25)
  W4 (2026-04-28 to 2026-05-02)
  W5 (2026-05-05 to 2026-05-09)
  W6 (2026-05-12 to 2026-05-16)

FY2025 mode runs a single backtest from 2025-01-01 to 2025-12-31.

Output:
  Parallel execution via subprocess.Popen
  Results collected from results/{name}/backtests/*/output/results.json
  Prints consolidated table and writes results/parallel-run-{timestamp}.json
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

WINDOWS = [
    ("W1", "2026-04-07", "2026-04-11"),
    ("W2", "2026-04-14", "2026-04-18"),
    ("W3", "2026-04-22", "2026-04-25"),
    ("W4", "2026-04-28", "2026-05-02"),
    ("W5", "2026-05-05", "2026-05-09"),
    ("W6", "2026-05-12", "2026-05-16"),
]

FY2025_WINDOW = ("FY2025", "2025-01-01", "2025-12-31")

ALGO_PATH = Path("algorithm/performance_bct")


def check_lean_installed():
    """Check if lean CLI is available."""
    try:
        subprocess.run(["lean", "--version"], capture_output=True, timeout=2)
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def run_backtest(name: str, start: str, end: str, output_dir: Path) -> dict:
    """Run single lean backtest for a window."""
    result_dir = output_dir / name
    result_dir.mkdir(parents=True, exist_ok=True)

    # Build lean CLI command with parameters
    cmd = [
        "lean", "backtest", str(ALGO_PATH),
        "--output", str(result_dir),
        "--lean-config", "lean-api.json",
        "--parameter", "start_year", str(start.split("-")[0]),
        "--parameter", "start_month", str(start.split("-")[1]),
        "--parameter", "start_day", str(start.split("-")[2]),
        "--parameter", "end_year", str(end.split("-")[0]),
        "--parameter", "end_month", str(end.split("-")[1]),
        "--parameter", "end_day", str(end.split("-")[2]),
    ]

    print(f"[{name}] Starting: {start} → {end}")
    print(f"[{name}] Command: {cmd}")
    
    try:
        # Run with timeout of 10 minutes
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        stdout_lines = []
        stderr_lines = []
        
        # Poll for completion
        while True:
            line = proc.stdout.readline()
            if line:
                stdout_lines.append(line.strip())
                print(f"[{name}] {line.strip()}")
            
            err_line = proc.stderr.readline()
            if err_line:
                stderr_lines.append(err_line.strip())
                print(f"[{name}] [ERROR] {err_line.strip()}")
            
            status = proc.poll()
            if status is not None:
                break
            
            time.sleep(0.1)
        
        # Collect remaining output
        stdout_remain, stderr_remain = proc.communicate(timeout=5)
        stdout_lines.extend(stdout_remain.splitlines())
        stderr_lines.extend(stderr_remain.splitlines())
        
        # Find results.json
        results_json = find_results_json(result_dir)
        
        result_data = {
            "name": name,
            "start": start,
            "end": end,
            "exit_code": status,
            "stdout": stdout_lines,
            "stderr": stderr_lines,
            "results_file": str(results_json) if results_json else None,
            "results": extract_results(results_json) if results_json else None,
        }
        
        print(f"[{name}] Completed with exit code {status}")
        return result_data
        
    except subprocess.TimeoutExpired:
        print(f"[{name}] TIMEOUT after 10 minutes")
        return {
            "name": name,
            "start": start,
            "end": end,
            "exit_code": None,
            "stdout": [],
            "stderr": ["Timeout expired"],
            "results_file": None,
            "results": None,
        }
    except Exception as e:
        print(f"[{name}] ERROR: {e}")
        return {
            "name": name,
            "start": start,
            "end": end,
            "exit_code": -1,
            "stdout": [],
            "stderr": [str(e)],
            "results_file": None,
            "results": None,
        }


def find_results_json(output_dir: Path) -> Path | None:
    """Find results.json in LEAN output structure."""
    # LEAN creates backtests/{timestamp}/output/results.json
    backtests_dir = output_dir / "backtests"
    if not backtests_dir.exists():
        return None
    
    for timestamp_dir in backtests_dir.iterdir():
        if timestamp_dir.is_dir():
            results_path = timestamp_dir / "output" / "results.json"
            if results_path.exists():
                return results_path
    
    return None


def extract_results(results_path: Path) -> dict:
    """Extract key metrics from results.json."""
    try:
        with open(results_path) as f:
            data = json.load(f)
        
        stats = data.get("statistics", {})
        
        return {
            "net_profit": stats.get("Total Net Profit", stats.get("Net Profit", "n/a")),
            "sharpe": stats.get("Sharpe Ratio", stats.get("SharpeRatio", "n/a")),
            "total_trades": stats.get("Total Trades", stats.get("TotalOrders", "n/a")),
            "win_rate": stats.get("Win Rate", stats.get("Profit Loss Ratio", "n/a")),
            "compounding_return": stats.get("Compounding Annual Return", stats.get("CAR", "n/a")),
            "alpha": stats.get("Alpha", stats.get("Alpha", "n/a")),
            "beta": stats.get("Beta", stats.get("Beta", "n/a")),
        }
    except Exception as e:
        return {"error": f"Failed to parse results.json: {e}"}


def run_parallel(windows: list, fy_mode: bool = False) -> list:
    """Run all windows in parallel using ThreadPoolExecutor."""
    if fy_mode:
        windows = [FY2025_WINDOW]
    
    results = []
    futures = []
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        for name, start, end in windows:
            output_dir = Path("results") / name
            future = executor.submit(run_backtest, name, start, end, output_dir)
            futures.append((name, future))
        
        for name, future in futures:
            try:
                result = future.result(timeout=720)  # 12 minute timeout per window
                results.append(result)
            except Exception as e:
                print(f"[{name}] Future exception: {e}")
                results.append({
                    "name": name,
                    "error": str(e),
                    "exit_code": -1,
                })
    
    return results


def print_table(results: list) -> None:
    """Print consolidated table."""
    print("\n" + "=" * 60)
    print("PARALLEL BACKTEST RESULTS")
    print(f"{'Window':<10} {'Period':<15} {'Net%':<10} {'Sharpe':<10} {'Trades':<8} {'Win%':<8}")
    print("-" * 60)
    
    for r in results:
        name = r["name"]
        start = r.get("start", "")
        end = r.get("end", "")
        period = f"{start} → {end}" if start and end else name
        
        if r.get("exit_code") != 0 or not r.get("results"):
            print(f"{name:<10} {period:<15} ERROR")
            continue
        
        stats = r["results"]
        net_profit = stats.get("net_profit", "n/a")
        sharpe = stats.get("sharpe", "n/a")
        trades = stats.get("total_trades", "n/a")
        win_rate = stats.get("win_rate", "n/a")
        
        # Format net profit as percentage
        if isinstance(net_profit, (int, float)):
            net_profit_str = f"{net_profit:+.2f}%"
        else:
            net_profit_str = str(net_profit)
        
        # Format win rate as percentage
        if isinstance(win_rate, (int, float)):
            win_rate_str = f"{win_rate:.0f}%"
        else:
            win_rate_str = str(win_rate)
        
        print(f"{name:<10} {period:<15} {net_profit_str:<10} {str(sharpe):<10} {str(trades):<8} {win_rate_str:<8}")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fy", action="store_true", help="Run FY2025 single backtest")
    parser.add_argument("--no-parallel", action="store_true", help="Run sequentially instead of parallel")
    args = parser.parse_args()
    
    # Check lean CLI availability
    if not check_lean_installed():
        print("ERROR: lean CLI not found. Please install Lean CLI and ensure it's in PATH.")
        print("Installation guide: https://www.lean.io/docs/v2/lean-cli/getting-started/installation")
        sys.exit(1)
    
    print(f"Lean CLI detected")
    print(f"Algorithm path: {ALGO_PATH}")
    
    # Create results directory
    results_root = Path("results")
    results_root.mkdir(exist_ok=True)
    
    windows = WINDOWS
    
    if args.fy:
        print("Running FY2025 single backtest")
        windows = [FY2025_WINDOW]
    
    if args.no_parallel:
        print("Running sequentially")
        results = []
        for name, start, end in windows:
            output_dir = results_root / name
            result = run_backtest(name, start, end, output_dir)
            results.append(result)
    else:
        print(f"Running {len(windows)} windows in parallel")
        results = run_parallel(windows, fy_mode=args.fy)
    
    # Save results
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    results_file = results_root / f"parallel-run-{timestamp}.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    print_table(results)
    
    # Check for failures
    failures = [r for r in results if r.get("exit_code") != 0 or not r.get("results")]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  {f['name']}: {f.get('error', 'exit_code=' + str(f.get('exit_code')))}")
        sys.exit(1)


if __name__ == "__main__":
    main()