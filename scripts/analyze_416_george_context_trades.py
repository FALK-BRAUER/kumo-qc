"""#416 trade/order diagnostics for the George-context FY2025 30-pack.

Reads an aggregate `summary.csv` whose rows point at LEAN result JSON files and produces
repeatable diagnostics from the result `orders` and `totalPerformance.closedTrades` payloads.
This does not rerun LEAN; it explains what the completed sweep actually traded.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "sweeps" / "reports" / "george_context_30_fy2025_stable4"


@dataclass(frozen=True)
class TradeRow:
    variant_id: str
    family: str
    symbol: str
    entry_time: str
    entry_date: str
    entry_price: float
    quantity: float
    status: str
    exit_time: str = ""
    exit_date: str = ""
    exit_price: float | None = None
    pnl: float | None = None
    total_fees: float | None = None
    mae: float | None = None
    mfe: float | None = None
    duration_days: float | None = None
    decision_score: float | None = None
    decision_rank: float | None = None
    decision_gap: float | None = None
    decision_vol: float | None = None
    decision_tdist: float | None = None
    decision_cond: str = ""

    @property
    def entry_key(self) -> str:
        return f"{self.symbol}|{self.entry_time}|{self.entry_price:.6f}|{self.quantity:.6f}"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--baseline",
        default="industry_top3_focus",
        help="Variant used for entry/add-miss comparison.",
    )
    return parser.parse_args()


def _iso_date(value: str) -> str:
    if not value:
        return ""
    return value[:10]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _duration_days(value: str) -> float | None:
    if not value:
        return None
    try:
        day_part, clock = value.split(".", 1) if "." in value else ("0", value)
        hours, minutes, seconds = (int(part) for part in clock.split(":"))
        return int(day_part) + (hours / 24.0) + (minutes / 1440.0) + (seconds / 86400.0)
    except Exception:  # noqa: BLE001 - diagnostic parser should tolerate LEAN format drift
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_decision_tag(tag: str) -> dict[str, Any]:
    """Parse LEAN order tag query-string fields into typed decision metrics."""
    raw = dict(parse_qsl(tag or "", keep_blank_values=True))
    out: dict[str, Any] = {"decision_cond": raw.get("decision_cond", "")}
    for key in ("decision_score", "decision_rank", "decision_gap", "decision_vol", "decision_tdist"):
        out[key] = _float_or_none(raw.get(key))
    return out


def _load_summary(report_dir: Path) -> list[dict[str, str]]:
    path = report_dir / "summary.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [row for row in rows if _summary_row_has_result(row)]


def _summary_row_has_result(row: dict[str, str]) -> bool:
    ok_raw = row.get("ok", "True")
    ok = str(ok_raw).strip().lower() in {"1", "true", "yes"}
    return ok and bool(row.get("result_path"))


def _orders_by_id(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    orders = result.get("orders") or {}
    return {int(order["id"]): order for order in orders.values()}


def _closed_trade_by_entry_order(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    closed = result.get("totalPerformance", {}).get("closedTrades") or []
    out: dict[int, dict[str, Any]] = {}
    for trade in closed:
        order_ids = trade.get("orderIds") or []
        if order_ids:
            out[int(order_ids[0])] = trade
    return out


def extract_trades(summary_row: dict[str, str]) -> list[TradeRow]:
    """Extract one row per filled buy order, joined to closed-trade stats when present."""
    result_path = Path(summary_row["result_path"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    orders = _orders_by_id(result)
    closed_by_entry = _closed_trade_by_entry_order(result)
    rows: list[TradeRow] = []

    for order_id, order in sorted(orders.items()):
        if order.get("direction") != 0 or order.get("status") != 3:
            continue
        symbol = str(order.get("symbol", {}).get("value") or "")
        entry_time = str(order.get("lastFillTime") or order.get("time") or "")
        decision = parse_decision_tag(str(order.get("tag") or ""))
        closed = closed_by_entry.get(order_id)
        if closed:
            exit_time = str(closed.get("exitTime") or "")
            status = "closed"
            exit_price = _float_or_none(closed.get("exitPrice"))
            pnl = _float_or_none(closed.get("profitLoss"))
            total_fees = _float_or_none(closed.get("totalFees"))
            mae = _float_or_none(closed.get("mae"))
            mfe = _float_or_none(closed.get("mfe"))
            duration = _duration_days(str(closed.get("duration") or ""))
        else:
            exit_time = ""
            status = "open"
            exit_price = pnl = total_fees = mae = mfe = duration = None
        rows.append(
            TradeRow(
                variant_id=summary_row["variant_id"],
                family=summary_row["family"],
                symbol=symbol,
                entry_time=entry_time,
                entry_date=_iso_date(entry_time),
                entry_price=float(order.get("price") or 0.0),
                quantity=abs(float(order.get("quantity") or 0.0)),
                status=status,
                exit_time=exit_time,
                exit_date=_iso_date(exit_time),
                exit_price=exit_price,
                pnl=pnl,
                total_fees=total_fees,
                mae=mae,
                mfe=mfe,
                duration_days=duration,
                decision_score=decision["decision_score"],
                decision_rank=decision["decision_rank"],
                decision_gap=decision["decision_gap"],
                decision_vol=decision["decision_vol"],
                decision_tdist=decision["decision_tdist"],
                decision_cond=decision["decision_cond"],
            )
        )
    return rows


def _mean(values: list[float | None]) -> str:
    clean = [v for v in values if v is not None]
    return f"{statistics.mean(clean):.3f}" if clean else ""


def _median(values: list[float | None]) -> str:
    clean = [v for v in values if v is not None]
    return f"{statistics.median(clean):.3f}" if clean else ""


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _variant_diagnostics(summary_row: dict[str, str], trades: list[TradeRow]) -> dict[str, str]:
    closed = [t for t in trades if t.status == "closed"]
    open_trades = [t for t in trades if t.status == "open"]
    winners = [t for t in closed if (t.pnl or 0.0) > 0]
    losers = [t for t in closed if (t.pnl or 0.0) <= 0]
    worst = min(closed, key=lambda t: t.pnl if t.pnl is not None else 0.0, default=None)
    best_mfe = max(closed, key=lambda t: t.mfe if t.mfe is not None else -1e18, default=None)
    realized_pnl = sum(t.pnl or 0.0 for t in closed)
    net_profit_est = float(summary_row["ret_pct"]) * 1000.0
    return {
        "variant_id": summary_row["variant_id"],
        "family": summary_row["family"],
        "ret_pct": summary_row["ret_pct"],
        "dd_pct": summary_row["dd_pct"],
        "orders": summary_row["orders"],
        "buy_orders": str(len(trades)),
        "closed_trades": str(len(closed)),
        "open_trades": str(len(open_trades)),
        "closed_win_rate": f"{(len(winners) / len(closed)):.3f}" if closed else "",
        "closed_loser_count": str(len(losers)),
        "net_profit_est": f"{net_profit_est:.2f}",
        "closed_realized_pnl": f"{realized_pnl:.2f}",
        "implied_open_pnl": f"{(net_profit_est - realized_pnl):.2f}",
        "avg_closed_pnl": _mean([t.pnl for t in closed]),
        "median_closed_pnl": _median([t.pnl for t in closed]),
        "avg_mfe": _mean([t.mfe for t in closed]),
        "avg_mae": _mean([t.mae for t in closed]),
        "avg_duration_days": _mean([t.duration_days for t in closed]),
        "avg_decision_rank": _mean([t.decision_rank for t in trades]),
        "avg_decision_gap": _mean([t.decision_gap for t in trades]),
        "avg_decision_vol": _mean([t.decision_vol for t in trades]),
        "worst_symbol": worst.symbol if worst else "",
        "worst_pnl": _fmt(worst.pnl) if worst else "",
        "worst_mfe": _fmt(worst.mfe) if worst else "",
        "worst_mae": _fmt(worst.mae) if worst else "",
        "best_mfe_symbol": best_mfe.symbol if best_mfe else "",
        "best_mfe": _fmt(best_mfe.mfe) if best_mfe else "",
        "entry_symbols": " ".join(sorted({t.symbol for t in trades})),
        "open_symbols": " ".join(sorted({t.symbol for t in open_trades})),
    }


def _closed_pnl_by_key(trades: list[TradeRow]) -> dict[str, float]:
    return {t.entry_key: float(t.pnl or 0.0) for t in trades if t.status == "closed"}


def _compare_to_baseline(
    summary_row: dict[str, str],
    trades: list[TradeRow],
    baseline_trades: list[TradeRow],
) -> dict[str, str]:
    keys = {t.entry_key for t in trades}
    base_keys = {t.entry_key for t in baseline_trades}
    added = sorted(keys - base_keys)
    missed = sorted(base_keys - keys)
    closed_pnl = _closed_pnl_by_key(trades)
    base_closed_pnl = _closed_pnl_by_key(baseline_trades)
    added_rows = [t for t in trades if t.entry_key in added]
    missed_rows = [t for t in baseline_trades if t.entry_key in missed]
    same_symbols = {t.symbol for t in trades} & {t.symbol for t in baseline_trades}
    return {
        "variant_id": summary_row["variant_id"],
        "family": summary_row["family"],
        "ret_pct": summary_row["ret_pct"],
        "dd_pct": summary_row["dd_pct"],
        "same_entry_count": str(len(keys & base_keys)),
        "added_entry_count": str(len(added)),
        "missed_entry_count": str(len(missed)),
        "same_symbol_count": str(len(same_symbols)),
        "added_closed_pnl": f"{sum(closed_pnl.get(k, 0.0) for k in added):.2f}",
        "missed_closed_pnl": f"{sum(base_closed_pnl.get(k, 0.0) for k in missed):.2f}",
        "added_symbols": " ".join(sorted({t.symbol for t in added_rows})),
        "missed_symbols": " ".join(sorted({t.symbol for t in missed_rows})),
        "added_open_symbols": " ".join(sorted({t.symbol for t in added_rows if t.status == "open"})),
        "missed_open_symbols": " ".join(sorted({t.symbol for t in missed_rows if t.status == "open"})),
    }


def _as_trade_dict(row: TradeRow, baseline_keys: set[str]) -> dict[str, str]:
    return {
        "variant_id": row.variant_id,
        "family": row.family,
        "symbol": row.symbol,
        "entry_time": row.entry_time,
        "entry_date": row.entry_date,
        "entry_price": f"{row.entry_price:.6f}",
        "quantity": f"{row.quantity:.6f}",
        "status": row.status,
        "exit_time": row.exit_time,
        "exit_date": row.exit_date,
        "exit_price": _fmt(row.exit_price),
        "pnl": _fmt(row.pnl),
        "total_fees": _fmt(row.total_fees),
        "mae": _fmt(row.mae),
        "mfe": _fmt(row.mfe),
        "duration_days": _fmt(row.duration_days),
        "decision_score": _fmt(row.decision_score),
        "decision_rank": _fmt(row.decision_rank),
        "decision_gap": _fmt(row.decision_gap),
        "decision_vol": _fmt(row.decision_vol),
        "decision_tdist": _fmt(row.decision_tdist),
        "decision_cond": row.decision_cond,
        "entry_in_baseline": str(row.entry_key in baseline_keys),
    }


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(
    path: Path,
    *,
    baseline: str,
    variant_rows: list[dict[str, str]],
    delta_rows: list[dict[str, str]],
) -> None:
    ranked = sorted(variant_rows, key=lambda r: float(r["ret_pct"]), reverse=True)
    high_change = sorted(delta_rows, key=lambda r: int(r["added_entry_count"]) + int(r["missed_entry_count"]), reverse=True)
    lines = [
        "# George Context Trade Diagnostics",
        "",
        f"Baseline for entry deltas: `{baseline}`.",
        "",
        "## Variant Diagnostics",
        "",
        "| Variant | Return % | DD % | Buys | Closed | Open | Net PnL | Realized PnL | Implied Open PnL | Worst |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in ranked[:12]:
        worst = f"{row['worst_symbol']} {row['worst_pnl']}".strip()
        lines.append(
            f"| {row['variant_id']} | {row['ret_pct']} | {row['dd_pct']} | {row['buy_orders']} | "
            f"{row['closed_trades']} | {row['open_trades']} | {row['net_profit_est']} | "
            f"{row['closed_realized_pnl']} | {row['implied_open_pnl']} | {worst} |"
        )
    lines.extend(
        [
            "",
            "## Largest Entry-Set Deltas",
            "",
            "| Variant | Added | Missed | Same Entries | Added Symbols | Missed Symbols |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for row in high_change[:12]:
        lines.append(
            f"| {row['variant_id']} | {row['added_entry_count']} | {row['missed_entry_count']} | "
            f"{row['same_entry_count']} | {row['added_symbols']} | {row['missed_symbols']} |"
        )
    lines.extend(["", "## Readout", ""])
    lines.extend(_readout_lines(variant_rows, delta_rows))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _readout_lines(
    variant_rows: list[dict[str, str]],
    delta_rows: list[dict[str, str]],
) -> list[str]:
    if not variant_rows:
        return ["- No successful result rows were available for diagnostics."]

    ret_values = {row["ret_pct"] for row in variant_rows}
    dd_values = {row["dd_pct"] for row in variant_rows}
    order_values = {row["orders"] for row in variant_rows}
    entry_changes = [
        int(row["added_entry_count"]) + int(row["missed_entry_count"])
        for row in delta_rows
    ]
    all_same_entries = all(change == 0 for change in entry_changes)
    lines: list[str] = []

    if len(ret_values) == len(dd_values) == len(order_values) == 1 and all_same_entries:
        lines.append(
            "- All successful variants preserve the same entry set, order count, return, and drawdown."
        )
        lines.append(
            "- The tested phase settings did not bind in this FY2025 window; inspect later waves for exit-path sensitivity."
        )
    else:
        max_change = max(entry_changes, default=0)
        lines.append(
            f"- Entry-set deltas versus baseline range from 0 to {max_change} added/missed entries."
        )
        lines.append(
            "- Compare return and drawdown changes against those entry deltas before attributing performance to exits."
        )

    open_pnl_values = [float(row["implied_open_pnl"]) for row in variant_rows if row["implied_open_pnl"]]
    realized_values = [float(row["closed_realized_pnl"]) for row in variant_rows if row["closed_realized_pnl"]]
    if open_pnl_values and realized_values and min(open_pnl_values) > 0 and max(realized_values) < 0:
        lines.append(
            "- Net profit is carried by open year-end positions; closed-trade realized PnL is negative."
        )
    return lines


def run(report_dir: Path, baseline: str) -> None:
    summary = _load_summary(report_dir)
    by_variant = {row["variant_id"]: extract_trades(row) for row in summary}
    if baseline not in by_variant:
        raise KeyError(f"baseline {baseline!r} not present in {report_dir / 'summary.csv'}")
    baseline_trades = by_variant[baseline]
    baseline_keys = {t.entry_key for t in baseline_trades}

    variant_rows = [_variant_diagnostics(row, by_variant[row["variant_id"]]) for row in summary]
    delta_rows = [
        _compare_to_baseline(row, by_variant[row["variant_id"]], baseline_trades)
        for row in summary
    ]
    trade_rows = [
        _as_trade_dict(trade, baseline_keys)
        for row in summary
        for trade in by_variant[row["variant_id"]]
    ]

    _write_csv(
        report_dir / "trade_diagnostics.csv",
        sorted(variant_rows, key=lambda r: float(r["ret_pct"]), reverse=True),
        [
            "variant_id", "family", "ret_pct", "dd_pct", "orders", "buy_orders",
            "closed_trades", "open_trades", "closed_win_rate", "closed_loser_count",
            "net_profit_est", "closed_realized_pnl", "implied_open_pnl", "avg_closed_pnl",
            "median_closed_pnl", "avg_mfe", "avg_mae", "avg_duration_days",
            "avg_decision_rank", "avg_decision_gap", "avg_decision_vol", "worst_symbol",
            "worst_pnl", "worst_mfe", "worst_mae", "best_mfe_symbol", "best_mfe",
            "entry_symbols", "open_symbols",
        ],
    )
    _write_csv(
        report_dir / "trade_deltas_vs_baseline.csv",
        sorted(delta_rows, key=lambda r: (int(r["added_entry_count"]) + int(r["missed_entry_count"]), r["variant_id"]), reverse=True),
        [
            "variant_id", "family", "ret_pct", "dd_pct", "same_entry_count",
            "added_entry_count", "missed_entry_count", "same_symbol_count",
            "added_closed_pnl", "missed_closed_pnl", "added_symbols", "missed_symbols",
            "added_open_symbols", "missed_open_symbols",
        ],
    )
    _write_csv(
        report_dir / "symbol_trade_diagnostics.csv",
        trade_rows,
        [
            "variant_id", "family", "symbol", "entry_time", "entry_date", "entry_price",
            "quantity", "status", "exit_time", "exit_date", "exit_price", "pnl",
            "total_fees", "mae", "mfe", "duration_days", "decision_score",
            "decision_rank", "decision_gap", "decision_vol", "decision_tdist",
            "decision_cond", "entry_in_baseline",
        ],
    )
    _write_markdown(
        report_dir / "trade_diagnostics.md",
        baseline=baseline,
        variant_rows=variant_rows,
        delta_rows=delta_rows,
    )
    print(f"WROTE {report_dir / 'trade_diagnostics.csv'}")
    print(f"WROTE {report_dir / 'trade_deltas_vs_baseline.csv'}")
    print(f"WROTE {report_dir / 'symbol_trade_diagnostics.csv'}")
    print(f"WROTE {report_dir / 'trade_diagnostics.md'}")


def main() -> None:
    args = _args()
    run(args.report_dir.resolve(), args.baseline)


if __name__ == "__main__":
    main()
