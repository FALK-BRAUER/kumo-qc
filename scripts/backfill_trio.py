#!/usr/bin/env python3
"""
Backfill Sharpe/Return%/DD% trio for today's (2026-05-30) bt-results.csv rows from
on-disk backtest artifacts. CORRECTS the contaminated P1 grid (rows 316-323) to
real artifact values. Never fabricates: rows with no recoverable artifact are
annotated, not invented.

cols (0-idx): 7=sharpe 8=net_profit_pct 12=max_drawdown_pct 14=notes
"""
import csv
import sys

CSV = "/Users/falk/projects/kumo-qc/bt-results.csv"

# row_number (1-based incl header) -> (sharpe, ret_pct, dd_pct, correction_note)
# values from artifacts pulled this session.
FIX = {
    300: (0.252, 11.051, 8.7, None),
    301: (0.546, 16.113, 7.6, None),
    302: (0.484, 15.850, 11.2, None),
    303: (0.087, 8.480, 8.5, None),
    304: (0.667, 20.534, 7.9, None),
    309: (0.073, 8.111, 9.7, None),
    310: (0.09, 8.392, 10.9, None),
    # 311 pyramid-B-200: NO matching artifact found — not backfilled (see annotate)
    312: (-0.12, 5.240, 10.7, None),
    313: (0.667, 19.872, 8.8, None),
    314: (0.393, 14.824, 11.9, None),
    315: (0.121, 9.048, 12.3, None),
    # P1 grid — CORRECTED from contaminated originals (compile-cache bug)
    316: (-0.516, 2.486, 6.4, "CORRECTED from contaminated 0.044 (compile-cache)"),
    317: (0.042, 7.994, 7.6, "CORRECTED from contaminated -0.105"),
    318: (0.252, 10.747, 7.8, "CORRECTED from contaminated 0.236"),
    319: (0.249, 10.702, 7.3, "CORRECTED from contaminated 0.131"),
    320: (0.295, 11.694, 8.6, "CORRECTED from contaminated 0.143"),
    321: (0.188, 10.139, 8.1, "CORRECTED from contaminated 0.286"),
    322: (0.371, 13.152, 9.0, "CORRECTED from phantom 0.392 WINNER — real artifact"),
    323: (0.536, 15.993, 8.0, "CORRECTED from contaminated 0.385 — real winner me10"),
}
# rows whose artifact is unrecoverable — annotate only, do NOT fabricate trio
ANNOTATE = {
    293: "DD: cloud artifact, not backfilled locally",
    311: "artifact unavailable on disk — trio not backfilled (no fabrication)",
}

lines = open(CSV).read().splitlines()
out = []
for i, line in enumerate(lines, start=1):
    if i in FIX or i in ANNOTATE:
        # notes is the last field and may contain commas → split first 14 only
        parts = line.split(",", 14)
        if len(parts) < 15:
            parts += [""] * (15 - len(parts))
        if i in FIX:
            sh, ret, dd, note = FIX[i]
            parts[7] = str(sh)
            parts[8] = str(ret)
            parts[12] = str(dd)
            if note:
                parts[14] = (parts[14].rstrip() + f" [{note}]").strip()
        if i in ANNOTATE:
            parts[14] = (parts[14].rstrip() + f" [{ANNOTATE[i]}]").strip()
        line = ",".join(parts)
    out.append(line)

open(CSV, "w").write("\n".join(out) + "\n")
print(f"backfilled {len(FIX)} rows, annotated {len(ANNOTATE)} unrecoverable")
