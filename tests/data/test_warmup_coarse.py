"""#259 — the WARMUP-NON-EMPTY guard (the assertion that would've caught the empty-warmup mirage).

ROOT CAUSE (research/parity/first-divergence-diff-2025.md, #173): the local pre-2025 WARMUP
coarse window (2023-06-20 → 2024-12-31) was never conformed — it held the OLD ~201-row 5-col
*headered* synthetic format LEAN's native CoarseFundamental reader CANNOT parse → the local
warmup universe was EMPTY for 18 months → zero subscriptions → the maintained DAILY indicators
never warmed → score_symbol_native returned None → local barely traded until ~Oct-2025. That
made the −0.616/+3.9% local trio an EMPTY-WARMUP ARTIFACT, not a real result.

These are DATA-PRESENCE tests over the REAL on-disk conformed coarse (NOT FakeQC): they assert
the warmup window is NON-EMPTY + in the 8-col headerless QC-native format the native reader
parses. PRE-FIX they FAIL (the warmup days are 201-row 5-col headered, or absent); POST-FIX
(scripts/conform_coarse.py --warmup) they PASS. This is the guard that would have caught #173
before it cost the parity FAIL.

If the local data tree is absent (CI without the gitignored data/), the tests SKIP — they are a
data-presence guard for the local harness, not a unit of pure logic. The pure conform logic
(build_row → 8 cols, SID parseable) is covered without the tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import conform_coarse  # noqa: E402  (scripts/ path inserted above)

_COARSE = _ROOT / "data" / "equity" / "usa" / "fundamental" / "coarse"

# A representative spread of warmup-window sessions (start, mid, near-end of the span) — the
# sample day called out in the #259 spec plus the span boundaries.
_WARMUP_SAMPLE_DAYS = ["20230620", "20231002", "20240701", "20241231"]
# Day 1 of the live FY2025 window — the first real trading bar (must also be non-empty).
_DAY1 = "20250102"


def _have_local_data() -> bool:
    return _COARSE.is_dir() and any(_COARSE.glob("2025*.csv"))


pytestmark = pytest.mark.skipif(
    not _have_local_data(),
    reason="local LEAN coarse tree absent (gitignored data/) — data-presence guard skips",
)


def _read_rows(ymd: str) -> list[str]:
    fp = _COARSE / f"{ymd}.csv"
    if not fp.is_file():
        return []
    return [ln for ln in fp.read_text().strip().split("\n") if ln]


# ── PURE conform logic (no data tree needed beyond a single ticker zip) ────────


def test_warmup_constants_match_the_560d_derivation() -> None:
    # 560 CALENDAR days before the FY2025 start (2025-01-01) = 2023-06-21; the span lower
    # bound is floored to 2023-06-20 (1-day margin) and ends the day before the live window.
    assert conform_coarse._WARMUP_START == "20230620"
    assert conform_coarse._WARMUP_END == "20241231"


def test_generate_equity_sid_is_parseable_two_token_form() -> None:
    # The coarse SID must be the LEAN two-token form "<TICKER> <base36-properties>" so the
    # native reader's SecurityIdentifier.Parse + Symbol(csv[0], csv[1]) resolves. (The same
    # encoding the FY2025 conform already ships — regression-pinned here for the warmup path.)
    import datetime as dt

    sid = conform_coarse.generate_equity_sid("SPY", dt.date(2021, 5, 12))
    ticker, _, props = sid.partition(" ")
    assert ticker == "SPY"
    assert props and all(c in conform_coarse._B36 for c in props)


# ── DATA-PRESENCE guard over the REAL conformed warmup window ──────────────────


@pytest.mark.parametrize("ymd", _WARMUP_SAMPLE_DAYS)
def test_warmup_day_is_nonempty(ymd: str) -> None:
    # THE assertion that would've caught #173: a warmup-window coarse day must have rows.
    # PRE-FIX: the synthetic file was ~201 rows OR absent (some span days had none); the
    # EMPTY/sparse universe is what starved indicator warmup. POST-FIX: thousands of names.
    rows = _read_rows(ymd)
    assert len(rows) > 1000, f"warmup day {ymd} has only {len(rows)} rows (empty-warmup artifact?)"


@pytest.mark.parametrize("ymd", _WARMUP_SAMPLE_DAYS)
def test_warmup_day_is_8col_headerless_qc_native(ymd: str) -> None:
    # PRE-FIX: 5-col file STARTING with the header "Symbol,Price,Volume,...". POST-FIX: 8-col
    # headerless. The header line is exactly what the native reader chokes on → empty universe.
    rows = _read_rows(ymd)
    assert rows, f"warmup day {ymd} absent"
    assert not rows[0].startswith("Symbol,Price"), f"{ymd} still has the old 5-col header"
    # Every row is the 8-col QC-native shape: SID,ticker,close,vol,dv,hasFund,priceFactor,split.
    for r in rows[:50]:
        assert len(r.split(",")) == 8, f"{ymd} row not 8-col: {r!r}"


def test_day1_live_window_is_nonempty() -> None:
    # The first real trading bar must also be a populated 8-col universe (sanity that the live
    # FY2025 conform is intact alongside the new warmup conform).
    rows = _read_rows(_DAY1)
    assert len(rows) > 1000, f"day-1 {_DAY1} has only {len(rows)} rows"
    assert len(rows[0].split(",")) == 8


def test_no_stale_old_format_files_inside_the_warmup_span() -> None:
    # After --warmup, NO file in [WARMUP_START, WARMUP_END] may still carry the 5-col header
    # (the native reader would trip on it). Orphan non-session holiday files are removed too.
    stale: list[str] = []
    for fp in _COARSE.glob("*.csv"):
        ymd = fp.stem
        if conform_coarse._WARMUP_START <= ymd <= conform_coarse._WARMUP_END:
            with fp.open() as fh:
                if fh.readline().startswith("Symbol,Price"):
                    stale.append(ymd)
    assert not stale, f"stale old-format coarse files inside warmup span: {sorted(stale)}"
