"""#263 — conform/CSV-layer WRONG-SHAPED / MALFORMED / MISSING-data coverage.

scripts/conform_coarse.py is the WRITER that emits the local 8-col QC-native coarse files the
LEAN-native reader feeds into _coarse_selection. Its read side (`_read_daily_zip` parsing each
ticker's daily zip) and `build_row` (emitting one coarse row) are the testable PARSE surface for
the wrong-shaped / missing-data cases. The LEAN C# CoarseFundamental reader that materialises
the on-disk CSV into coarse objects is NOT Python — its contract is pinned at the boundary the
engine owns in tests/runtime/test_coarse_parse.py (the 8-col row → coarse-object adapter).

Falk's #263 mandate: degraded / malformed / missing / zero-row data must FAIL LOUD (raise or
loud-skip with a LOGGED reason) — NEVER a silent-0 / empty-set mirage.

#261 RESOLUTION (this file was test-only under #263; #261 LANDED the conform fail-loud change):
  - `_read_daily_zip` no longer wraps the whole loop in a blanket `except → None` that silently
    dropped the ENTIRE ticker (incl. valid bars after a bad row). It now loud-SKIPS the bad ROW
    with a logged reason (ticker + row + why → stderr) and KEEPS every valid bar (#261-3).
  - `build_row` now loud-SKIPS a non-finite / non-positive close with a logged reason instead of
    silently EMITTING a malformed (negative close / negative DV) coarse row (#261-4).
  - Missing map_file / missing daily zip → None (correct skip: no data == no row; correct-0 at
    the per-ticker grain). A corrupt (non-zip) file → loud-WARN + None (whole-file unreadable).
conform_coarse is an OFFLINE data-prep tool, so #261 uses loud-SKIP-WITH-LOG at the row grain
(not a hard raise that would abort a multi-thousand-ticker conform) — the live engine path
(#261-1/2/5/6/8) hard-RAISES. The drop is VISIBLE in every case, never silent.
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


def test_read_daily_zip_corrupt_zip_loud_returns_none(coarse_env, capsys) -> None:
    # A corrupt (non-zip) file -> None, now with a LOUD logged reason (#261-3): the whole file is
    # unreadable (not one bad row), so there are no rows to salvage — but the ticker drop is
    # VISIBLE in stderr, not silent.
    coarse_env.write_corrupt_zip("corrupt")
    assert conform_coarse._read_daily_zip("corrupt") is None
    err = capsys.readouterr().err
    assert "corrupt" in err and "BadZipFile" in err and "#261-3" in err


def test_read_daily_zip_nonnumeric_close_loud_skips_row_keeps_ticker(coarse_env, capsys) -> None:
    # #261-3 (FLIPPED from strict-xfail): a non-numeric close no longer drops the WHOLE ticker
    # silently. The bad ROW is loud-SKIPPED-WITH-A-LOGGED-REASON (to stderr) and any VALID bar
    # is kept. Here the only bar is bad → {} (not None: the file IS readable, it just has no
    # usable bar), and the drop reason is VISIBLE in stderr (ticker + the offending row).
    coarse_env.write_daily("badclose", ["20250103 00:00,1,1,1,NOTANUM,1000000"])
    result = conform_coarse._read_daily_zip("badclose")
    assert result == {}  # bad row skipped, no valid bars remain (readable file → {} not None)
    err = capsys.readouterr().err
    assert "badclose" in err and "non-numeric daily row" in err and "#261-3" in err


def test_read_daily_zip_bad_row_keeps_following_valid_bar(coarse_env, capsys) -> None:
    # #261-3: the KEY regression — a bad row no longer loses the VALID bars after it. A
    # non-numeric row FOLLOWED by a valid bar yields the valid bar (the prior blanket-except
    # would have dropped BOTH). The skip of the bad row is logged loudly.
    coarse_env.write_daily("mix", ["20250102 00:00,1,1,1,NOTANUM,1000000", _VALID_BAR])
    result = conform_coarse._read_daily_zip("mix")
    assert result == {"20250103": (539.1, 1_000_000)}  # the valid bar SURVIVES
    assert "mix" in capsys.readouterr().err  # bad row's drop was logged


def test_read_daily_zip_truncated_row_loud_skips_row(coarse_env, capsys) -> None:
    # #261-3 (FLIPPED): a truncated row (too few cols) is loud-skipped-with-log, not a silent
    # whole-ticker drop. A following valid bar survives.
    coarse_env.write_daily("trunc", ["20250102 00:00,5391000", _VALID_BAR])  # row 1 truncated
    result = conform_coarse._read_daily_zip("trunc")
    assert result == {"20250103": (539.1, 1_000_000)}  # valid bar kept
    err = capsys.readouterr().err
    assert "trunc" in err and "malformed daily row" in err and "#261-3" in err


def test_read_daily_zip_header_row_loud_skips_keeps_real_bars(coarse_env, capsys) -> None:
    # #261-3 (FLIPPED): a stray HEADER row mixed into a daily zip is loud-skipped, and the REAL
    # bars after it SURVIVE (the prior blanket-except dropped the header AND every real bar).
    coarse_env.write_daily("hdr", ["Date,Open,High,Low,Close,Volume", _VALID_BAR])
    result = conform_coarse._read_daily_zip("hdr")
    assert result == {"20250103": (539.1, 1_000_000)}  # the real bar survives
    assert "hdr" in capsys.readouterr().err  # header row's skip was logged


def test_read_daily_zip_valid_bars_no_warn(coarse_env, capsys) -> None:
    # HAPPY-PATH REGRESSION (#261-3): a clean daily zip parses with NO warning (the guard is not
    # over-eager — valid rows never trigger the loud-skip log).
    coarse_env.write_daily("clean", [_VALID_BAR])
    assert conform_coarse._read_daily_zip("clean") == {"20250103": (539.1, 1_000_000)}
    assert capsys.readouterr().err == ""


def test_build_row_skips_negative_close_loud(coarse_env, capsys) -> None:
    # #261-4 (FLIPPED from strict-xfail + the ACTUAL-pin): build_row no longer EMITS a
    # negative-close / negative-DV row. A negative close is loud-SKIPPED-WITH-A-LOGGED-REASON
    # (returns None), so no degraded row is written into the universe file. The reason is VISIBLE.
    coarse_env.write_map("negc")
    daily = {"20250103": (-539.1, 1_000_000)}  # negative close (a corrupt bar)
    assert conform_coarse.build_row("negc", "20250103", daily) is None
    err = capsys.readouterr().err
    assert "negc" in err and "non-finite/non-positive close" in err and "#261-4" in err


def test_build_row_skips_nonfinite_close_loud(coarse_env, capsys) -> None:
    # #261-4: a non-finite (inf/nan) close is also loud-skipped (never written).
    coarse_env.write_map("infc")
    assert conform_coarse.build_row("infc", "20250103", {"20250103": (float("inf"), 1_000_000)}) is None
    assert conform_coarse.build_row("infc", "20250103", {"20250103": (float("nan"), 1_000_000)}) is None
    assert "non-finite/non-positive close" in capsys.readouterr().err


def test_build_row_valid_close_no_warn_emits_row(coarse_env, capsys) -> None:
    # HAPPY-PATH REGRESSION (#261-4): a valid positive finite close emits the 8-col row with NO
    # warning (the guard is not over-eager).
    coarse_env.write_map("good")
    row = conform_coarse.build_row("good", "20250103", {"20250103": (539.1, 1_000_000)})
    assert row is not None and len(row.split(",")) == 8
    assert capsys.readouterr().err == ""


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
