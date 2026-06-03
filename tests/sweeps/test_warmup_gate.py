"""WarmupGate (C) tests — serialize the memory-heavy warmup phase, keep execution parallel.

ZERO real LEAN / Docker / subprocess: a FakeProc yields a hand-authored stdout line stream and a
returncode. The gate's release-on-marker / release-on-exit logic + the capacity-1 serialization
guarantee are asserted deterministically (no timing flakiness — threads coordinate via Events).
"""
from __future__ import annotations

import threading
import time

from sweeps.adapters.local_lean import WarmupGate, make_gated_run_lean


class FakeProc:
    """Stand-in for subprocess.Popen: .stdout is an iterable of lines, .wait() returns rc."""
    def __init__(self, lines, rc=0, on_wait=None):
        self.stdout = iter(lines)
        self.returncode = rc
        self._on_wait = on_wait

    def wait(self):
        if self._on_wait is not None:
            self._on_wait()
        return self.returncode


def _gate_available(gate: WarmupGate) -> bool:
    """True if the gate can be acquired right now (non-blocking probe); restores state if it could."""
    got = gate._sem.acquire(blocking=False)
    if got:
        gate._sem.release()
    return got


def test_releases_on_warmup_marker_before_exit() -> None:
    """The gate frees the warmup lane the instant the marker is seen — NOT at process exit. Proven by
    a wait() that checks gate availability mid-drain: by the time wait() runs (post-marker), the lane
    is already free."""
    gate = WarmupGate()
    seen_free_at_wait = {}

    def on_wait():
        seen_free_at_wait["free"] = _gate_available(gate)

    proc = FakeProc(
        ["loading 50%", "Algorithm finished warming up.", "trading bar 1", "trading bar 2"],
        rc=0, on_wait=on_wait,
    )
    rc = gate.run(["lean"], {}, popen=lambda: proc)
    assert rc == 0
    assert seen_free_at_wait["free"] is True  # lane freed at the marker, before exit
    assert _gate_available(gate) is True       # still free after


def test_releases_on_exit_when_no_marker() -> None:
    """A cell that dies mid-warmup (OOM) never emits the marker — the gate must still free on exit, or
    the next cell deadlocks forever."""
    gate = WarmupGate()
    proc = FakeProc(["loading 50%", "loading 54%"], rc=1)  # killed mid-warmup, no marker
    rc = gate.run(["lean"], {}, popen=lambda: proc)
    assert rc == 1
    assert _gate_available(gate) is True  # freed on exit despite no marker


def test_no_double_release() -> None:
    """Marker + clean exit must release exactly once (capacity stays 1, not inflated to 2)."""
    gate = WarmupGate()
    proc = FakeProc(["Algorithm finished warming up.", "done"], rc=0)
    gate.run(["lean"], {}, popen=lambda: proc)
    # capacity is 1: a single acquire must succeed and a second must then block (not be available).
    assert gate._sem.acquire(blocking=False) is True
    assert gate._sem.acquire(blocking=False) is False  # would be True if release double-counted
    gate._sem.release()


def test_capacity_one_serializes_warmup() -> None:
    """THE GUARANTEE: with capacity 1, a second cell cannot ENTER its warmup region until the first
    cell passes its marker. Cell A blocks inside warmup (its stdout stalls before the marker) until
    we let it proceed; cell B's run() must not start its process until A releases."""
    gate = WarmupGate()
    a_in_warmup = threading.Event()
    let_a_finish_warmup = threading.Event()
    b_started_proc = threading.Event()

    def a_lines():
        a_in_warmup.set()
        let_a_finish_warmup.wait(2.0)          # A holds the lane here (mid-warmup)
        yield "Algorithm finished warming up."  # ...then passes the marker -> releases the gate
        yield "trading"

    def b_popen():
        b_started_proc.set()  # B's process only starts AFTER B acquires the gate
        return FakeProc(["Algorithm finished warming up."], rc=0)

    ta = threading.Thread(target=lambda: gate.run(["lean", "A"], {}, popen=lambda: FakeProc(a_lines(), rc=0)))
    tb = threading.Thread(target=lambda: gate.run(["lean", "B"], {}, popen=b_popen))
    ta.start()
    assert a_in_warmup.wait(2.0)
    tb.start()
    # B must be BLOCKED on the gate (A holds it) — its process hasn't started.
    time.sleep(0.2)
    assert not b_started_proc.is_set(), "B entered warmup while A still held the gate — not serialized"
    # let A finish warmup -> releases gate -> B proceeds.
    let_a_finish_warmup.set()
    assert b_started_proc.wait(2.0), "B never started after A released the gate"
    ta.join(2.0)
    tb.join(2.0)


def test_make_gated_run_lean_uses_gate(monkeypatch) -> None:
    """make_gated_run_lean builds a (project_dir)->int RunLean that routes through the gate with the
    Docker host env fix + the right argv."""
    gate = WarmupGate()
    captured = {}

    def fake_run(argv, env, popen=None):
        captured["argv"] = argv
        captured["docker_host"] = env.get("DOCKER_HOST")
        return 0

    monkeypatch.setattr(gate, "run", fake_run)
    run_lean = make_gated_run_lean(gate)
    from pathlib import Path
    rc = run_lean(Path("/tmp/projX"))
    assert rc == 0
    assert captured["argv"] == ["lean", "backtest", "/tmp/projX"]
    assert "docker.sock" in captured["docker_host"]
