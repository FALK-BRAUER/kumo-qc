from types import SimpleNamespace

from scripts.run_408_george_range_30 import _parse_exit_events


def test_parse_exit_event_fields(tmp_path):
    stdout = tmp_path / "lean-stdout.txt"
    stdout.write_text(
        "2026 TRACE:: Log: EXIT_EVENT|2025-01-10|AAPL|event=PROACTIVE_STRENGTH_EXIT"
        "|module=exit.proactive_strength_exit|reason=target|days_held=9|qty=100.000000"
        "|entry_price=100.000000|exit_price=106.000000|pnl=600.000000"
        "|return_pct=0.060000|mfe_pct=0.060000|mae_pct=-0.010000"
        "|peak_return_pct=0.060000|giveback_from_peak_pct=0.000000\n",
        encoding="utf-8",
    )
    prepared = SimpleNamespace(
        spec=SimpleNamespace(variant_id="demo_variant"),
        config_hash="abc123",
    )

    rows = _parse_exit_events(stdout, prepared)

    assert rows == [
        {
            "variant_id": "demo_variant",
            "config_hash": "abc123",
            "event": "PROACTIVE_STRENGTH_EXIT",
            "date": "2025-01-10",
            "symbol": "AAPL",
            "module": "exit.proactive_strength_exit",
            "reason": "target",
            "order_id": None,
            "days_held": "9",
            "qty": "100.000000",
            "entry_price": "100.000000",
            "exit_price": "106.000000",
            "pnl": "600.000000",
            "return_pct": "0.060000",
            "mfe_pct": "0.060000",
            "mae_pct": "-0.010000",
            "peak_return_pct": "0.060000",
            "giveback_from_peak_pct": "0.000000",
            "raw": "EXIT_EVENT|2025-01-10|AAPL|event=PROACTIVE_STRENGTH_EXIT"
            "|module=exit.proactive_strength_exit|reason=target|days_held=9|qty=100.000000"
            "|entry_price=100.000000|exit_price=106.000000|pnl=600.000000"
            "|return_pct=0.060000|mfe_pct=0.060000|mae_pct=-0.010000"
            "|peak_return_pct=0.060000|giveback_from_peak_pct=0.000000",
        }
    ]


def test_parse_wrapped_exit_event_fields(tmp_path):
    stdout = tmp_path / "lean-stdout.txt"
    stdout.write_text(
        "20260607 23:22:45.680 TRACE:: Log: 2025-01-17 16:10:00 \n"
        "EXIT_EVENT|2025-01-17|JPM|event=PROACTIVE_STRENGTH_EXIT|module=exit.proactive_st\n"
        "rength_exit|reason=target|days_held=3|qty=16.000000|entry_price=243.875000|exit_\n"
        "price=259.410000|pnl=248.560000|return_pct=0.063701|mfe_pct=0.063701|mae_pct=0.0\n"
        "00000|peak_return_pct=0.063701|giveback_from_peak_pct=0.000000\n"
        "20260607 23:22:45.681 TRACE:: Log: next log line\n",
        encoding="utf-8",
    )
    prepared = SimpleNamespace(
        spec=SimpleNamespace(variant_id="demo_variant"),
        config_hash="abc123",
    )

    rows = _parse_exit_events(stdout, prepared)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "JPM"
    assert rows[0]["module"] == "exit.proactive_strength_exit"
    assert rows[0]["reason"] == "target"
    assert rows[0]["days_held"] == "3"
    assert rows[0]["exit_price"] == "259.410000"
    assert rows[0]["mae_pct"] == "0.000000"
    assert rows[0]["giveback_from_peak_pct"] == "0.000000"
