from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import analyze_monster_runs as M


def test_monster_run_summary_and_outputs(tmp_path: Path) -> None:
    trades = pd.DataFrame(
        [
            {
                "variant_id": "demo",
                "family": "x",
                "status": "closed",
                "symbol": "AAA",
                "entry_order_id": 1,
                "exit_order_id": 2,
                "entry_time": 1,
                "exit_time": 2,
                "entry_date": "2025-01-01",
                "exit_date": "2025-01-03",
                "duration_days": 2,
                "entry_price": 10,
                "exit_price": 12,
                "pnl": 1000,
                "return_pct": 0.20,
                "censored": False,
            },
            {
                "variant_id": "demo",
                "family": "x",
                "status": "closed",
                "symbol": "BBB",
                "entry_order_id": 3,
                "exit_order_id": 4,
                "entry_time": 3,
                "exit_time": 4,
                "entry_date": "2025-01-04",
                "exit_date": "2025-01-12",
                "duration_days": 8,
                "entry_price": 10,
                "exit_price": 10.4,
                "pnl": 100,
                "return_pct": 0.04,
                "censored": False,
            },
            {
                "variant_id": "demo",
                "family": "x",
                "status": "closed",
                "symbol": "CCC",
                "entry_order_id": 5,
                "exit_order_id": 6,
                "entry_time": 5,
                "exit_time": 6,
                "entry_date": "2025-01-05",
                "exit_date": "2025-03-16",
                "duration_days": 70,
                "entry_price": 10,
                "exit_price": 9.9,
                "pnl": -50,
                "return_pct": -0.01,
                "censored": False,
            },
            {
                "variant_id": "demo",
                "family": "x",
                "status": "open",
                "symbol": "DDD",
                "entry_order_id": 7,
                "exit_order_id": "",
                "entry_time": 7,
                "exit_time": "",
                "entry_date": "2025-01-06",
                "exit_date": "",
                "duration_days": "",
                "entry_price": 10,
                "exit_price": "",
                "pnl": 25,
                "return_pct": "",
                "censored": True,
            },
        ]
    )
    input_path = tmp_path / "trades.csv"
    output_dir = tmp_path / "out"
    trades.to_csv(input_path, index=False)

    outputs = M.run(trades_csv=(input_path,), variants=("demo",), output_dir=output_dir, top_n=2)
    summary = pd.read_csv(outputs["variant_summary"])
    buckets = pd.read_csv(outputs["hold_bucket_summary"])
    top = pd.read_csv(outputs["top_trades"])

    assert summary.loc[0, "closed_pnl"] == 1050
    assert summary.loc[0, "open_or_censored_trades"] == 1
    assert summary.loc[0, "top1_positive_pnl_share_pct"] == 90.909
    assert summary.loc[0, "monster_trades"] == 1
    assert buckets.set_index("hold_bucket").loc["0-3d", "pnl"] == 1000
    assert top["symbol"].tolist() == ["AAA", "BBB"]
    assert outputs["report"].exists()
