"""#455 diagnostics: convert LambdaMART top20 edge into realized-PnL hypotheses.

This script does not rerun LEAN. It reads the committed #453 summary rows plus
local raw LEAN result artifacts and compares scanner-off controls against
scanner-top20 variants for the three real strategy bases.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "sweeps" / "reports" / "scanner_ranker_real_strategy_fy2025_453_combined"
DEFAULT_OUTPUT_DIR = ROOT / "sweeps" / "reports" / "top20_realized_pnl_diagnostics_455"
FY_END = date(2025, 12, 31)
TARGET_BASE_MODULES = {
    "strategies.realized_giveback_no_bull",
    "strategies.realized_target_04_fast_take",
    "strategies.realized_target_08_let_run",
}
TARGET_SETTINGS = {"off", "top20"}

EXIT_RE = re.compile(
    r"(?:(?P<prefix>EXIT_EVENT)|(?P<legacy>SCRATCH_FLAT_EXIT|PROACTIVE_STRENGTH_EXIT))\|"
    r"(?P<date>\d{4}-\d{2}-\d{2})\|(?P<symbol>[A-Za-z0-9.\-]+)\|(?P<rest>[^\n\r]*)"
)
EXIT_EVENT_DONE_RE = re.compile(r"(?:^|\|)giveback_from_peak_pct=-?\d+(?:\.\d+)?$")
LEAN_LOG_PREFIX_RE = re.compile(r"^\d{8}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\w+::")


@dataclass(frozen=True)
class ExitEvent:
    variant_id: str
    date: str
    symbol: str
    event: str
    module: str
    reason: str
    days_held: str
    pnl: float | None
    return_pct: float | None
    mfe_pct: float | None
    mae_pct: float | None
    giveback_from_peak_pct: float | None
    raw: str


@dataclass(frozen=True)
class TradeRow:
    variant_id: str
    base_module: str
    scanner_setting: str
    symbol: str
    entry_order_id: int
    entry_time: str
    entry_date: str
    entry_price: float
    quantity: float
    status: str
    exit_order_id: str = ""
    exit_time: str = ""
    exit_date: str = ""
    exit_price: float | None = None
    closed_pnl: float | None = None
    total_fees: float | None = None
    mae_abs: float | None = None
    mfe_abs: float | None = None
    mae_pct: float | None = None
    mfe_pct: float | None = None
    giveback_from_peak_pct: float | None = None
    duration_days: float | None = None
    exit_reason: str = ""
    exit_module: str = ""
    decision_rank: float | None = None
    decision_gap: float | None = None
    decision_vol: float | None = None
    decision_tdist: float | None = None
    allocated_unrealized_est: float | None = None

    @property
    def entry_cost(self) -> float:
        return self.entry_price * self.quantity

    @property
    def age_days_to_fy_end(self) -> int | None:
        try:
            return (FY_END - date.fromisoformat(self.entry_date)).days
        except ValueError:
            return None


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="Root used to resolve relative raw result paths from summary.csv.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    return _float_or_none(value) or 0.0


def _fmt(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _fmt2(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _mean(values: list[float | None]) -> str:
    clean = [v for v in values if v is not None]
    return f"{statistics.mean(clean):.3f}" if clean else ""


def _iso_date(value: str) -> str:
    return value[:10] if value else ""


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _duration_days(value: str) -> float | None:
    if not value:
        return None
    try:
        day_part, clock = value.split(".", 1) if "." in value else ("0", value)
        hours, minutes, seconds = (int(part) for part in clock.split(":"))
        return int(day_part) + (hours / 24.0) + (minutes / 1440.0) + (seconds / 86400.0)
    except Exception:  # noqa: BLE001 - diagnostic parser should tolerate LEAN drift.
        return None


def _resolve_path(path_text: str, *, source_root: Path, repo_root: Path = ROOT) -> Path:
    raw = Path(path_text)
    candidates = [raw]
    if not raw.is_absolute():
        candidates = [source_root / raw, repo_root / raw, raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _load_summary(report_dir: Path) -> list[dict[str, str]]:
    path = report_dir / "summary.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [
        row
        for row in rows
        if row.get("base_module") in TARGET_BASE_MODULES
        and row.get("scanner_setting") in TARGET_SETTINGS
        and row.get("result_path")
    ]


def _decision_tag(tag: str) -> dict[str, float | None]:
    raw = dict(parse_qsl(tag or "", keep_blank_values=True))
    return {
        key: _float_or_none(raw.get(key))
        for key in ("decision_rank", "decision_gap", "decision_vol", "decision_tdist")
    }


def _symbol(order_or_trade: dict[str, Any]) -> str:
    symbol = order_or_trade.get("symbol")
    if isinstance(symbol, dict):
        return str(symbol.get("value") or symbol.get("permtick") or "")
    symbols = order_or_trade.get("symbols")
    if isinstance(symbols, list) and symbols:
        first = symbols[0]
        if isinstance(first, dict):
            return str(first.get("value") or first.get("permtick") or "")
    return str(symbol or "")


def _orders_by_id(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    orders = result.get("orders") or {}
    return {int(order["id"]): order for order in orders.values()}


def _closed_trade_by_entry_order(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for trade in result.get("totalPerformance", {}).get("closedTrades") or []:
        order_ids = trade.get("orderIds") or []
        if order_ids:
            out[int(order_ids[0])] = trade
    return out


def _exit_record_complete(record: str) -> bool:
    if record.startswith("EXIT_EVENT|"):
        return EXIT_EVENT_DONE_RE.search(record) is not None
    return True


def _exit_event_records(text: str) -> list[str]:
    records: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = EXIT_RE.search(line)
        if match is not None:
            if pending:
                records.append(pending)
            pending = line[match.start():]
            if _exit_record_complete(pending):
                records.append(pending)
                pending = ""
            continue
        if pending:
            if LEAN_LOG_PREFIX_RE.match(line):
                records.append(pending)
                pending = ""
                continue
            pending += line
            if _exit_record_complete(pending):
                records.append(pending)
                pending = ""
    if pending:
        records.append(pending)
    return records


def parse_exit_events(stdout_path: Path, variant_id: str) -> list[ExitEvent]:
    if not stdout_path.exists():
        return []
    events: list[ExitEvent] = []
    for record in _exit_event_records(stdout_path.read_text(encoding="utf-8", errors="replace")):
        match = EXIT_RE.search(record)
        if not match:
            continue
        fields: dict[str, str] = {}
        for part in match.group("rest").split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
        events.append(
            ExitEvent(
                variant_id=variant_id,
                date=match.group("date"),
                symbol=match.group("symbol").upper(),
                event=fields.get("event") or match.group("legacy") or "EXIT_EVENT",
                module=fields.get("module") or "",
                reason=fields.get("reason") or "",
                days_held=fields.get("days_held") or fields.get("days") or "",
                pnl=_float_or_none(fields.get("pnl")),
                return_pct=_float_or_none(fields.get("return_pct")),
                mfe_pct=_float_or_none(fields.get("mfe_pct")),
                mae_pct=_float_or_none(fields.get("mae_pct")),
                giveback_from_peak_pct=_float_or_none(fields.get("giveback_from_peak_pct")),
                raw=record,
            )
        )
    return events


def _exit_queues(events: list[ExitEvent]) -> dict[tuple[str, str], deque[ExitEvent]]:
    queues: dict[tuple[str, str], deque[ExitEvent]] = defaultdict(deque)
    for event in events:
        queues[(event.symbol, event.date)].append(event)
    return queues


def _run_dir_from_row(row: dict[str, str], *, source_root: Path, result_path: Path) -> Path:
    if row.get("run_dir"):
        return _resolve_path(row["run_dir"], source_root=source_root)
    return result_path.parents[2]


def extract_trades(row: dict[str, str], *, source_root: Path) -> tuple[list[TradeRow], list[ExitEvent]]:
    result_path = _resolve_path(row["result_path"], source_root=source_root)
    if not result_path.exists():
        raise FileNotFoundError(f"missing raw result for {row['variant_id']}: {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    run_dir = _run_dir_from_row(row, source_root=source_root, result_path=result_path)
    exit_events = parse_exit_events(run_dir / "lean-stdout.txt", row["variant_id"])
    exit_queues = _exit_queues(exit_events)
    closed_by_entry = _closed_trade_by_entry_order(result)
    trades: list[TradeRow] = []

    for order_id, order in sorted(_orders_by_id(result).items()):
        if order.get("direction") != 0 or order.get("status") != 3:
            continue
        symbol = _symbol(order).upper()
        entry_time = str(order.get("lastFillTime") or order.get("time") or "")
        decision = _decision_tag(str(order.get("tag") or ""))
        entry_price = float(order.get("price") or 0.0)
        quantity = abs(float(order.get("quantity") or 0.0))
        closed = closed_by_entry.get(order_id)
        exit_event: ExitEvent | None = None

        if closed:
            exit_time = str(closed.get("exitTime") or "")
            exit_date = _iso_date(exit_time)
            queue = exit_queues.get((symbol, exit_date))
            if queue:
                exit_event = queue.popleft()
            mfe_abs = _float_or_none(closed.get("mfe"))
            mae_abs = _float_or_none(closed.get("mae"))
            entry_cost = entry_price * quantity
            trades.append(
                TradeRow(
                    variant_id=row["variant_id"],
                    base_module=row["base_module"],
                    scanner_setting=row["scanner_setting"],
                    symbol=symbol,
                    entry_order_id=order_id,
                    entry_time=entry_time,
                    entry_date=_iso_date(entry_time),
                    entry_price=entry_price,
                    quantity=quantity,
                    status="closed",
                    exit_order_id=str((closed.get("orderIds") or ["", ""])[-1]),
                    exit_time=exit_time,
                    exit_date=exit_date,
                    exit_price=_float_or_none(closed.get("exitPrice")),
                    closed_pnl=_float_or_none(closed.get("profitLoss")),
                    total_fees=_float_or_none(closed.get("totalFees")),
                    mae_abs=mae_abs,
                    mfe_abs=mfe_abs,
                    mae_pct=exit_event.mae_pct if exit_event else (mae_abs / entry_cost if entry_cost else None),
                    mfe_pct=exit_event.mfe_pct if exit_event else (mfe_abs / entry_cost if entry_cost else None),
                    giveback_from_peak_pct=exit_event.giveback_from_peak_pct if exit_event else None,
                    duration_days=_duration_days(str(closed.get("duration") or "")),
                    exit_reason=exit_event.reason if exit_event else "",
                    exit_module=exit_event.module if exit_event else "",
                    decision_rank=decision["decision_rank"],
                    decision_gap=decision["decision_gap"],
                    decision_vol=decision["decision_vol"],
                    decision_tdist=decision["decision_tdist"],
                )
            )
        else:
            trades.append(
                TradeRow(
                    variant_id=row["variant_id"],
                    base_module=row["base_module"],
                    scanner_setting=row["scanner_setting"],
                    symbol=symbol,
                    entry_order_id=order_id,
                    entry_time=entry_time,
                    entry_date=_iso_date(entry_time),
                    entry_price=entry_price,
                    quantity=quantity,
                    status="open",
                    decision_rank=decision["decision_rank"],
                    decision_gap=decision["decision_gap"],
                    decision_vol=decision["decision_vol"],
                    decision_tdist=decision["decision_tdist"],
                )
            )

    unrealized = _float(row.get("unrealized"))
    open_cost = sum(trade.entry_cost for trade in trades if trade.status == "open")
    if open_cost:
        trades = [
            trade
            if trade.status != "open"
            else TradeRow(**{**trade.__dict__, "allocated_unrealized_est": unrealized * trade.entry_cost / open_cost})
            for trade in trades
        ]
    return trades, exit_events


def _variant_row(summary: dict[str, str], trades: list[TradeRow]) -> dict[str, str]:
    closed = [trade for trade in trades if trade.status == "closed"]
    open_trades = [trade for trade in trades if trade.status == "open"]
    reason_counts = Counter(trade.exit_reason or "unknown" for trade in closed)
    worst = min(closed, key=lambda trade: trade.closed_pnl or 0.0, default=None)
    open_worst = min(open_trades, key=lambda trade: trade.allocated_unrealized_est or 0.0, default=None)
    return {
        "variant_id": summary["variant_id"],
        "base_module": summary["base_module"],
        "scanner_setting": summary["scanner_setting"],
        "ret_pct": summary["ret_pct"],
        "dd_pct": summary["dd_pct"],
        "orders": summary["orders"],
        "summary_realized_net": f"{_float(summary.get('realized_net')):.2f}",
        "summary_unrealized": f"{_float(summary.get('unrealized')):.2f}",
        "buy_entries": str(len(trades)),
        "closed_trades": str(len(closed)),
        "open_lots": str(len(open_trades)),
        "closed_pnl_sum": f"{sum(trade.closed_pnl or 0.0 for trade in closed):.2f}",
        "allocated_open_unrealized_est": f"{sum(trade.allocated_unrealized_est or 0.0 for trade in open_trades):.2f}",
        "avg_mfe_pct": _mean([trade.mfe_pct for trade in closed]),
        "avg_mae_pct": _mean([trade.mae_pct for trade in closed]),
        "avg_giveback_pct": _mean([trade.giveback_from_peak_pct for trade in closed]),
        "avg_duration_days": _mean([trade.duration_days for trade in closed]),
        "avg_decision_rank": _mean([trade.decision_rank for trade in trades]),
        "exit_reason_counts": ";".join(f"{key}:{value}" for key, value in sorted(reason_counts.items())),
        "worst_closed_symbol": worst.symbol if worst else "",
        "worst_closed_pnl": _fmt2(worst.closed_pnl) if worst else "",
        "worst_open_symbol": open_worst.symbol if open_worst else "",
        "worst_open_unrealized_est": _fmt2(open_worst.allocated_unrealized_est) if open_worst else "",
        "open_symbols": " ".join(sorted({trade.symbol for trade in open_trades})),
    }


def _symbol_aggregate(trades: list[TradeRow]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "entries": 0,
            "closed": 0,
            "open": 0,
            "closed_pnl": 0.0,
            "open_unrealized_est": 0.0,
            "entry_cost": 0.0,
            "decision_ranks": [],
            "mfe_pcts": [],
            "mae_pcts": [],
            "exit_reasons": Counter(),
        }
    )
    for trade in trades:
        row = out[trade.symbol]
        row["entries"] += 1
        row["entry_cost"] += trade.entry_cost
        if trade.status == "closed":
            row["closed"] += 1
            row["closed_pnl"] += trade.closed_pnl or 0.0
            row["mfe_pcts"].append(trade.mfe_pct)
            row["mae_pcts"].append(trade.mae_pct)
            row["exit_reasons"][trade.exit_reason or "unknown"] += 1
        else:
            row["open"] += 1
            row["open_unrealized_est"] += trade.allocated_unrealized_est or 0.0
        if trade.decision_rank is not None:
            row["decision_ranks"].append(trade.decision_rank)
    return out


def _symbol_delta_rows(base_module: str, off: list[TradeRow], top20: list[TradeRow]) -> list[dict[str, str]]:
    off_by_symbol = _symbol_aggregate(off)
    top_by_symbol = _symbol_aggregate(top20)
    rows: list[dict[str, str]] = []
    for symbol in sorted(set(off_by_symbol) | set(top_by_symbol)):
        off_row = off_by_symbol.get(symbol, {})
        top_row = top_by_symbol.get(symbol, {})
        off_entries = int(off_row.get("entries", 0))
        top_entries = int(top_row.get("entries", 0))
        relation = "shared"
        if off_entries and not top_entries:
            relation = "removed_by_top20"
        elif top_entries and not off_entries:
            relation = "added_by_top20"
        rows.append(
            {
                "base_module": base_module,
                "symbol": symbol,
                "relation": relation,
                "off_entries": str(off_entries),
                "top20_entries": str(top_entries),
                "delta_entries": str(top_entries - off_entries),
                "off_closed_pnl": f"{float(off_row.get('closed_pnl', 0.0)):.2f}",
                "top20_closed_pnl": f"{float(top_row.get('closed_pnl', 0.0)):.2f}",
                "delta_closed_pnl": f"{float(top_row.get('closed_pnl', 0.0)) - float(off_row.get('closed_pnl', 0.0)):.2f}",
                "off_open_lots": str(int(off_row.get("open", 0))),
                "top20_open_lots": str(int(top_row.get("open", 0))),
                "off_open_unrealized_est": f"{float(off_row.get('open_unrealized_est', 0.0)):.2f}",
                "top20_open_unrealized_est": f"{float(top_row.get('open_unrealized_est', 0.0)):.2f}",
                "delta_open_unrealized_est": f"{float(top_row.get('open_unrealized_est', 0.0)) - float(off_row.get('open_unrealized_est', 0.0)):.2f}",
                "off_avg_rank": _mean(off_row.get("decision_ranks", [])),
                "top20_avg_rank": _mean(top_row.get("decision_ranks", [])),
                "top20_avg_mfe_pct": _mean(top_row.get("mfe_pcts", [])),
                "top20_avg_mae_pct": _mean(top_row.get("mae_pcts", [])),
                "top20_exit_reasons": ";".join(
                    f"{key}:{value}" for key, value in sorted(top_row.get("exit_reasons", Counter()).items())
                ),
            }
        )
    return rows


def _entry_key(trade: TradeRow) -> tuple[str, str]:
    return trade.symbol, trade.entry_date


def _entry_aggregate(trades: list[TradeRow]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "entries": 0,
            "closed": 0,
            "open": 0,
            "closed_pnl": 0.0,
            "open_unrealized_est": 0.0,
            "entry_cost": 0.0,
            "decision_ranks": [],
            "mfe_pcts": [],
            "mae_pcts": [],
        }
    )
    for trade in trades:
        row = out[_entry_key(trade)]
        row["entries"] += 1
        row["entry_cost"] += trade.entry_cost
        if trade.status == "closed":
            row["closed"] += 1
            row["closed_pnl"] += trade.closed_pnl or 0.0
            row["mfe_pcts"].append(trade.mfe_pct)
            row["mae_pcts"].append(trade.mae_pct)
        else:
            row["open"] += 1
            row["open_unrealized_est"] += trade.allocated_unrealized_est or 0.0
        if trade.decision_rank is not None:
            row["decision_ranks"].append(trade.decision_rank)
    return out


def _entry_delta_rows(base_module: str, off: list[TradeRow], top20: list[TradeRow]) -> list[dict[str, str]]:
    off_by_entry = _entry_aggregate(off)
    top_by_entry = _entry_aggregate(top20)
    rows: list[dict[str, str]] = []
    for symbol, entry_date in sorted(set(off_by_entry) | set(top_by_entry)):
        off_row = off_by_entry.get((symbol, entry_date), {})
        top_row = top_by_entry.get((symbol, entry_date), {})
        off_entries = int(off_row.get("entries", 0))
        top_entries = int(top_row.get("entries", 0))
        relation = "shared"
        if off_entries and not top_entries:
            relation = "removed_by_top20"
        elif top_entries and not off_entries:
            relation = "added_by_top20"
        rows.append(
            {
                "base_module": base_module,
                "symbol": symbol,
                "entry_date": entry_date,
                "relation": relation,
                "off_entries": str(off_entries),
                "top20_entries": str(top_entries),
                "off_closed_pnl": f"{float(off_row.get('closed_pnl', 0.0)):.2f}",
                "top20_closed_pnl": f"{float(top_row.get('closed_pnl', 0.0)):.2f}",
                "delta_closed_pnl": f"{float(top_row.get('closed_pnl', 0.0)) - float(off_row.get('closed_pnl', 0.0)):.2f}",
                "off_open_lots": str(int(off_row.get("open", 0))),
                "top20_open_lots": str(int(top_row.get("open", 0))),
                "off_open_unrealized_est": f"{float(off_row.get('open_unrealized_est', 0.0)):.2f}",
                "top20_open_unrealized_est": f"{float(top_row.get('open_unrealized_est', 0.0)):.2f}",
                "delta_open_unrealized_est": f"{float(top_row.get('open_unrealized_est', 0.0)) - float(off_row.get('open_unrealized_est', 0.0)):.2f}",
                "off_avg_rank": _mean(off_row.get("decision_ranks", [])),
                "top20_avg_rank": _mean(top_row.get("decision_ranks", [])),
                "top20_avg_mfe_pct": _mean(top_row.get("mfe_pcts", [])),
                "top20_avg_mae_pct": _mean(top_row.get("mae_pcts", [])),
            }
        )
    return rows


def _rank_bucket(rank: float | None) -> str:
    if rank is None:
        return "missing"
    if rank <= 10:
        return "001_010"
    if rank <= 20:
        return "011_020"
    if rank <= 50:
        return "021_050"
    return "gt_050"


def _rank_bucket_rows(trades_by_variant: dict[str, list[TradeRow]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, str, str], list[TradeRow]] = defaultdict(list)
    for trades in trades_by_variant.values():
        for trade in trades:
            grouped[(trade.variant_id, trade.base_module, trade.scanner_setting, _rank_bucket(trade.decision_rank))].append(trade)
    rows: list[dict[str, str]] = []
    for (variant_id, base_module, scanner_setting, bucket), trades in sorted(grouped.items()):
        closed = [trade for trade in trades if trade.status == "closed"]
        open_trades = [trade for trade in trades if trade.status == "open"]
        rows.append(
            {
                "variant_id": variant_id,
                "base_module": base_module,
                "scanner_setting": scanner_setting,
                "decision_rank_bucket": bucket,
                "entries": str(len(trades)),
                "closed_trades": str(len(closed)),
                "open_lots": str(len(open_trades)),
                "closed_pnl": f"{sum(trade.closed_pnl or 0.0 for trade in closed):.2f}",
                "open_unrealized_est": f"{sum(trade.allocated_unrealized_est or 0.0 for trade in open_trades):.2f}",
                "avg_mfe_pct": _mean([trade.mfe_pct for trade in closed]),
                "avg_mae_pct": _mean([trade.mae_pct for trade in closed]),
            }
        )
    return rows


def _trade_dict(trade: TradeRow) -> dict[str, str]:
    return {
        "variant_id": trade.variant_id,
        "base_module": trade.base_module,
        "scanner_setting": trade.scanner_setting,
        "symbol": trade.symbol,
        "entry_order_id": str(trade.entry_order_id),
        "entry_time": trade.entry_time,
        "entry_date": trade.entry_date,
        "entry_price": f"{trade.entry_price:.6f}",
        "quantity": f"{trade.quantity:.6f}",
        "entry_cost": f"{trade.entry_cost:.2f}",
        "status": trade.status,
        "exit_order_id": trade.exit_order_id,
        "exit_time": trade.exit_time,
        "exit_date": trade.exit_date,
        "exit_price": _fmt(trade.exit_price, 6),
        "closed_pnl": _fmt2(trade.closed_pnl),
        "total_fees": _fmt2(trade.total_fees),
        "mae_abs": _fmt2(trade.mae_abs),
        "mfe_abs": _fmt2(trade.mfe_abs),
        "mae_pct": _fmt(trade.mae_pct),
        "mfe_pct": _fmt(trade.mfe_pct),
        "giveback_from_peak_pct": _fmt(trade.giveback_from_peak_pct),
        "duration_days": _fmt(trade.duration_days),
        "exit_reason": trade.exit_reason,
        "decision_rank": _fmt(trade.decision_rank),
        "decision_gap": _fmt(trade.decision_gap),
        "decision_vol": _fmt(trade.decision_vol),
        "decision_tdist": _fmt(trade.decision_tdist),
        "allocated_unrealized_est": _fmt2(trade.allocated_unrealized_est),
        "age_days_to_fy_end": "" if trade.age_days_to_fy_end is None else str(trade.age_days_to_fy_end),
    }


def _open_lot_dict(trade: TradeRow) -> dict[str, str]:
    row = _trade_dict(trade)
    return {key: row[key] for key in OPEN_LOT_COLUMNS}


def _exit_event_dict(event: ExitEvent) -> dict[str, str]:
    return {
        "variant_id": event.variant_id,
        "date": event.date,
        "symbol": event.symbol,
        "event": event.event,
        "module": event.module,
        "reason": event.reason,
        "days_held": event.days_held,
        "pnl": _fmt2(event.pnl),
        "return_pct": _fmt(event.return_pct),
        "mfe_pct": _fmt(event.mfe_pct),
        "mae_pct": _fmt(event.mae_pct),
        "giveback_from_peak_pct": _fmt(event.giveback_from_peak_pct),
        "raw": event.raw,
    }


VARIANT_COLUMNS = [
    "variant_id", "base_module", "scanner_setting", "ret_pct", "dd_pct", "orders",
    "summary_realized_net", "summary_unrealized", "buy_entries", "closed_trades", "open_lots",
    "closed_pnl_sum", "allocated_open_unrealized_est", "avg_mfe_pct", "avg_mae_pct",
    "avg_giveback_pct", "avg_duration_days", "avg_decision_rank", "exit_reason_counts",
    "worst_closed_symbol", "worst_closed_pnl", "worst_open_symbol", "worst_open_unrealized_est",
    "open_symbols",
]
SYMBOL_DELTA_COLUMNS = [
    "base_module", "symbol", "relation", "off_entries", "top20_entries", "delta_entries",
    "off_closed_pnl", "top20_closed_pnl", "delta_closed_pnl", "off_open_lots", "top20_open_lots",
    "off_open_unrealized_est", "top20_open_unrealized_est", "delta_open_unrealized_est",
    "off_avg_rank", "top20_avg_rank", "top20_avg_mfe_pct", "top20_avg_mae_pct", "top20_exit_reasons",
]
ENTRY_DELTA_COLUMNS = [
    "base_module", "symbol", "entry_date", "relation", "off_entries", "top20_entries",
    "off_closed_pnl", "top20_closed_pnl", "delta_closed_pnl", "off_open_lots", "top20_open_lots",
    "off_open_unrealized_est", "top20_open_unrealized_est", "delta_open_unrealized_est",
    "off_avg_rank", "top20_avg_rank", "top20_avg_mfe_pct", "top20_avg_mae_pct",
]
RANK_BUCKET_COLUMNS = [
    "variant_id", "base_module", "scanner_setting", "decision_rank_bucket", "entries",
    "closed_trades", "open_lots", "closed_pnl", "open_unrealized_est", "avg_mfe_pct",
    "avg_mae_pct",
]
TRADE_COLUMNS = [
    "variant_id", "base_module", "scanner_setting", "symbol", "entry_order_id", "entry_time",
    "entry_date", "entry_price", "quantity", "entry_cost", "status", "exit_order_id", "exit_time",
    "exit_date", "exit_price", "closed_pnl", "total_fees", "mae_abs", "mfe_abs", "mae_pct",
    "mfe_pct", "giveback_from_peak_pct", "duration_days", "exit_reason", "decision_rank",
    "decision_gap", "decision_vol", "decision_tdist", "allocated_unrealized_est",
    "age_days_to_fy_end",
]
OPEN_LOT_COLUMNS = [
    "variant_id", "base_module", "scanner_setting", "symbol", "entry_order_id", "entry_time",
    "entry_date", "entry_price", "quantity", "entry_cost", "status", "decision_rank",
    "allocated_unrealized_est", "age_days_to_fy_end",
]
EXIT_EVENT_COLUMNS = [
    "variant_id", "date", "symbol", "event", "module", "reason", "days_held", "pnl",
    "return_pct", "mfe_pct", "mae_pct", "giveback_from_peak_pct", "raw",
]


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _readout_lines(
    variant_rows: list[dict[str, str]],
    symbol_delta_rows: list[dict[str, str]],
    entry_delta_rows: list[dict[str, str]],
    open_rows: list[dict[str, str]],
) -> list[str]:
    top20_rows = [row for row in variant_rows if row["scanner_setting"] == "top20"]
    lines = [
        "- `top20` is the only scanner setting analyzed here; each row is compared with its scanner-off control.",
        "- Per-symbol open PnL is an allocation estimate from each variant's aggregate LEAN `Unrealized` statistic, proportional to open lot cost. Treat it as a drag locator, not exact accounting.",
        "- Current order tags do not include LambdaMART scanner score/rank. Rank-bucket diagnostics use the existing `decision_rank` tag, not the learned scanner score.",
    ]
    for row in sorted(top20_rows, key=lambda item: item["base_module"]):
        lines.append(
            f"- `{row['variant_id']}`: realized `{row['summary_realized_net']}`, "
            f"unrealized `{row['summary_unrealized']}`, open lots `{row['open_lots']}`, "
            f"worst allocated open `{row['worst_open_symbol']} {row['worst_open_unrealized_est']}`."
        )
    removed_helped = [
        row for row in symbol_delta_rows
        if row["relation"] == "removed_by_top20"
        and (_float(row["off_closed_pnl"]) + _float(row["off_open_unrealized_est"])) < 0
    ]
    added_hurt = [
        row for row in symbol_delta_rows
        if row["relation"] == "added_by_top20"
        and (_float(row["top20_closed_pnl"]) + _float(row["top20_open_unrealized_est"])) < 0
    ]
    retained_open_drag = [
        row for row in symbol_delta_rows
        if row["relation"] == "shared" and _float(row["top20_open_unrealized_est"]) < 0
    ]
    lines.append(
        f"- Removed symbols with negative off-control contribution: `{len(removed_helped)}`. "
        f"Added symbols with negative top20 contribution: `{len(added_hurt)}`. "
        f"Shared symbols with negative top20 open allocation: `{len(retained_open_drag)}`."
    )
    removed_entries = [row for row in entry_delta_rows if row["relation"] == "removed_by_top20"]
    added_entries = [row for row in entry_delta_rows if row["relation"] == "added_by_top20"]
    lines.append(
        f"- Entry-date changes are material: `{len(removed_entries)}` off-control entries are absent in top20, "
        f"and `{len(added_entries)}` top20 entries are absent in scanner-off controls."
    )
    if open_rows:
        oldest = max(open_rows, key=lambda row: int(row["age_days_to_fy_end"] or 0))
        lines.append(
            f"- Oldest open lot at year-end: `{oldest['variant_id']} {oldest['symbol']}` "
            f"from `{oldest['entry_date']}`, age `{oldest['age_days_to_fy_end']}` days."
        )
    return lines


def _write_markdown(
    path: Path,
    *,
    variant_rows: list[dict[str, str]],
    symbol_delta_rows: list[dict[str, str]],
    entry_delta_rows: list[dict[str, str]],
    open_rows: list[dict[str, str]],
) -> None:
    lines = [
        "# #455 Top20 Realized PnL Diagnostics",
        "",
        "## Read",
        "",
        *_readout_lines(variant_rows, symbol_delta_rows, entry_delta_rows, open_rows),
        "",
        "## Variant Summary",
        "",
        "| variant | ret % | DD % | realized | unrealized | open lots | worst open est | exit reasons |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in sorted(variant_rows, key=lambda item: (item["base_module"], item["scanner_setting"])):
        worst_open = f"{row['worst_open_symbol']} {row['worst_open_unrealized_est']}".strip()
        lines.append(
            f"| `{row['variant_id']}` | {row['ret_pct']} | {row['dd_pct']} | "
            f"{row['summary_realized_net']} | {row['summary_unrealized']} | {row['open_lots']} | "
            f"{worst_open} | {row['exit_reason_counts']} |"
        )
    lines.extend(
        [
            "",
            "## Largest Negative Top20 Open Allocations",
            "",
            "| variant | symbol | entry date | age days | rank | allocation est |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in sorted(open_rows, key=lambda item: _float(item["allocated_unrealized_est"]))[:15]:
        lines.append(
            f"| `{row['variant_id']}` | {row['symbol']} | {row['entry_date']} | "
            f"{row['age_days_to_fy_end']} | {row['decision_rank']} | {row['allocated_unrealized_est']} |"
        )
    lines.extend(
        [
            "",
            "## Largest Entry-Date Deltas",
            "",
            "| base | symbol | date | relation | delta closed | delta open est | off entries | top20 entries |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    ranked_entry_delta = sorted(
        entry_delta_rows,
        key=lambda row: abs(_float(row["delta_closed_pnl"])) + abs(_float(row["delta_open_unrealized_est"])),
        reverse=True,
    )
    for row in ranked_entry_delta[:20]:
        base = row["base_module"].replace("strategies.", "")
        lines.append(
            f"| `{base}` | {row['symbol']} | {row['entry_date']} | {row['relation']} | "
            f"{row['delta_closed_pnl']} | {row['delta_open_unrealized_est']} | "
            f"{row['off_entries']} | {row['top20_entries']} |"
        )
    lines.extend(
        [
            "",
            "## Largest Symbol Deltas",
            "",
            "| base | symbol | relation | delta closed | delta open est | off entries | top20 entries |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    ranked_delta = sorted(
        symbol_delta_rows,
        key=lambda row: abs(_float(row["delta_closed_pnl"])) + abs(_float(row["delta_open_unrealized_est"])),
        reverse=True,
    )
    for row in ranked_delta[:20]:
        base = row["base_module"].replace("strategies.", "")
        lines.append(
            f"| `{base}` | {row['symbol']} | {row['relation']} | {row['delta_closed_pnl']} | "
            f"{row['delta_open_unrealized_est']} | {row['off_entries']} | {row['top20_entries']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_readme(path: Path) -> None:
    path.write_text(
        "# top20_realized_pnl_diagnostics_455/\n\n"
        "Small diagnostics generated for #455 from committed summary rows and local raw LEAN artifacts.\n"
        "Contains CSV/Markdown summaries only; raw backtest artifacts stay under `sweeps/runs`.\n",
        encoding="utf-8",
    )


def run(report_dir: Path, source_root: Path, output_dir: Path) -> None:
    summary_rows = _load_summary(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_readme(output_dir / "README.md")

    trades_by_variant: dict[str, list[TradeRow]] = {}
    events: list[ExitEvent] = []
    for row in summary_rows:
        trades, exit_events = extract_trades(row, source_root=source_root)
        trades_by_variant[row["variant_id"]] = trades
        events.extend(exit_events)

    variant_rows = [_variant_row(row, trades_by_variant[row["variant_id"]]) for row in summary_rows]
    symbol_delta_rows: list[dict[str, str]] = []
    entry_delta_rows: list[dict[str, str]] = []
    for base_module in sorted({row["base_module"] for row in summary_rows}):
        off_variant = next(
            row["variant_id"]
            for row in summary_rows
            if row["base_module"] == base_module and row["scanner_setting"] == "off"
        )
        top20_variant = next(
            row["variant_id"]
            for row in summary_rows
            if row["base_module"] == base_module and row["scanner_setting"] == "top20"
        )
        symbol_delta_rows.extend(
            _symbol_delta_rows(
                base_module,
                trades_by_variant[off_variant],
                trades_by_variant[top20_variant],
            )
        )
        entry_delta_rows.extend(
            _entry_delta_rows(
                base_module,
                trades_by_variant[off_variant],
                trades_by_variant[top20_variant],
            )
        )

    trade_rows = [_trade_dict(trade) for rows in trades_by_variant.values() for trade in rows]
    open_rows = [_open_lot_dict(trade) for rows in trades_by_variant.values() for trade in rows if trade.status == "open"]
    exit_rows = [_exit_event_dict(event) for event in events]
    rank_bucket_rows = _rank_bucket_rows(trades_by_variant)

    _write_csv(output_dir / "variant_diagnostics.csv", variant_rows, VARIANT_COLUMNS)
    _write_csv(output_dir / "symbol_delta_top20_vs_off.csv", symbol_delta_rows, SYMBOL_DELTA_COLUMNS)
    _write_csv(output_dir / "entry_delta_top20_vs_off.csv", entry_delta_rows, ENTRY_DELTA_COLUMNS)
    _write_csv(output_dir / "decision_rank_buckets.csv", rank_bucket_rows, RANK_BUCKET_COLUMNS)
    _write_csv(output_dir / "symbol_trade_diagnostics.csv", trade_rows, TRADE_COLUMNS)
    _write_csv(
        output_dir / "open_lot_unrealized_allocation.csv",
        sorted(open_rows, key=lambda row: _float(row["allocated_unrealized_est"])),
        OPEN_LOT_COLUMNS,
    )
    _write_csv(output_dir / "exit_events.csv", exit_rows, EXIT_EVENT_COLUMNS)
    _write_markdown(
        output_dir / "diagnostics.md",
        variant_rows=variant_rows,
        symbol_delta_rows=symbol_delta_rows,
        entry_delta_rows=entry_delta_rows,
        open_rows=open_rows,
    )
    manifest = {
        "report_dir": str(report_dir),
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "variants": sorted(trades_by_variant),
        "raw_artifacts_committed": False,
        "open_pnl_note": "Per-symbol open PnL is allocated from aggregate unrealized by open lot cost.",
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {output_dir}")


def main() -> None:
    args = _args()
    run(args.report_dir.resolve(), args.source_root.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
