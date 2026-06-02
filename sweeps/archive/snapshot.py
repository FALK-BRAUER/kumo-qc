"""`persist_run(...)` — the durable per-run archive writer (#276b, results-archive-design.md).

THE #1-RISK component. Cloud BTs PURGE; logs/ObjectStore/ChartEmit are unretrievable. The ONLY
durable channel is `/backtests/orders/read` (per-order fills + the entry-order `tag`). This module
grabs that AT RUN-TIME (before purge) and writes a durable per-run artifact:

    results/archive/<config_hash>/<backtest_id>/
        result.json        full config + provenance + ALL QC statistics + 3-state status
        trades.jsonl.gz     one closed trade per line — the learn-substrate (feeds the #303 mine)

backtest_id is REQUIRED and is the directory key: it GUARANTEES per-run uniqueness, killing the
resolution-collision that let runs overwrite each other / evaporate.

FAIL-LOUD contract (the crux — mirrors assert_cloud_clean):
  * the injected `/orders/read` fetch errors        → retry w/ exponential backoff, then RAISE
  * status is not a valid RunStatus                  → RAISE
  * a trade row fails JSON-Schema validation         → RAISE (the schema is the doc + drift guard)
  * empty trades while statistics Total Orders > 0    → RAISE (EmptyTradesError, the silent-miss)
  * a CRASHED run captures whatever is retrievable    → params/stats even if trades empty; the
                                                         CALLER hard-excludes non-CLEAN from learning
Atomic + idempotent: every file is written to a temp path then os.replace()'d into place, so a
mid-write crash leaves no partial file and re-running persist_run for the same bt_id is safe.

Decoupling: the config is passed PRE-SERIALIZED (a plain dict) so this module never imports engine
code — consistent with the phase-agnostic sweeps/types contract. The `/orders/read` fetch AND the
write-destination root are INJECTED so tests mock them (ZERO real QC / LEAN). NO hardcoded secrets.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs

import jsonschema


# --------------------------------------------------------------------------- #
# Failure modes — fail-loud, never a silent partial (CLAUDE.md data-integrity).
# --------------------------------------------------------------------------- #
class ArchiveError(Exception):
    """Base class for snapshotter failures. The snapshotter RAISES rather than writing a
    silent/partial artifact — a run whose archive can't be trusted is worse than no archive
    (the exact failure this component exists to fix)."""


class OrdersFetchError(ArchiveError):
    """The injected `/orders/read` fetch failed after the retry budget was exhausted. The run
    detail is unrecoverable from this channel — fail loud, do NOT write an empty trades file as
    if the run had no trades."""


class EmptyTradesError(ArchiveError):
    """The orders fetch returned zero closed trades while the statistics report Total Orders > 0
    — the silent-miss (a parse/pairing bug or a purge race would evaporate the run while looking
    'successful'). This is the single most important fail-loud check in the component."""


class SchemaValidationError(ArchiveError):
    """A trades.jsonl line failed JSON-Schema validation BEFORE write. The schema IS the doc and
    the drift guard — a row that does not conform is a corrupt learn-substrate row; refuse it."""


# --------------------------------------------------------------------------- #
# 3-state run status. The caller hard-excludes anything != COMPLETED_CLEAN from
# the learn-substrate and from sweep selection.
# --------------------------------------------------------------------------- #
class RunStatus(str, Enum):
    """The run's terminal disposition.

    COMPLETED_CLEAN     — passed assert_cloud_clean / local parity: a real, learnable result.
    COMPLETED_DEGRADED  — ran to completion but degraded (e.g. data-outage mirage / flat); the
                          archive records it (provenance survives) but the caller EXCLUDES it.
    CRASHED             — runtime/wiring error; capture whatever is retrievable (params + stats
                          even if trades are empty), excluded from learning.
    """

    COMPLETED_CLEAN = "COMPLETED_CLEAN"
    COMPLETED_DEGRADED = "COMPLETED_DEGRADED"
    CRASHED = "CRASHED"


# --------------------------------------------------------------------------- #
# Per-trade context quality (HQ refinement) — tiered, NOT uniform null.
# --------------------------------------------------------------------------- #
class ContextStatus(str, Enum):
    """Per-row decision-context quality, so the mine FILTERS instead of trusting a contextless row.

    OK            — the CORE learn-substrate is present (decision_score AND decision_cond).
    CORE_MISSING  — the entry order carried no tag, or the tag lacked decision_score/decision_cond.
                    The row is still recorded (the execution fill is real) but flagged SUSPECT so
                    the consumer excludes it from the learn set. Optional fields missing is NOT
                    core-missing — those are plain null.
    """

    OK = "OK"
    CORE_MISSING = "CORE_MISSING"


# --------------------------------------------------------------------------- #
# The injected `/orders/read` fetch.
# --------------------------------------------------------------------------- #
@runtime_checkable
class OrdersFetch(Protocol):
    """`(backtest_id) -> list[order-dict]` — the injected `/backtests/orders/read` pull.

    Prod wiring passes a closure over scripts.qc_v2_cloud.orders (paginated, fail-loud) for cloud,
    or a reader over the local LEAN `*-order-events.json` for local. Unit tests pass a MOCK
    returning a fixture order list — ZERO real QC. The callable MAY raise on a transient API error;
    persist_run retries it with exponential backoff before giving up (OrdersFetchError)."""

    def __call__(self, backtest_id: str) -> Sequence[Mapping[str, Any]]: ...


# --------------------------------------------------------------------------- #
# Schemas (the doc + the drift guard). Bump *_SCHEMA_VERSION on ANY field /
# bit-order change so the mine can detect and gate on substrate drift.
# --------------------------------------------------------------------------- #
TRADE_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 1

_COND_BITS = 8  # the 8 BCT conditions, stable bit order (cond_0 .. cond_7)

TRADE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "results-archive closed-trade row",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "context_status",
        # execution_* (from the FILLS)
        "symbol", "entry_dt", "entry_px", "exit_dt", "exit_px",
        "qty", "side", "pnl", "ret", "duration_sec", "exit_reason",
        # decision_* (from the entry order TAG)
        "decision_score", "decision_cond",
        "decision_gap", "decision_vol", "decision_tdist", "decision_rank",
        # excursion (follow-on emit) — null until the exit-tag path lands
        "mfe", "mae",
    ]
    + [f"cond_{i}" for i in range(_COND_BITS)],
    "properties": {
        "schema_version": {"type": "integer", "const": TRADE_SCHEMA_VERSION},
        "context_status": {"enum": [ContextStatus.OK.value, ContextStatus.CORE_MISSING.value]},
        # --- execution (always present, from real fills) ---
        "symbol": {"type": "string", "minLength": 1},
        "entry_dt": {"type": "string"},        # ISO 8601
        "entry_px": {"type": "number"},
        "exit_dt": {"type": "string"},
        "exit_px": {"type": "number"},
        "qty": {"type": "number"},             # absolute share count of the paired lot
        "side": {"enum": ["long", "short"]},
        "pnl": {"type": "number"},
        "ret": {"type": "number"},
        "duration_sec": {"type": "number", "minimum": 0},
        "exit_reason": {"type": ["string", "null"]},
        # --- decision context (from the entry tag; typed; null if the field was absent) ---
        "decision_score": {"type": ["integer", "null"]},
        "decision_cond": {"type": ["string", "null"], "pattern": f"^[01]{{{_COND_BITS}}}$"},
        "decision_gap": {"type": ["number", "null"]},
        "decision_vol": {"type": ["number", "null"]},
        "decision_tdist": {"type": ["number", "null"]},
        "decision_rank": {"type": ["integer", "null"]},
        # --- excursion (null until the strategy exit-tag emit follow-on) ---
        "mfe": {"type": ["number", "null"]},
        "mae": {"type": ["number", "null"]},
        # --- the 8 BCT conditions expanded to booleans (null when decision_cond absent) ---
        **{f"cond_{i}": {"type": ["boolean", "null"]} for i in range(_COND_BITS)},
    },
}

# Pattern allowing null: the "decision_cond" pattern above only applies when the value is a
# string; jsonschema does not apply `pattern` to a null, so the ["string","null"] union is safe.

_TRADE_VALIDATOR = jsonschema.Draft202012Validator(TRADE_SCHEMA)


# --------------------------------------------------------------------------- #
# Tag parsing — urldecode + TYPE-CAST so the mine gets clean types.
# --------------------------------------------------------------------------- #
def _parse_entry_tag(tag: str | None) -> dict[str, Any]:
    """Parse the entry-order TAG (urlencoded, from lean_entry._build_entry_tag) into typed
    decision_* fields. Missing fields → None (NEVER faked). A piece that can't be cleanly cast is
    treated as absent (None) rather than banked as garbage.

    Tag shape (urlencode of a subset of):
        decision_score=8 decision_cond=11110111 decision_gap=0.0340 decision_vol=1.612
        decision_tdist=0.0081 decision_rank=12
    """
    out: dict[str, Any] = {
        "decision_score": None,
        "decision_cond": None,
        "decision_gap": None,
        "decision_vol": None,
        "decision_tdist": None,
        "decision_rank": None,
    }
    if not tag:
        return out
    # parse_qs already urldecodes; keep_blank_values False so empty pieces drop out.
    parsed = parse_qs(tag, keep_blank_values=False)

    def _first(key: str) -> str | None:
        vals = parsed.get(key)
        return vals[0] if vals else None

    def _as_int(key: str) -> int | None:
        raw = _first(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    def _as_float(key: str) -> float | None:
        raw = _first(key)
        if raw is None:
            return None
        try:
            v = float(raw)
        except (ValueError, TypeError):
            return None
        return v if math.isfinite(v) else None

    out["decision_score"] = _as_int("decision_score")
    out["decision_gap"] = _as_float("decision_gap")
    out["decision_vol"] = _as_float("decision_vol")
    out["decision_tdist"] = _as_float("decision_tdist")
    out["decision_rank"] = _as_int("decision_rank")

    cond = _first("decision_cond")
    if cond is not None and len(cond) == _COND_BITS and set(cond) <= {"0", "1"}:
        out["decision_cond"] = cond
    # A malformed cond (wrong length / non-binary) is NOT banked — treated as absent.
    return out


def _expand_cond(cond: str | None) -> dict[str, bool | None]:
    """decision_cond "11110111" → cond_0..cond_7 booleans. None when the cond is absent (the row is
    flagged CORE_MISSING, not silently all-False)."""
    if cond is None:
        return {f"cond_{i}": None for i in range(_COND_BITS)}
    return {f"cond_{i}": (cond[i] == "1") for i in range(_COND_BITS)}


# --------------------------------------------------------------------------- #
# Order / fill helpers — the QC /orders/read shape.
# --------------------------------------------------------------------------- #
# QC order status: 3 == Filled, 7 == Liquidated (delisting). Both are real fills with a fill price.
_FILLED_STATUSES: frozenset[Any] = frozenset({3, 7, "filled", "Filled"})
# QC order type codes (for a human-readable exit_reason fallback when the tag is empty).
_ORDER_TYPE_NAMES = {0: "market", 1: "limit", 2: "stop_market", 3: "stop_limit", 4: "stop_market"}


def _sym_value(order: Mapping[str, Any]) -> str | None:
    sym = order.get("symbol")
    if isinstance(sym, Mapping):
        v = sym.get("value")
        return str(v) if v else None
    if isinstance(sym, str) and sym:
        return sym
    sv = order.get("symbolValue")
    return str(sv) if sv else None


def _fill_dt(order: Mapping[str, Any]) -> datetime:
    """Fill timestamp. Prefer lastFillTime (ISO or unix), fall back to time. UTC-normalised."""
    raw = order.get("lastFillTime") or order.get("time")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    s = str(raw).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fill_price(order: Mapping[str, Any]) -> float:
    """Fill price. Prefer the order-level `price` (the avg fill); fall back to the filled event's
    fillPrice. FAIL-LOUD: a filled order with no determinable non-zero price is corrupt data — raise
    rather than bank a 0 that would yield nonsense pnl/ret (or a div-by-zero on entry notional)."""
    p = order.get("price")
    if p is not None and float(p) != 0.0:
        return float(p)
    for ev in order.get("events") or []:
        if str(ev.get("status")).lower() == "filled" and ev.get("fillPrice"):
            fp = float(ev["fillPrice"])
            if fp != 0.0:
                return fp
    raise ArchiveError(
        f"filled order id={order.get('id', 'N/A')} sym={_sym_value(order)} has no non-zero fill "
        f"price — corrupt data, refusing to bank a 0-price trade (fail loud, #276b)"
    )


def _is_filled(order: Mapping[str, Any]) -> bool:
    return order.get("status") in _FILLED_STATUSES


def _exit_reason(order: Mapping[str, Any]) -> str | None:
    """exit_reason from the EXIT order: its tag if present (e.g. 'Liquidate from delisting' or a
    stop-tag), else the order-type name. None when nothing informative."""
    tag = order.get("tag")
    if tag:
        return str(tag)
    t = order.get("type")
    if t is not None:
        return _ORDER_TYPE_NAMES.get(t, f"type_{t}")
    return None


# --------------------------------------------------------------------------- #
# Trade pairing — FIFO entry/exit per symbol from the fills.
# --------------------------------------------------------------------------- #
def _pair_trades(orders: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Pair entry+exit fills per symbol into closed trades (FIFO lot matching).

    A BUY opens long lots (a SELL while flat opens a short lot); the opposite-side fill closes the
    oldest open lot(s). Each closed trade records the OPENING fill's tag as its decision context
    (the conditions the entry SAW) and the CLOSING fill for exit_dt/exit_px/exit_reason. Partial
    fills split lots so qty/pnl stay exact. Trades still open at end of data are NOT emitted (no
    exit → not a closed trade; the QC closedTrades summary agrees)."""
    # Chronological, deterministic: sort by fill time, then order id for tie-break.
    fills = [o for o in orders if _is_filled(o) and _sym_value(o) and float(o.get("quantity") or 0) != 0]
    fills.sort(key=lambda o: (_fill_dt(o), o.get("id", 0)))

    # per-symbol open lots: list of dicts {qty_remaining(+long/-short), px, dt, tag}
    open_lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []

    for o in fills:
        sym = _sym_value(o)
        assert sym is not None  # filtered above
        qty = float(o["quantity"])
        px = _fill_price(o)
        dt = _fill_dt(o)
        lots = open_lots.setdefault(sym, [])

        # Net the incoming fill against opposite-side open lots (FIFO).
        while qty != 0 and lots and (lots[0]["qty"] > 0) != (qty > 0):
            lot = lots[0]
            close_qty = min(abs(lot["qty"]), abs(qty))
            side = "long" if lot["qty"] > 0 else "short"
            entry_px = lot["px"]
            sign = 1.0 if side == "long" else -1.0
            pnl = (px - entry_px) * close_qty * sign
            notional = entry_px * close_qty
            ret = (pnl / notional) if notional else 0.0
            duration = (dt - lot["dt"]).total_seconds()
            closed.append(
                {
                    "symbol": sym,
                    "entry_dt": lot["dt"],
                    "entry_px": entry_px,
                    "exit_dt": dt,
                    "exit_px": px,
                    "qty": close_qty,
                    "side": side,
                    "pnl": pnl,
                    "ret": ret,
                    "duration_sec": max(0.0, duration),
                    "exit_reason": _exit_reason(o),
                    "entry_tag": lot["tag"],
                }
            )
            # Move BOTH toward zero by close_qty: the lot is on `side`, the incoming fill is the
            # opposite side, so each shrinks by close_qty toward 0 (signs are opposite).
            lot["qty"] -= sign * close_qty           # long lot shrinks (-), short lot grows (+) → toward 0
            qty -= -sign * close_qty                 # incoming is opposite-sign → also toward 0
            if abs(lot["qty"]) < 1e-9:
                lots.pop(0)

        # Any residual incoming quantity opens a new lot on its own side.
        if abs(qty) > 1e-9:
            lots.append({"qty": qty, "px": px, "dt": dt, "tag": o.get("tag")})

    return closed


def _trade_to_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    """A paired trade → the schema-validated JSONL row (typed decision_* + cond bits + flag)."""
    decision = _parse_entry_tag(trade.get("entry_tag"))
    cond_bits = _expand_cond(decision["decision_cond"])
    core_present = decision["decision_score"] is not None and decision["decision_cond"] is not None
    row: dict[str, Any] = {
        "schema_version": TRADE_SCHEMA_VERSION,
        "context_status": (ContextStatus.OK if core_present else ContextStatus.CORE_MISSING).value,
        # execution
        "symbol": trade["symbol"],
        "entry_dt": _iso(trade["entry_dt"]),
        "entry_px": float(trade["entry_px"]),
        "exit_dt": _iso(trade["exit_dt"]),
        "exit_px": float(trade["exit_px"]),
        "qty": float(trade["qty"]),
        "side": trade["side"],
        "pnl": float(trade["pnl"]),
        "ret": float(trade["ret"]),
        "duration_sec": float(trade["duration_sec"]),
        "exit_reason": trade["exit_reason"],
        # decision (typed; null if absent)
        **decision,
        # excursion — follow-on emit; null today (never block)
        "mfe": None,
        "mae": None,
        # cond bits
        **cond_bits,
    }
    return row


def _iso(dt: Any) -> str:
    if isinstance(dt, datetime):
        d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return d.isoformat()
    return str(dt)


# --------------------------------------------------------------------------- #
# Statistics helper — Total Orders for the silent-miss guard.
# --------------------------------------------------------------------------- #
def _total_orders(statistics: Mapping[str, Any]) -> int | None:
    raw = (statistics or {}).get("Total Orders")
    if raw is None:
        return None
    try:
        return int(str(raw).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Atomic write helpers — temp file in the SAME dir + os.replace (atomic rename).
# --------------------------------------------------------------------------- #
def _atomic_write_bytes(dest: Path, payload: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=f".{dest.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, dest)  # atomic on POSIX — no partial dest ever observed
    except BaseException:
        # Clean the temp so a mid-write failure leaves NO partial artifact.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _gzip_bytes(text: str) -> bytes:
    # mtime=0 → deterministic gzip (idempotent re-runs produce byte-identical output).
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(text.encode("utf-8"))
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# The public entry point.
# --------------------------------------------------------------------------- #
def persist_run(
    *,
    config: Mapping[str, Any],
    config_hash: str,
    backtest_id: str,
    status: RunStatus,
    statistics: Mapping[str, Any],
    commit: str,
    data_fingerprint: str,
    objective_version: str,
    timestamp: str,
    env: str,
    orders_fetch: OrdersFetch,
    dest_root: Path | str,
    fetch_retries: int = 3,
    fetch_backoff: float = 2.0,
) -> Path:
    """Write the durable per-run artifact; return the run directory.

    PATH: ``<dest_root>/<config_hash>/<backtest_id>/`` — backtest_id is the uniqueness key.

    Args (ALL injected — no secrets, no implicit clock, no real QC/LEAN reached here):
      config              pre-serialized StrategyConfig dict (name, version, phases{kind:impl+params},
                          config_hash). The caller serializes; this module never imports engine code.
      config_hash         the run's config digest (the first path segment + cross-check vs config).
      backtest_id         REQUIRED, non-empty — the QC backtestId (cloud) or LEAN bt dir id (local).
      status              the 3-state RunStatus. Non-CLEAN is archived (provenance survives) but the
                          CALLER hard-excludes it from the learn-substrate + sweep selection.
      statistics          the FULL QC statistics dict (the trio + everything) — stored verbatim.
      commit/data_fingerprint/objective_version   provenance pinning (CLAUDE.md: a result without
                          commit+config-hash+data-fingerprint is invalid).
      timestamp           caller-supplied ISO string — NOT computed here (no Date.now / determinism).
      env                 "local" | "cloud".
      orders_fetch        the injected `/orders/read` callable (retried w/ backoff; tests mock it).
      dest_root           the injected write root (tests pass tmp_path).
      fetch_retries       attempts for orders_fetch on a transient error (>=1).
      fetch_backoff       base seconds for exponential backoff (delay = backoff * 2**attempt).

    Fail-loud (RAISES, never a silent partial):
      * status not a RunStatus
      * empty backtest_id / config_hash
      * orders_fetch errors past the retry budget       → OrdersFetchError
      * a trade row fails schema validation               → SchemaValidationError
      * empty trades while Total Orders > 0 on a non-CRASHED run → EmptyTradesError (the silent-miss)

    CRASHED: orders_fetch is best-effort — if it fails or returns nothing, trades.jsonl.gz is written
    EMPTY (header-less, zero lines) and the EmptyTradesError guard is SKIPPED (a crash legitimately
    may have no trades). result.json still captures config + stats so provenance survives.

    Idempotent: both files are atomic-renamed; re-running for the same backtest_id overwrites cleanly.
    """
    if not isinstance(status, RunStatus):
        raise ArchiveError(f"status must be a RunStatus, got {status!r}")
    if not backtest_id:
        raise ArchiveError("backtest_id is REQUIRED (the uniqueness key) — refusing to archive")
    if not config_hash:
        raise ArchiveError("config_hash is REQUIRED — refusing to archive")
    if env not in ("local", "cloud"):
        raise ArchiveError(f"env must be 'local' or 'cloud', got {env!r}")

    run_dir = Path(dest_root) / config_hash / backtest_id
    crashed = status is RunStatus.CRASHED

    # 1. Fetch orders (retried). On CRASHED, a fetch failure is tolerated (best-effort capture).
    orders = _fetch_orders(orders_fetch, backtest_id, fetch_retries, fetch_backoff, crashed=crashed)

    # 2. Pair + serialize trades, validating EACH row before write.
    rows = [_trade_to_row(t) for t in _pair_trades(orders)]
    for row in rows:
        _validate_trade_row(row)

    # 3. The silent-miss guard (the crux): empty trades while stats say orders fired.
    total_orders = _total_orders(statistics)
    if not crashed and not rows and total_orders is not None and total_orders > 0:
        raise EmptyTradesError(
            f"0 closed trades parsed but statistics Total Orders={total_orders} (bt={backtest_id}, "
            f"status={status.value}) — the run would silently evaporate; fail loud (#276b silent-miss)"
        )

    # 4. Write trades.jsonl.gz (atomic, gzip-from-day-1, deterministic).
    jsonl = "".join(json.dumps(r, separators=(",", ":"), sort_keys=True) + "\n" for r in rows)
    _atomic_write_bytes(run_dir / "trades.jsonl.gz", _gzip_bytes(jsonl))

    # 5. Write result.json (atomic).
    result_doc = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "trade_schema_version": TRADE_SCHEMA_VERSION,
        "status": status.value,
        "backtest_id": backtest_id,
        "config_hash": config_hash,
        "config": dict(config),
        "commit": commit,
        "data_fingerprint": data_fingerprint,
        "objective_version": objective_version,
        "timestamp": timestamp,
        "env": env,
        "statistics": dict(statistics),
        "n_closed_trades": len(rows),
        "total_orders": total_orders,
    }
    _atomic_write_bytes(
        run_dir / "result.json",
        (json.dumps(result_doc, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return run_dir


def _fetch_orders(
    orders_fetch: OrdersFetch,
    backtest_id: str,
    retries: int,
    backoff: float,
    *,
    crashed: bool,
) -> list[Mapping[str, Any]]:
    """Call the injected fetch with exponential backoff. Past the budget: RAISE (clean/degraded)
    or return [] (crashed — best-effort capture, never block provenance on a dead channel)."""
    attempts = max(1, retries)
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            result = orders_fetch(backtest_id)
            return list(result or [])
        except Exception as exc:  # noqa: BLE001 — any fetch error is retried/loud
            last_exc = exc
            if attempt < attempts - 1 and backoff > 0:
                time.sleep(backoff * (2 ** attempt))
    if crashed:
        return []
    raise OrdersFetchError(
        f"/orders/read failed for bt={backtest_id} after {attempts} attempts: {last_exc}"
    ) from last_exc


def _validate_trade_row(row: Mapping[str, Any]) -> None:
    errors = sorted(_TRADE_VALIDATOR.iter_errors(row), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise SchemaValidationError(
            f"trade row failed schema (schema_version={TRADE_SCHEMA_VERSION}): "
            f"{first.message} at {list(first.path)}"
        )
