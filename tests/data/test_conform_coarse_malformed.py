"""#263 — conform/CSV-layer WRONG-SHAPED / MALFORMED / MISSING-data coverage.

scripts/conform_coarse.py is the WRITER that emits the local 8-col QC-native coarse files the
LEAN-native reader feeds into _coarse_selection. Its read side (`_read_daily_zip` parsing each
ticker's daily zip) and `build_row` (emitting one coarse row) are the testable PARSE surface for
the wrong-shaped / missing-data cases. The LEAN C# CoarseFundamental reader that materialises
the on-disk CSV into coarse objects is NOT Python — its contract is pinned at the boundary the
engine owns in tests/runtime/test_coarse_parse.py (the 8-col row → coarse-object adapter).

Falk's #263 mandate: degraded / malformed / missing / zero-row data must FAIL LOUD (raise or
loud-skip with a LOGGED reason) — NEVER a silent-0 / empty-set mirage. Where conform_coarse is
SILENTLY-LENIENT (drops a ticker with no logged reason, or emits a malformed row) that is a
FINDING: the test asserts the CORRECT fail-loud behavior + is marked xfail + reported as a #261
line-item. We do NOT change engine/conform behavior here (test-only ticket).

ACTUAL behavior probed before writing (read the code, test reality):
  - `_read_daily_zip` wraps the parse in `except (BadZipFile, IndexError, ValueError): return
    None` — so ANY single malformed row (non-numeric close, truncated row, a header line)
    drops the ENTIRE ticker to None with NO logged reason. SILENT-SKIP finding (#261).
  - `build_row` emits a row from whatever `_read_daily_zip` returned with NO finite/sign
    validation — a negative or non-finite close yields a malformed-but-written coarse row.
    SILENT-EMIT finding (#261). (The downstream floor rejects it, but the gap is real.)
  - Missing map_file / missing daily zip → `build_row`/`_read_daily_zip` → None (correct skip:
    no data == no row; this is correct-0 at the per-ticker grain, not a broken-0).
"""
from __future__ import annotations

import datetime as dt
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import conform_coarse  # noqa: E402  (scripts/ path inserted above)


# ---------------------------------------------------------------------------
# Isolated temp data tree — each test points conform_coarse's module globals at a
# throwaway dir so we never touch the real data/ symlink. (build_row/_read_daily_zip
# read _DAILY/_MAPS/_FACTORS as module globals.)
# ---------------------------------------------------------------------------
@pytest.fixture()
def coarse_env(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    maps = tmp_path / "map_files"
    factors = tmp_path / "factor_files"
    for d in (daily, maps, factors):
        d.mkdir()
    monkeypatch.setattr(conform_coarse, "_DAILY", daily)
    monkeypatch.setattr(conform_coarse, "_MAPS", maps)
    monkeypatch.setattr(conform_coarse, "_FACTORS", factors)
    conform_coarse._factor_rows.cache_clear()  # memoised; clear between tests

    def write_daily(ticker: str, lines: list[str]) -> None:
        with zipfile.ZipFile(daily / f"{ticker}.zip", "w") as zf:
            zf.writestr(f"{ticker}.csv", "\n".join(lines))

    def write_corrupt_zip(ticker: str) -> None:
        (daily / f"{ticker}.zip").write_bytes(b"this is not a zip file")

    def write_map(ticker: str, first: str = "20210512") -> None:
        (maps / f"{ticker}.csv").write_text(f"{first},{ticker},2050\n")

    return type("Env", (), {
        "write_daily": staticmethod(write_daily),
        "write_corrupt_zip": staticmethod(write_corrupt_zip),
        "write_map": staticmethod(write_map),
    })


_VALID_BAR = "20250103 00:00,5391000,5400000,5380000,5391000,1000000"  # close=539.1, vol=1e6


# ── PARSE: a valid daily bar parses to (real_close, volume) ────────────────────


def test_read_daily_zip_valid_bar(coarse_env) -> None:
    coarse_env.write_daily("good", [_VALID_BAR])
    assert conform_coarse._read_daily_zip("good") == {"20250103": (539.1, 1_000_000)}


def test_build_row_valid_is_8col_qc_native(coarse_env) -> None:
    coarse_env.write_map("good")
    coarse_env.write_daily("good", [_VALID_BAR])
    daily = conform_coarse._read_daily_zip("good")
    row = conform_coarse.build_row("good", "20250103", daily)
    assert row is not None
    cols = row.split(",")
    assert len(cols) == 8
    assert cols[1] == "GOOD"           # ticker upper
    assert cols[2] == "539.1"          # close
    assert cols[4] == "539100000"      # dollar_volume = close*volume
    assert cols[5] == "True"           # has_fundamental_data


# ── MISSING DATA: correct-skip (no data == no row), distinguishable from broken ─


def test_build_row_missing_map_file_returns_none(coarse_env) -> None:
    # No map_file -> no SID first-date -> None. Correct skip (a name with no map can't resolve).
    coarse_env.write_daily("nomap", [_VALID_BAR])
    daily = conform_coarse._read_daily_zip("nomap")
    assert conform_coarse.build_row("nomap", "20250103", daily) is None


def test_read_daily_zip_missing_file_returns_none(coarse_env) -> None:
    # No daily zip at all -> None. Correct skip (no price data for this ticker).
    assert conform_coarse._read_daily_zip("doesnotexist") is None


def test_build_row_no_bar_that_day_returns_none(coarse_env) -> None:
    # Daily zip exists but has no bar for the requested day (e.g. ticker not yet listed) -> None.
    coarse_env.write_map("good")
    coarse_env.write_daily("good", [_VALID_BAR])
    daily = conform_coarse._read_daily_zip("good")
    assert conform_coarse.build_row("good", "20251231", daily) is None  # different day


def test_read_daily_zip_empty_file_yields_empty_dict(coarse_env) -> None:
    # An empty daily CSV -> {} (0 bars). Distinct from None (absent file): an EMPTY result that
    # is genuinely 0 rows. build_row over {} returns None (no bar that day) — correct-0.
    coarse_env.write_daily("empty", [""])
    assert conform_coarse._read_daily_zip("empty") == {}


# ── WRONG-SHAPED ROWS: ACTUAL silent-skip behavior + the #261 fail-loud findings ─


def test_read_daily_zip_corrupt_zip_returns_none(coarse_env) -> None:
    # A corrupt (non-zip) file -> None. The BadZipFile branch. (Arguably should log a reason —
    # see the silent-skip finding below; but a None here at least doesn't emit a junk row.)
    coarse_env.write_corrupt_zip("corrupt")
    assert conform_coarse._read_daily_zip("corrupt") is None


@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: _read_daily_zip catches ValueError on a single non-numeric "
    "close and returns None for the ENTIRE ticker with NO logged reason — one bad row silently "
    "drops a whole name from every coarse day. Falk's mandate: a malformed row must fail loud "
    "or loud-SKIP-with-a-logged-reason, never a silent drop. DESIRED: raise (or log+skip the "
    "ROW, not the ticker). #261 owns the conform fail-loud change.",
    strict=True,
)
def test_read_daily_zip_nonnumeric_close_fails_loud(coarse_env) -> None:
    # DESIRED behavior: a non-numeric close raises (or skips only that row with a logged reason).
    # ACTUAL: returns None silently for the whole ticker.
    coarse_env.write_daily("badclose", ["20250103 00:00,o,h,l,NOTANUM,1000000"])
    with pytest.raises(ValueError):
        conform_coarse._read_daily_zip("badclose")


@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: a TRUNCATED daily row triggers IndexError, caught -> None for "
    "the whole ticker, no logged reason (silent drop). Should fail loud / loud-skip the row.",
    strict=True,
)
def test_read_daily_zip_truncated_row_fails_loud(coarse_env) -> None:
    coarse_env.write_daily("trunc", ["20250103 00:00,5391000"])  # missing high/low/close/vol
    with pytest.raises((ValueError, IndexError)):
        conform_coarse._read_daily_zip("trunc")


@pytest.mark.xfail(
    reason="#261 FAIL-LOUD GAP: a HEADER row mixed into a daily zip (e.g. 'Date,Open,...') is "
    "non-numeric -> ValueError caught -> None for the whole ticker, silently. The valid bars "
    "after the header are lost too. Should loud-skip the header row, keep the real bars.",
    strict=True,
)
def test_read_daily_zip_header_row_fails_loud(coarse_env) -> None:
    coarse_env.write_daily("hdr", ["Date,Open,High,Low,Close,Volume", _VALID_BAR])
    # DESIRED: the real bar survives (header skipped with a reason), OR a loud raise.
    result = conform_coarse._read_daily_zip("hdr")
    assert result == {"20250103": (539.1, 1_000_000)}  # ACTUAL: None (whole ticker dropped)


@pytest.mark.xfail(
    reason="#261 SILENT-EMIT GAP: build_row performs NO finite/sign validation on close — a "
    "NEGATIVE close (corrupt daily bar) is emitted as a malformed coarse row "
    "(negative close + negative dollar_volume). The downstream floor rejects it, but conform "
    "should fail loud / loud-skip rather than WRITE a degraded row into the universe file. "
    "#261 owns the conform validation.",
    strict=True,
)
def test_build_row_rejects_negative_close(coarse_env) -> None:
    coarse_env.write_map("negc")
    coarse_env.write_daily("negc", ["20250103 00:00,-5391000,1,1,-5391000,1000000"])
    daily = conform_coarse._read_daily_zip("negc")
    # DESIRED: build_row refuses to emit a negative-close row (returns None or raises).
    assert conform_coarse.build_row("negc", "20250103", daily) is None


def test_build_row_negative_close_actual_emits_malformed_row(coarse_env) -> None:
    # PIN the ACTUAL (silently-lenient) behavior so the #261 finding is concrete: build_row
    # currently EMITS a negative-close / negative-DV row. This is the exact silent-emit the
    # fail-loud guard must close. (Not xfail — it documents reality for the #261 line-item.)
    coarse_env.write_map("negc")
    coarse_env.write_daily("negc", ["20250103 00:00,-5391000,1,1,-5391000,1000000"])
    daily = conform_coarse._read_daily_zip("negc")
    row = conform_coarse.build_row("negc", "20250103", daily)
    assert row is not None
    cols = row.split(",")
    assert float(cols[2]) < 0  # negative close written
    assert float(cols[4]) < 0  # negative dollar_volume written


# ── SID encoding edge (the parse path's identity column) ───────────────────────


def test_generate_equity_sid_is_two_token_parseable() -> None:
    sid = conform_coarse.generate_equity_sid("AAPL", dt.date(2021, 5, 12))
    ticker, _, props = sid.partition(" ")
    assert ticker == "AAPL"
    assert props and all(c in conform_coarse._B36 for c in props)


def test_encode_base36_rejects_negative() -> None:
    # The properties integer is never negative; a negative input is a programming error and
    # must fail loud (the one place conform_coarse DOES raise on bad input — pin it).
    with pytest.raises(ValueError):
        conform_coarse._encode_base36(-1)
