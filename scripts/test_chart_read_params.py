#!/usr/bin/env python3
"""Test that chart-read sends count + time-range params (#285).

Verifies the POST body structure without hitting the real API (unit test).
For live verification against a real backtest, run:
  python3 scripts/qc_v2_cloud.py chart <backtestId> Universe /tmp/test-chart.json
Expected: series with >1 data points (was returning 1 point before the fix).
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the module under test
_spec = __import__("importlib.util").util.spec_from_file_location(
    "qcv2", str(Path(__file__).resolve().parent / "qc_v2_cloud.py"))
assert _spec and _spec.loader
qcv2 = __import__("importlib.util").util.module_from_spec(_spec)
_spec.loader.exec_module(qcv2)


def test_chart_read_params() -> None:
    """Verify chart() sends count, start, end in the POST body."""
    captured_bodies = []
    
    def mock_post(path: str, body: dict) -> dict:
        captured_bodies.append((path, body))
        if path == "/backtests/chart/read":
            return {"success": True, "chart": {"series": {}}}
        return {"success": True}
    
    # Patch ensure_project to no-op (avoids keychain/auth)
    qcv2.PID = 12345
    
    with patch.object(qcv2, 'post', side_effect=mock_post):
        result = qcv2.chart("test-bt-id", "Universe")
    
    assert result is not None, "chart() should succeed with mock"
    assert len(captured_bodies) >= 1, "Should have made at least one POST call"
    
    chart_calls = [b for p, b in captured_bodies if p == "/backtests/chart/read"]
    assert len(chart_calls) >= 1, "Should have called /backtests/chart/read"
    
    body = chart_calls[0]
    assert "count" in body, "POST body must include 'count'"
    assert "start" in body, "POST body must include 'start'"
    assert "end" in body, "POST body must include 'end'"
    assert body["count"] == 4000, f"count should be 4000, got {body['count']}"
    assert body["start"] == 0, f"start should be 0, got {body['start']}"
    assert isinstance(body["end"], int), f"end should be int (unix timestamp), got {type(body['end'])}"
    assert body["end"] > 1700000000, f"end should be a recent unix timestamp, got {body['end']}"
    
    print("✅ All assertions passed:")
    print(f"   count={body['count']}, start={body['start']}, end={body['end']}")
    print(f"   → will retrieve full series (up to 4000 pts) instead of 1 point")


if __name__ == "__main__":
    test_chart_read_params()
