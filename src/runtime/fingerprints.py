"""Universe artifact fingerprints — the SINGLE source of the hash algorithm.

Used at BUILD time (scripts/build_filter.py, scripts/build_universe.py) AND at LOAD time
(runtime/lean_entry.load_universe). They MUST be the same function: the load-time
fingerprint-verify (#213 anti-#182 guardrail) recomputes the loaded artifact's hash and
asserts it equals the pinned build-time value. If the two used different algorithms the
check would be meaningless. So both import from here — never reimplement.

- membership_hash: PURE eligibility membership (date -> sorted tickers, DV/order EXCLUDED).
  The "diff this FIRST" handle in divergence-debug. Accepts the filter artifact
  ({date: {ticker: dv}}) or any {date: <iterable of tickers>}.
- order_hash: ORDER-sensitive (date -> the list verbatim). The ranked artifact's order is
  its whole point; this changes if the rank order changes.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Union

# date -> (iterable of tickers)  OR  date -> {ticker: dv}
MembershipMap = Mapping[str, Union[Iterable[str], Mapping[str, float]]]
OrderMap = Mapping[str, list[str]]


def membership_hash(data: MembershipMap) -> str:
    """SHA-256 over date -> sorted(tickers). Order/DV-independent: a pure eligibility
    fingerprint. `data[date]` may be a dict ({ticker: dv} -> keys) or any ticker iterable.
    """
    h = hashlib.sha256()
    for date in sorted(data):
        h.update(date.encode("utf-8"))
        h.update(b":")
        h.update(",".join(sorted(data[date])).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def order_hash(universe: OrderMap) -> str:
    """SHA-256 over date -> LIST verbatim (ORDER-SENSITIVE). Changes if the ranked order
    changes — the structural check that local and cloud scan the same set in the same order.
    """
    h = hashlib.sha256()
    for date in sorted(universe):
        h.update(date.encode("utf-8"))
        h.update(b":")
        h.update(",".join(universe[date]).encode("utf-8"))  # NOT sorted — order matters
        h.update(b"\n")
    return h.hexdigest()
