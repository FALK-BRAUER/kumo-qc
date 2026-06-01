"""tests/conftest.py — test-suite-wide pytest configuration.

Registers the `gdata` marker (#260): the local-LEAN real-data integration gate class, distinct
from the FakeQC logic gates. The marker makes these tests selectable (`-m gdata` / `-m "not
gdata"`) and is READY FOR GATE WIRING — the gate.py + nightly-CI wiring (#250/#255) is a
separate follow-up and is intentionally NOT done here (tests-only lane).
"""
from __future__ import annotations


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "gdata: real-data (local-LEAN) integration gate — runs the REAL selection/warmup/score "
        "path over real on-disk data (skips when the gitignored data/ tree is absent).",
    )
