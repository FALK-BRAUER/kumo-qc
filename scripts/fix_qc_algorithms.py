#!/usr/bin/env python3
"""
Batch fix QC downloaded algorithm.py files:
- Add ETF lines after set_warmup
- Change list(self._active) → sorted(self._active)
"""
import os
import re

ETF_LINES = """# Add ETFs explicitly (Morningstar fundamental data excludes ETFs)
# These will be included in the BCT scoring universe
etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
for etf_symbol in etfs:
    self.add_equity(etf_symbol)
"""

def fix_etf_lines(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Insert ETF lines after set_warmup(timedelta(days=750))
    pattern = r'self\.set_warmup\(timedelta\(days=750\)\)\s*\n\s*self\.universe_settings\.resolution = Resolution\.DAILY'
    replacement = 'self.set_warmup(timedelta(days=750))\n\n        # Add ETFs explicitly (Morningstar fundamental data excludes ETFs)\n        # These will be included in the BCT scoring universe\n        etfs = ["QQQ", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]\n        for etf_symbol in etfs:\n            self.add_equity(etf_symbol)\n\n        self.universe_settings.resolution = Resolution.DAILY'
    
    if pattern in content:
        content = re.sub(pattern, replacement, content)
    
    # Replace list(self._active) → sorted(self._active)
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