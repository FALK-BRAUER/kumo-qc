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

import jsonschema

# #archive ①: the SHARED tag schema — single source of truth for the decision_* keys + encode/decode.
# lean_entry._build_entry_tag (cloud) emits via the same module; parsing here uses the same decode →
# emit and parse cannot desync (the round-trip test is the contract guarantee).
from runtime.tag_schema import COND_BITS, expand_cond, parse_entry_tag


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
# The injected mark-to-market source for CENSORED (open-at-end) lots.
# --------------------------------------------------------------------------- #
@runtime_checkable
class M2MMark(Protocol):
    """`(symbol, end_of_data) -> (mark_price | None, source_label)` — the injected end-of-data mark.

    Resolves the per-symbol closing mark for a position still OPEN at the run's end-of-data, so a
    censored row carries a PROVISIONAL outcome instead of being dropped. Contract:

      * Returns a (price, source) tuple. price is None when no mark resolves; source is one of
        ``M2M_QC_NATIVE`` / ``M2M_LOCAL_PARQUET`` / ``M2M_UNAVAILABLE``.
      * When price is None, source MUST be ``M2M_UNAVAILABLE`` (the row records m2m_ret=null — the
        entry context still has learn value; the outcome is honestly unknown, NEVER faked).
      * Prod wiring PREFERS the QC-native end-of-data mark (same data vendor as the run, consistent
        with the run's reported return). NOTE: QC `/backtests/read` exposes only an AGGREGATE
        `runtimeStatistics.Unrealized` — NOT a per-symbol mark — so the cloud-native per-symbol path
        is only usable if a future channel (e.g. an end-of-data holdings chart) provides it; today
        the practical source is the LOCAL fallback below.
      * FALLBACK (``M2M_LOCAL_PARQUET``): the symbol's RAW/UNADJUSTED close at the LAST trading day
        <= end_of_data from local data. NEVER an ADJUSTED price (adjusted levels corrupt the mark —
        the split/dividend-factor trap) and NEVER "today" (always the run's end-of-data timestamp).

    `end_of_data` is the run's terminal timestamp (the END_DATE / last-data day), passed by the
    caller — NOT read from a clock here (determinism). Unit tests pass a MOCK — ZERO real LEAN/QC."""

    def __call__(self, symbol: str, end_of_data: datetime) -> tuple[float | None, str]: ...


# --------------------------------------------------------------------------- #
# Schemas (the doc + the drift guard). Bump *_SCHEMA_VERSION on ANY field /
# bit-order change so the mine can detect and gate on substrate drift.
# --------------------------------------------------------------------------- #
# Schema v2 (#276b-1): adds the CENSORED open-position row type. This strategy is
# cut-losers/let-winners → the CLOSED set is loser-biased BY CONSTRUCTION on EVERY run (a stop that
# never fires leaves the WINNERS open at end-of-data; the QC closedTrades summary — and v1 of this
# snapshotter — DROPPED them). A closed-only substrate teaches the #303 mine "these entry conditions
# → LOSS" which is FALSE: the SAME conditions produced the censored winners. So every row now carries
# `censored` (REQUIRED): false == a real closed trade (real exit), true == an open lot at end-of-data
# marked-to-market provisionally (`m2m_ret` / `m2m_source`, exit_reason "censored_open"). The mine
# gates on `schema_version` (v1 artifacts are censored-LESS) and reads `censored` to keep provisional
# (unrealized) outcomes distinct from realized ones — that weighting is the mine's job, not ours.
TRADE_SCHEMA_VERSION = 2
RESULT_SCHEMA_VERSION = 2  # v2 adds run_class (validation | substrate-generation | null); v1 lacks it

_COND_BITS = COND_BITS  # the 8 BCT conditions, stable bit order (cond_0 .. cond_7) — shared source

# Censored-row exit_reason sentinel — the mine keys on this to recognise a provisional (open) row.
CENSORED_EXIT_REASON = "censored_open"

# M2M provenance labels — qc_native (preferred, same vendor as the run), local_parquet (RAW /
# UNADJUSTED LEAN daily close at end-of-data; NEVER an adjusted price — the adjusted-price level
# trap), or unavailable (neither resolved → m2m_ret null, NEVER faked).
M2M_QC_NATIVE = "qc_native"
M2M_LOCAL_PARQUET = "local_parquet"
M2M_UNAVAILABLE = "unavailable"

TRADE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "results-archive trade row (closed OR censored-open)",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "context_status",
        # censored discriminator (v2) — REQUIRED on EVERY row (closed rows = false).
        "censored",
        # execution_* (from the FILLS). exit_dt/exit_px are null on a censored (open) row.
        "symbol", "entry_dt", "entry_px", "exit_dt", "exit_px",
        "qty", "side", "pnl", "ret", "duration_sec", "exit_reason",
        # decision_* (from the entry order TAG)
        "decision_score", "decision_cond",
        "decision_gap", "decision_vol", "decision_tdist", "decision_rank",
        # excursion (follow-on emit) — null until the exit-tag path lands
        "mfe", "mae",
        # m2m provenance (v2) — null/"unavailable" on a closed row (it has a real exit).
        "m2m_ret", "m2m_source",
    ]
    + [f"cond_{i}" for i in range(_COND_BITS)],
    "properties": {
        "schema_version": {"type": "integer", "const": TRADE_SCHEMA_VERSION},
        "context_status": {"enum": [ContextStatus.OK.value, ContextStatus.CORE_MISSING.value]},
        # --- censored discriminator (v2): false == real closed trade, true == open-at-end lot ---
        "censored": {"type": "boolean"},
        # --- execution (entry always real; exit null on a censored open row) ---
        "symbol": {"type": "string", "minLength": 1},
        "entry_dt": {"type": "string"},        # ISO 8601
        "entry_px": {"type": "number"},
        "exit_dt": {"type": ["string", "null"]},   # null on a censored (still-open) row
        "exit_px": {"type": ["number", "null"]},   # null on a censored (still-open) row
        "qty": {"type": "number"},             # absolute share count of the lot
        "side": {"enum": ["long", "short"]},
        # pnl/ret: realized on a closed row; PROVISIONAL mark-to-market on a censored row (null if
        # the mark is unavailable — never faked).
        "pnl": {"type": ["number", "null"]},
        "ret": {"type": ["number", "null"]},
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
        # --- m2m provenance (v2): the provisional mark's outcome + source, censored rows only ---
        "m2m_ret": {"type": ["number", "null"]},
        "m2m_source": {"enum": [M2M_QC_NATIVE, M2M_LOCAL_PARQUET, M2M_UNAVAILABLE, None]},
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
    """Parse the entry-order TAG → typed decision_* fields. #archive ①: delegates to the SHARED
    runtime.tag_schema.parse_entry_tag — the SAME module lean_entry._build_entry_tag encodes with,
    so emit and parse CANNOT desync (a key/format drift would break the round-trip test, not slip
    through as a silent all-None substrate). Missing/uncastable → None, never faked."""
    return parse_entry_tag(tag)


def _expand_cond(cond: str | None) -> dict[str, bool | None]:
    """decision_cond "11110111" → cond_0..cond_7 booleans (shared tag_schema.expand_cond). None when
    the cond is absent (the row is flagged CORE_MISSING, not silently all-False)."""
    return expand_cond(cond)


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
def _pair_trades(
    orders: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair entry+exit fills per symbol into closed trades (FIFO lot matching).

    A BUY opens long lots (a SELL while flat opens a short lot); the opposite-side fill closes the
    oldest open lot(s). Each closed trade records the OPENING fill's tag as its decision context
    (the conditions the entry SAW) and the CLOSING fill for exit_dt/exit_px/exit_reason. Partial
    fills split lots so qty/pnl stay exact.

    Returns ``(closed, open_residual)``. CLOSED is the realized-trade list — its pairing logic is
    UNCHANGED (the v1 22-closed behaviour is preserved verbatim). OPEN_RESIDUAL is the leftover lots
    still open at end of data (a filled entry whose protective stop was Submitted-never-filled →
    status 1, so no opposite-side fill ever netted it). v1 DROPPED these; v2 emits them as CENSORED
    rows so the loser-biased closed set is not the whole substrate. Each open lot carries its sign
    (long/short), absolute qty, entry px/dt, and the OPENING fill's tag (same decision context)."""
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
            qty += sign * close_qty                  # incoming is opposite-sign → also toward 0 (≡ -= -sign*..)
            if abs(lot["qty"]) < 1e-9:
                lots.pop(0)

        # Any residual incoming quantity opens a new lot on its own side.
        if abs(qty) > 1e-9:
            lots.append({"qty": qty, "px": px, "dt": dt, "tag": o.get("tag")})

    # Collect the leftover OPEN lots (no opposite-side fill ever closed them) — the censored set.
    # Deterministic order: by symbol, then entry dt, then entry px (stable across re-runs).
    open_residual: list[dict[str, Any]] = []
    for sym in sorted(open_lots):
        for lot in open_lots[sym]:
            if abs(lot["qty"]) < 1e-9:
                continue
            open_residual.append(
                {
                    "symbol": sym,
                    "entry_dt": lot["dt"],
                    "entry_px": lot["px"],
                    "qty": abs(lot["qty"]),
                    "side": "long" if lot["qty"] > 0 else "short",
                    "entry_tag": lot["tag"],
                }
            )
    open_residual.sort(key=lambda r: (r["symbol"], r["entry_dt"], r["entry_px"]))

    return closed, open_residual


def _trade_to_row(trade: Mapping[str, Any]) -> dict[str, Any]:
    """A paired trade → the schema-validated JSONL row (typed decision_* + cond bits + flag)."""
    decision = _parse_entry_tag(trade.get("entry_tag"))
    cond_bits = _expand_cond(decision["decision_cond"])
    core_present = decision["decision_score"] is not None and decision["decision_cond"] is not None
    row: dict[str, Any] = {
        "schema_version": TRADE_SCHEMA_VERSION,
        "context_status": (ContextStatus.OK if core_present else ContextStatus.CORE_MISSING).value,
        # v2: a real closed trade (real exit) — never provisional.
        "censored": False,
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
        # m2m provenance — N/A on a realized closed row (it has a real exit).
        "m2m_ret": None,
        "m2m_source": None,
        # cond bits
        **cond_bits,
    }
    return row


def _open_lot_to_row(
    lot: Mapping[str, Any],
    *,
    end_of_data: datetime,
    m2m_mark: M2MMark,
) -> dict[str, Any]:
    """A leftover OPEN lot → a CENSORED, schema-validated row (the let-winners blind spot fix).

    The entry context is REAL (the opening fill + its tag — same decision_* parse as a closed row).
    The exit is OPEN: exit_dt = end_of_data, exit_px = null, exit_reason = ``censored_open``. The
    outcome is PROVISIONAL — marked-to-market via the injected ``m2m_mark`` (entry_px → end-of-data
    mark): m2m_ret (and the convenience pnl/ret mirror it). If no mark resolves, m2m_ret / pnl / ret
    are null and m2m_source is ``unavailable`` — NEVER faked. The mine reads ``censored`` to keep
    this provisional (unrealized) outcome distinct from realized closed-trade outcomes."""
    decision = _parse_entry_tag(lot.get("entry_tag"))
    cond_bits = _expand_cond(decision["decision_cond"])
    core_present = decision["decision_score"] is not None and decision["decision_cond"] is not None

    entry_px = float(lot["entry_px"])
    side = lot["side"]
    mark, source = m2m_mark(lot["symbol"], end_of_data)
    # A mark is USABLE only if it is a finite, strictly-positive price from a non-unavailable
    # source. A 0 / negative / NaN / inf mark is corrupt data — mirror _fill_price's "refuse to bank
    # a degenerate price" stance: do NOT fabricate a -100% (or NaN — which also serialises as the
    # invalid JSON token `NaN`) provisional outcome; degrade to the honest unavailable null instead.
    mark_f = float(mark) if mark is not None else None
    usable = (
        mark_f is not None
        and source != M2M_UNAVAILABLE
        and math.isfinite(mark_f)
        and mark_f > 0.0
        and entry_px != 0.0
    )
    if usable:
        assert mark_f is not None  # narrowed by usable
        sign = 1.0 if side == "long" else -1.0
        m2m_ret = ((mark_f - entry_px) / entry_px) * sign
        m2m_pnl = (mark_f - entry_px) * float(lot["qty"]) * sign
    else:
        # No resolvable (usable) mark → honest null; do NOT fabricate. Force the unavailable label.
        mark_f = None
        source = M2M_UNAVAILABLE
        m2m_ret = None
        m2m_pnl = None

    row: dict[str, Any] = {
        "schema_version": TRADE_SCHEMA_VERSION,
        "context_status": (ContextStatus.OK if core_present else ContextStatus.CORE_MISSING).value,
        # v2: an open-at-end lot — outcome is provisional, not realized.
        "censored": True,
        # execution — entry real, exit OPEN.
        "symbol": lot["symbol"],
        "entry_dt": _iso(lot["entry_dt"]),
        "entry_px": entry_px,
        "exit_dt": _iso(end_of_data),       # marked at end-of-data, not a real exit fill
        "exit_px": mark_f,                   # the M2M mark (None when no usable mark resolved)
        "qty": float(lot["qty"]),
        "side": side,
        # provisional mark-to-market (null when the mark is unavailable — never faked)
        "pnl": m2m_pnl,
        "ret": m2m_ret,
        "duration_sec": max(0.0, (_as_dt(end_of_data) - _as_dt(lot["entry_dt"])).total_seconds()),
        "exit_reason": CENSORED_EXIT_REASON,
        # decision (typed; null if absent) — SAME context as a closed row
        **decision,
        # excursion — follow-on emit; null today
        "mfe": None,
        "mae": None,
        # m2m provenance
        "m2m_ret": m2m_ret,
        "m2m_source": source,
        # cond bits
        **cond_bits,
    }
    return row


def _as_dt(dt: Any) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    s = str(dt).replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


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
    end_of_data: datetime | str | None = None,
    m2m_mark: M2MMark | None = None,
    runtime_statistics: Mapping[str, Any] | None = None,
    run_class: str | None = None,
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
      run_class           "validation" | "substrate-generation" (Falk 2026-06-02, CONVENTIONS run-class
                          protocol). VALIDATION = a candidate/champion grade (window-then-FY, 6-window
                          mandatory) — its Sharpe/Ret/DD ARE grades. SUBSTRATE-GENERATION = mine fuel
                          (full-year OK for trade count) — its metrics are NOT validation grades and
                          MUST NOT be read as such. Validated if given; None = undeclared (a protocol
                          gap to fix, not an error here — back-compat for callers not yet threading it).
      orders_fetch        the injected `/orders/read` callable (retried w/ backoff; tests mock it).
      dest_root           the injected write root (tests pass tmp_path).
      end_of_data         the run's terminal timestamp (END_DATE / last-data day) — the mark date for
                          CENSORED open lots. Required to emit censored rows: if None (or m2m_mark is
                          None) the censored-open capture is SKIPPED (back-compat / callers that don't
                          wire it yet); closed-trade behaviour is unchanged either way.
      m2m_mark            the injected per-symbol end-of-data mark source (M2MMark) for censored
                          (open-at-end) lots. PREFER QC-native; fall back to RAW/unadjusted local at
                          end_of_data; `unavailable` (m2m_ret null) when neither — NEVER faked.
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
    may have no trades). A pairing/validation error (corrupt fill) is also tolerated on CRASHED →
    empty trades, so result.json still captures config + stats and provenance survives.

    ② (non-CRASHED): the statistics MUST carry a parseable 'Total Orders' — else ArchiveError (the
    silent-miss guard cannot run on an unverifiable order count; an absent/wrong key would silently
    disable it).

    COMPLETION-MARKER CONTRACT (④): result.json is written LAST (step 5), after trades.jsonl.gz. So
    `result.json` present + valid == the run dir is COMPLETE. A run dir with trades.jsonl.gz but no
    valid result.json is an INCOMPLETE/interrupted snapshot — CONSUMERS MUST treat it as absent
    (ignore / re-snapshot), never read the trades alone. (The two writes are individually atomic but
    not cross-atomic; result.json-last is the de-facto commit marker.)

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
    if run_class is not None and run_class not in ("validation", "substrate-generation"):
        raise ArchiveError(
            f"run_class must be 'validation' or 'substrate-generation' (or None/undeclared), "
            f"got {run_class!r} — never conflate a substrate-gen run's metrics with a validation grade"
        )

    run_dir = Path(dest_root) / config_hash / backtest_id
    crashed = status is RunStatus.CRASHED

    # 1. Fetch orders (retried). On CRASHED, a fetch failure is tolerated (best-effort capture).
    orders = _fetch_orders(orders_fetch, backtest_id, fetch_retries, fetch_backoff, crashed=crashed)

    # 2. Pair + serialize trades, validating EACH row. On a CLEAN/DEGRADED run a pairing/validation
    # error (a 0-price fill, a schema violation) is a REAL fail-loud. On CRASHED, tolerate it
    # (degrade to empty trades) so result.json STILL captures provenance — the 3-state intent
    # ("capture whatever's retrievable on CRASHED"); a corrupt fill must not evaporate the run dir.
    # CENSORED open-position capture (v2, PERMANENT): this strategy is cut-losers/let-winners, so the
    # CLOSED set is loser-biased BY CONSTRUCTION on EVERY run (a stop that never fires leaves the
    # WINNERS open at end-of-data; v1 DROPPED them → a closed-only substrate teaches the mine "these
    # conditions → LOSS", FALSE). We emit the leftover open lots as censored, mark-to-market rows.
    # Requires both end_of_data and m2m_mark wired; if either is absent the censored capture is
    # skipped (closed behaviour unchanged) — it is NOT faked.
    eod = _as_dt(end_of_data) if end_of_data is not None else None
    capture_open = eod is not None and m2m_mark is not None
    try:
        closed, open_residual = _pair_trades(orders)
        rows = [_trade_to_row(t) for t in closed]
        if capture_open:
            assert eod is not None and m2m_mark is not None  # narrowed by capture_open
            rows += [
                _open_lot_to_row(lot, end_of_data=eod, m2m_mark=m2m_mark) for lot in open_residual
            ]
        for row in rows:
            _validate_trade_row(row)
    except ArchiveError:
        if not crashed:
            raise
        rows = []  # crashed + corrupt fill/row → empty trades; provenance survives via result.json

    # 3. The silent-miss guard (the crux): empty trades while stats say orders fired.
    total_orders = _total_orders(statistics)
    # ② (HQ): a non-CRASHED run MUST carry a parseable 'Total Orders' — else the silent-miss guard
    # below can't run, and a wrong/absent key would SILENTLY DISABLE the single most important
    # check. That unverifiable state is ITSELF fail-loud, not a silent skip.
    if not crashed and total_orders is None:
        raise ArchiveError(
            f"statistics carry no parseable 'Total Orders' (bt={backtest_id}, status={status.value}) "
            f"— the silent-miss guard cannot run; refusing to archive an unverifiable order count (#276b ②)"
        )
    # The silent-miss is about ANY trade row evaporating while orders fired — a run with only
    # censored-open lots (0 closed) still has rows, so an empty `rows` means BOTH closed and open are
    # gone: the true silent-miss. Guard on the full row set.
    if not crashed and not rows and total_orders is not None and total_orders > 0:
        raise EmptyTradesError(
            f"0 trade rows parsed (closed+censored) but statistics Total Orders={total_orders} "
            f"(bt={backtest_id}, status={status.value}) — the run would silently evaporate; fail loud "
            f"(#276b silent-miss)"
        )

    # 4. Write trades.jsonl.gz (atomic, gzip-from-day-1, deterministic). allow_nan=False so a stray
    # NaN/inf (which would serialise as the INVALID JSON token `NaN`/`Infinity` and silently corrupt
    # the substrate) RAISES instead — fail loud, never write an unparseable line (#276b data-integrity).
    jsonl = "".join(
        json.dumps(r, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n" for r in rows
    )
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
        # run-class (Falk 2026-06-02): "validation" metrics ARE grades; "substrate-generation"
        # metrics are NOT (mine fuel — full-year-OK, per-window decomp required). None = undeclared.
        "run_class": run_class,
        "statistics": dict(statistics),
        # #303 funnel: the per-run cumulative funnel.* counters (signal_winners→…→orders) + the
        # funnel._sem legend, captured INLINE here (they ride /backtests/read.runtimeStatistics at
        # run-time, same as the trio — folded in so new runs carry their own per-year funnel
        # decomposition without a post-hoc step). None when not supplied (e.g. local runs).
        "runtime_statistics": dict(runtime_statistics) if runtime_statistics else None,
        # n_closed_trades counts REALIZED rows only (back-compat); n_censored / n_censored_trades is
        # the open-at-end provisional count (both keys for the mine's gate convenience — #303 reads
        # n_censored without decompressing the jsonl); n_trade_rows is the total written.
        "n_closed_trades": sum(1 for r in rows if not r["censored"]),
        "n_censored": sum(1 for r in rows if r["censored"]),
        "n_censored_trades": sum(1 for r in rows if r["censored"]),
        "n_trade_rows": len(rows),
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
