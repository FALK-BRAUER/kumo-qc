"""#263 — coarse PARSE + WRONG-SHAPED / malformed coverage at the ENGINE-CONSUMPTION layer.

Falk's #263 mandate: "everything needs unit test — integration failures, missing data,
wrong-shaped data. everything. all edge cases and integrations." HARD principle: degraded /
malformed / missing / zero-row data must FAIL LOUD (raise or loud-skip with a logged reason)
— NEVER a silent-0 / empty-set mirage (the silent empty-warmup universe is exactly what
produced the fake −0.616 baseline).

SCOPE OF THIS FILE — the PYTHON surface the engine actually consumes from QC's coarse feed:
  - The 8-col QC-native coarse ROW contract (what `_coarse_selection` reads off each coarse
    object): col1=ticker, col2=close, col4=dollar_volume. Parsed here against a REAL conformed
    row from data/.../coarse/ AND fed through `coarse_to_dollar_volume`/`coarse_to_close` via a
    row→coarse-object adapter, so the field MAPPING the engine relies on is pinned.
  - `coarse_to_dollar_volume` / `coarse_to_close` on MALFORMED coarse objects: non-numeric →
    must RAISE (fail-loud, asserted); NaN / Inf / negative → the engine's ACTUAL behavior is
    asserted, and where it is silently-lenient against Falk's fail-loud mandate it is marked
    xfail + reported as a #261 line-item (the fail-loud engine change is #261's, not #263's).
  - `apply_floors` on NaN / Inf / negative metrics (the selection gate's last line of defence).

NOTE on the LEAN-native CSV reader: locally LEAN's C# CoarseFundamental reader parses the
on-disk CSV into the coarse objects — that reader is NOT Python and cannot be unit-tested in
the dev venv. The conform/CSV-emit-and-read layer (scripts/conform_coarse.py: `_read_daily_zip`
/ `build_row` / the wrong-shaped-row behavior) is covered in
tests/data/test_conform_coarse_malformed.py. THIS file pins the contract at the boundary the
Python engine owns: the coarse object → dict extraction + the floors.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from runtime.lean_entry import coarse_to_close, coarse_to_dollar_volume
from runtime.universe_select import apply_floors

_ROOT = Path(__file__).resolve().parents[2]
_COARSE = _ROOT / "data" / "equity" / "usa" / "fundamental" / "coarse"


# ---------------------------------------------------------------------------
# Row→coarse-object adapter: mirror the 8-col QC-native contract the LEAN reader
# materialises, so we can drive the engine's PURE extractors from a CSV row exactly
# as the C# reader would. Columns (verified vs data/.../coarse/ + conform_coarse docs):
#   0:SID  1:ticker  2:close  3:volume  4:dollar_volume  5:hasFund  6:priceFactor  7:split
# ---------------------------------------------------------------------------
class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value


class _CoarseRow:
    """A coarse object materialised from an 8-col QC-native row. Exposes exactly the three
    attributes the engine reads: `.symbol.value` (col1, ticker), `.price` (col2, RAW close),
    `.dollar_volume` (col4). This is the SAME shape FakeCoarse in test_lean_entry uses, but
    constructed FROM a real CSV row to pin the column→field mapping."""

    def __init__(self, row: str) -> None:
        cols = row.split(",")
        if len(cols) != 8:
            raise ValueError(f"not an 8-col QC-native coarse row: {row!r}")
        self.symbol = _Sym(cols[1])
        self.price = float(cols[2])
        self.dollar_volume = float(cols[4])


def _have_local_data() -> bool:
    return _COARSE.is_dir() and any(_COARSE.glob("2025*.csv"))


# ── 1. Coarse PARSE — a valid 8-col row parses to the engine's expected fields ──


def test_valid_8col_row_parses_to_engine_fields() -> None:
    # A hand-written canonical row (mirrors a real conformed row, e.g. "A XOF4GF67NMG5,A,
    # 133.47,747886,99820344.42,True,1,1"). The engine reads col1/col2/col4.
    row = "AAPL XOF4GF67NMG5,AAPL,243.82,1000000,243820000000.0,True,1,1"
    c = _CoarseRow(row)
    assert c.symbol.value == "AAPL"
    assert c.price == 243.82
    assert c.dollar_volume == 243820000000.0
    # ...and the engine's extractors pull exactly those (lowercased per the zip-stem convention)
    assert coarse_to_close([c]) == {"aapl": 243.82}
    assert coarse_to_dollar_volume([c]) == {"aapl": 243820000000.0}


@pytest.mark.skipif(not _have_local_data(), reason="local LEAN coarse tree absent (gitignored)")
def test_real_conformed_row_parses_and_feeds_extractors() -> None:
    # PIN against REAL conformed data: the first row of the FY2025 day-1 file must parse as
    # an 8-col QC-native row and feed the engine extractors with sane (positive, finite) values.
    fp = _COARSE / "20250102.csv"
    first = next(ln for ln in fp.read_text().splitlines() if ln)
    cols = first.split(",")
    assert len(cols) == 8, f"real coarse row not 8-col: {first!r}"
    c = _CoarseRow(first)
    assert c.symbol.value  # non-empty ticker
    assert c.price > 0 and math.isfinite(c.price)
    assert c.dollar_volume > 0 and math.isfinite(c.dollar_volume)
    # the field MAPPING the engine depends on (col1→ticker, col2→price, col4→dv) holds on
    # real data, not just a synthetic row.
    assert coarse_to_close([c]) == {c.symbol.value.lower(): c.price}
    assert coarse_to_dollar_volume([c]) == {c.symbol.value.lower(): c.dollar_volume}


# ── 2. WRONG-SHAPED rows at the adapter (the 8-col contract) ───────────────────


@pytest.mark.parametrize(
    "row, why",
    [
        ("AAPL SID,AAPL,243.82,1000,243820,True", "5-col old format (too few)"),
        ("AAPL SID,AAPL,243.82,1000", "truncated / half row"),
        ("AAPL SID,AAPL,243.82,1000,243820,True,1,1,EXTRA", "too many columns"),
        ("Symbol,Price,Volume,DollarVolume,Has", "a 'Symbol,Price' header row"),
        ("", "empty line"),
    ],
)
def test_wrong_column_count_row_is_rejected_loud(row: str, why: str) -> None:
    # The 8-col contract is exact: anything else must FAIL LOUD at materialisation, never be
    # silently coerced into a wrong/partial coarse object. (_CoarseRow models the column-count
    # invariant the LEAN reader enforces; a wrong-width row never becomes a usable coarse obj.)
    with pytest.raises(ValueError):
        _CoarseRow(row)


def test_non_numeric_close_column_rejected_loud() -> None:
    # col2 (close) must be numeric — a "NOTANUM" close must raise, never become a junk price.
    with pytest.raises(ValueError):
        _CoarseRow("AAPL SID,AAPL,NOTANUM,1000,243820,True,1,1")


def test_non_numeric_dollar_volume_column_rejected_loud() -> None:
    # col4 (dollar_volume) must be numeric — a non-numeric DV must raise, never select a name.
    with pytest.raises(ValueError):
        _CoarseRow("AAPL SID,AAPL,243.82,1000,NOTANUM,True,1,1")


# ── 3. MALFORMED coarse objects at the engine extractors ───────────────────────


class _FakeSym:
    def __init__(self, value: object) -> None:
        self.value = value


class _FakeCoarse:
    def __init__(self, ticker: object, dv: object, price: object) -> None:
        self.symbol = _FakeSym(ticker)
        self.dollar_volume = dv
        self.price = price


def test_extractors_raise_on_non_numeric_dollar_volume() -> None:
    # FAIL-LOUD (asserted, GOOD): float("abc") raises ValueError — a non-numeric DV is never
    # silently dropped or coerced to 0. This is the correct behavior; pin it so it stays.
    with pytest.raises(ValueError):
        coarse_to_dollar_volume([_FakeCoarse("AAPL", "abc", 50.0)])


def test_extractors_raise_on_non_numeric_price() -> None:
    with pytest.raises(ValueError):
        coarse_to_close([_FakeCoarse("AAPL", 5.0e9, "xyz")])


# --- NaN / Inf / negative: ACTUAL behavior asserted; FINDINGS marked xfail (#261). ---

@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: coarse_to_dollar_volume silently passes NaN through "
    "(float('nan')) instead of raising/loud-skipping. A NaN DV is degraded data that must "
    "fail loud, not enter the rolling-DV window. Engine fail-loud change is #261's.",
    strict=True,
)
def test_extractors_reject_nan_dollar_volume() -> None:
    # DESIRED (fail-loud) behavior: a NaN dollar_volume must raise. ACTUAL: it passes through
    # as {'aapl': nan}. xfail until #261 adds the finite-guard at the selection gate.
    with pytest.raises((ValueError, FloatingPointError)):
        coarse_to_dollar_volume([_FakeCoarse("AAPL", float("nan"), 50.0)])


@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: coarse_to_dollar_volume silently passes Inf through. An Inf "
    "DV would dominate the DV-desc rank (Inf > any real DV) AND pass apply_floors — a garbage "
    "name could be selected #1. Must fail loud / be filtered. #261 owns the engine guard.",
    strict=True,
)
def test_extractors_reject_inf_dollar_volume() -> None:
    with pytest.raises((ValueError, OverflowError)):
        coarse_to_dollar_volume([_FakeCoarse("AAPL", float("inf"), 50.0)])


def test_extractors_pass_negative_dv_through_but_floors_reject_it() -> None:
    # A negative DV is nonsensical but NOT silently selected: it passes the extractor (no guard)
    # yet apply_floors rejects it (neg < 100M). So the SELECTION outcome is correct-reject. We
    # pin BOTH facts: the extractor is lenient (documented) AND the floor is the safety net.
    dv = coarse_to_dollar_volume([_FakeCoarse("AAPL", -5.0e8, 50.0)])
    assert dv == {"aapl": -5.0e8}  # extractor lenient (no finite/sign guard) — documented
    assert apply_floors({"aapl": (50.0, -5.0e8)},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []  # floor rejects


# ── 4. apply_floors with NaN / Inf / negative metrics (selection gate defence) ──


def test_apply_floors_nan_dv_excluded() -> None:
    # NaN fails the `dv >= floor` comparison (NaN comparisons are False) -> excluded. This is a
    # benign correct-reject (degraded name dropped), so NOT a fail-loud gap on its own — but the
    # name vanishing silently is why #261 should fail-loud upstream at the extractor.
    assert apply_floors({"a": (50.0, float("nan"))},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []


def test_apply_floors_nan_price_excluded() -> None:
    assert apply_floors({"a": (float("nan"), 5.0e8)},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []


def test_apply_floors_negative_price_and_dv_excluded() -> None:
    assert apply_floors({"a": (-5.0, 5.0e8)},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []
    assert apply_floors({"a": (50.0, -5.0e8)},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []


@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: apply_floors ADMITS an Inf dollar_volume (Inf >= 100M is True), "
    "so a name whose trailing DV is Inf would PASS the liquidity floor AND rank #1 (DV-desc). "
    "A non-finite metric must be rejected/fail-loud at the gate, not selected. #261 owns the "
    "finite-guard (apply_floors or the extractor). Asserting the DESIRED reject here.",
    strict=True,
)
def test_apply_floors_rejects_inf_dv() -> None:
    # DESIRED: an Inf dv is NOT eligible (it is degraded data). ACTUAL: it passes the floor.
    assert apply_floors({"a": (50.0, float("inf"))},
                        min_price=10.0, min_avg_dollar_volume=1.0e8) == []
