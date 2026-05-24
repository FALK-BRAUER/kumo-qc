#!/usr/bin/env python3
"""
Fix QC downloaded algorithm.py files:
- Insert ETF lines between set_warmup and universe_settings
- Change list(self._active) → sorted(self._active)
"""
import os
import re

ETF_LINES = """        # Add ETFs explicitly (Morningstar fundamental data excludes ETFs)
        # These will be included in the BCT scoring universe
        etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        for etf_symbol in etfs:
            self.add_equity(etf_symbol)

"""

def fix_etf_lines(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    # Find set_warmup line
    for i, line in enumerate(lines):
        if line.strip() == 'self.set_warmup(timedelta(days=750))':
            # Insert ETF lines after this line
            lines.insert(i + 1, ETF_LINES)
            break
    
    # Replace list(self._active) → sorted(self._active)
    content = ''.join(lines)
    content = re.sub(r'list\(self\._active\)', 'sorted(self._active)', content)
    
    with open(filepath, 'w') as f:
        f.write(content)
    print(f"Fixed {filepath}")

def main():
    for dirname in os.listdir('qc'):
        if dirname.startswith('.'):
            continue
        algo_path = os.path.join('qc', dirname, 'algorithm.py')
        if os.path.exists(algo_path):
            fix_etf_lines(algo_path)

if __name__ == '__main__':
    main()