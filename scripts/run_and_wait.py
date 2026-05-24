#!/usr/bin/env python3
"""
Run a window via lean cloud backtest and poll results.
"""

import subprocess
import time
import json
import sys

WINDOWS = [
    ('W1', '2026-04-07', '2026-04-11'),
    ('W2', '2026-04-14', '2026-04-18'),
    ('W3', '2026-04-21', '2026-04-25'),
    ('W6', '2026-05-12', '2026-05-16'),
    ('FY2025', '2025-01-01', '2025-12-31'),
]

def run_window(name, start, end):
    """Submit via lean CLI."""
    cmd = [
        'lean', 'cloud', 'backtest', 'performance_bct',
        '--name', f'perf-{name}',
        '--parameter', 'start_year', start.split('-')[0],
        '--parameter', 'start_month', start.split('-')[1],
        '--parameter', 'start_day', start.split('-')[2],
        '--parameter', 'end_year', end.split('-')[0],
        '--parameter', 'end_month', end.split('-')[1],
        '--parameter', 'end_day', end.split('-')[2],
        '--parameter', 'cloud_exit', 'True',
        '--parameter', 'weekly_kijun_exit', 'True',
        '--parameter', 'warmup_days', '200',
    ]
    print(f'\n\n--- Submit {name}: {start} to {end}')
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f'Submit failed: {result.stderr}')
        return None
    # Extract backtest ID from output
    lines = result.stdout.split('\n')
    backtest_id = None
    backtest_url = None
    for line in lines:
        if 'Backtest id:' in line:
            backtest_id = line.split(':')[1].strip()
        elif 'Backtest url:' in line:
            backtest_url = line.strip()
    return {'backtest_id': backtest_id, 'url': backtest_url}

def poll_result(name, backtest_id):
    """Poll via lean cloud status."""
    for i in range(60):
        cmd = ['lean', 'cloud', 'status', 'performance_bct']
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Parse progress
        lines = result.stdout.split('\n')
        for line in lines:
            if f'perf-{name}' in line:
                # extract status
                pass
        time.sleep(30)
        if i % 2 == 0:
            print(f'  {name}: polling...')
    return {'name': name, 'status': 'unknown'}

def main():
    for window in WINDOWS:
        name, start, end = window
        meta = run_window(name, start, end)
        if not meta:
            print(f'{name} submit failed')
            continue
        print(f'{name} submitted: {meta.get("backtest_id")}')
        # Wait for completion (approx 30 mins)
        time.sleep(1800)  # 30 minutes
        # TODO: poll lean cloud status to fetch stats
        print(f'{name} presumably done')
    print('All windows submitted')

if __name__ == '__main__':
    main()