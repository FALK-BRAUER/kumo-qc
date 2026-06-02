"""Tests for the results-archive WIRING into the run adapters (#276b — the snapshotter is already
unit-tested in test_archive_snapshot.py; here we test that the cloud/local adapters CALL persist_run
with the right status mapping + orders_fetch + provenance, and that a persist failure stays LOUD).

ZERO real QC / LEAN: the cloud calls (deploy/run_backtest), the `/orders/read` fn, and the
write-destination are all INJECTED / MOCKED. The local reader runs against a fixture order-events
file on tmp_path. No keychain, no Docker, no spend.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from sweeps.adapters.cloud_lean import (
    ArchivePersister,
    CloudLeanRun,
    CloudResult,
    _cloud_status,
)
from sweeps.adapters.local_lean import (
    LocalLeanRun,
    make_local_persist,
    read_local_orders,
)
from sweeps.archive.config_serializer import (
    CONFIG_SERIALIZER_VERSION,
    TYPE_KEY,
    _jsonify,
    serialize_config,
    unjsonify,
)
from sweeps.archive.snapshot import RunStatus
from sweeps.enumerate import enumerate_catalog
from sweeps.types import CloudValidationError, SweepConfig, Window
from tests.sweeps.conftest import MOCK_CATALOG

W = Window(name="fy2025", start="2025-01-01", end="2025-12-31")


def _config() -> SweepConfig:
    return enumerate_catalog(MOCK_CATALOG)[0]  # type: ignore[arg-type]


def _stats(total_orders: int = 2, sharpe: float = 1.3) -> dict:
    return {
        "Total Orders": total_orders,
        "Sharpe Ratio": str(sharpe),
        "Net Profit": "10.0%",
        "Drawdown": "5.0%",
    }


# --------------------------------------------------------------------------- #
# 1. config → dict serializer
# --------------------------------------------------------------------------- #
def test_serialize_config_shape() -> None:
    cfg = _config()
    out = serialize_config(cfg)
    assert out["config_hash"] == cfg.config_hash
    assert out["name"] == cfg.config_hash  # defaults to the hash when no name supplied
    assert out["version"] == CONFIG_SERIALIZER_VERSION
    assert set(out.keys()) == {"name", "version", "config_hash", "phases"}
    phase = out["phases"]["signal"]
    assert phase["impl"] == "TwoAxisPhase"
    assert phase["params"] == {"alpha": 1, "beta": 0.1}
    assert phase["free_params"] == 2


def test_serialize_config_named() -> None:
    out = serialize_config(_config(), name="champion_intraday")
    assert out["name"] == "champion_intraday"


def test_serialize_config_injected_impl_param_is_json_safe() -> None:
    """#322 regression: a Params field whose VALUE is an injected dataclass (e.g. OracleSignal's
    predictor=DvRankPredictor(...)) must serialize to a JSON-safe dict — else persist_run's
    json.dumps raises 'Object of type DvRankPredictor is not JSON serializable' (caught on the
    first learned-dvrank smoke, post-assert_cloud_clean, in the archive persist). The injected
    object is recorded as {"__type__": <cls>, <field>: <val>} so result.json serializes AND the
    mine reads the booster's params (rank_cap) back."""
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class _Pred:
        min_score: int = 7
        rank_cap: int = 250

    from sweeps.types import PhaseChoice

    cfg = SweepConfig(choices=(PhaseChoice(
        kind="signal", impl_name="oracle_signal",
        params=(("min_score", 7), ("predictor", _Pred())), free_params=2,
    ),))
    out = serialize_config(cfg)
    # the whole thing must json.dumps without raising (the bug was a TypeError here).
    json.dumps(out, sort_keys=True)
    pred = out["phases"]["signal"]["params"]["predictor"]
    assert pred == {"__type__": "_Pred", "min_score": 7, "rank_cap": 250}


def test_serialize_config_deterministic() -> None:
    cfg = _config()
    a = json.dumps(serialize_config(cfg), sort_keys=True)
    b = json.dumps(serialize_config(cfg), sort_keys=True)
    assert a == b  # byte-stable for idempotent archive writes


# --- #9 storage-uniformity: _jsonify never-raises + the unjsonify round-trip ---------------

def test_jsonify_roundtrip_on_native_structures() -> None:
    """ROUND-TRIP CONTRACT: unjsonify(_jsonify(x)) == x for the round-trippable set (JSON-native
    scalars, dicts, lists, and arbitrary nesting thereof). Also survives a json dumps/loads cycle."""
    cases = [
        7, 3.14, "abc", True, None,
        {"a": 1, "b": [1, 2, {"c": "d"}]},
        [1, "x", {"k": [True, None, 2.5]}],
        {"nested": {"deep": {"list": [1, {"z": 9}]}}},
    ]
    for x in cases:
        j = _jsonify(x)
        assert json.loads(json.dumps(j, sort_keys=True)) == j  # JSON-native, byte-stable
        assert unjsonify(j) == x                                 # true inverse on the round-trip set


def test_jsonify_never_raises_on_non_native_scalars() -> None:
    """#9 contract: _jsonify NEVER hands json.dumps a non-serializable value — datetime/Path/set/
    Enum are coerced (one-way) instead of passed through to a TypeError that would evaporate the run."""
    import datetime as dt
    import enum
    from pathlib import Path

    class Color(enum.Enum):
        RED = "red"

    val = {
        "when": dt.datetime(2025, 6, 1, 9, 30),
        "day": dt.date(2025, 6, 1),
        "path": Path("/tmp/x/y.json"),
        "tags": {"b", "a", "c"},          # set → sorted list
        "color": Color.RED,                # Enum → .value
        "nums": (1, 2, 3),                 # tuple → list
    }
    j = _jsonify(val)
    json.dumps(j, sort_keys=True, allow_nan=False)  # MUST NOT raise
    assert j["when"] == "2025-06-01T09:30:00"
    assert j["day"] == "2025-06-01"
    assert j["path"] == "/tmp/x/y.json"
    assert j["tags"] == ["a", "b", "c"]   # sorted
    assert j["color"] == "red"
    assert j["nums"] == [1, 2, 3]


def test_jsonify_dataclass_roundtrips_to_field_dict() -> None:
    """A dataclass param flattens to {__type__: Name, ...fields}; unjsonify returns it as a plain
    field-dict (the mine reads fields by name — the class is NOT reconstructed, only the name kept)."""
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class _Pred:
        min_score: int = 7
        rank_cap: int = 250

    j = _jsonify({"predictor": _Pred(), "scalar": 5})
    assert j == {"predictor": {TYPE_KEY: "_Pred", "min_score": 7, "rank_cap": 250}, "scalar": 5}
    back = unjsonify(j)
    assert back == j  # field-dict survives; mine reads back["predictor"]["rank_cap"]
    assert back["predictor"]["rank_cap"] == 250


# --------------------------------------------------------------------------- #
# 2. cloud status mapping (_cloud_status classifies the assert FAILURES)
# --------------------------------------------------------------------------- #
def test_cloud_status_error_is_crashed() -> None:
    r = CloudResult(backtest_id="b", progress=1, error="boom", raw={})
    assert _cloud_status(r) is RunStatus.CRASHED


def test_cloud_status_partial_is_crashed() -> None:
    r = CloudResult(backtest_id="b", progress=0.4, error=None, raw={})
    assert _cloud_status(r) is RunStatus.CRASHED


def test_cloud_status_completed_but_failed_check_is_degraded() -> None:
    # completed (progress==1, no error) but failed a non-fatal liveness/finiteness check
    r = CloudResult(backtest_id="b", progress=1, error=None,
                    raw={"statistics": {"Total Orders": "0"}})
    assert _cloud_status(r) is RunStatus.COMPLETED_DEGRADED


# --------------------------------------------------------------------------- #
# 3. CloudLeanRun calls persist with the right status + the clean run persists CLEAN
# --------------------------------------------------------------------------- #
def _cloud_adapter(result: CloudResult, persist: ArchivePersister) -> CloudLeanRun:
    return CloudLeanRun(
        deploy=lambda c, w: "cid",
        run_backtest=lambda n, cid: result,
        persist=persist,
    )


def test_clean_cloud_run_persists_completed_clean() -> None:
    captured: list[tuple] = []

    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        captured.append((config, result, status))

    raw = {"statistics": _stats(), "progress": 1}
    res = CloudResult(backtest_id="bt-1", progress=1, error=None, raw=raw)
    _cloud_adapter(res, persist).fetch(_config(), W)
    assert len(captured) == 1
    assert captured[0][2] is RunStatus.COMPLETED_CLEAN
    assert captured[0][1].backtest_id == "bt-1"


def test_crashed_cloud_run_persists_crashed_then_raises() -> None:
    captured: list[RunStatus] = []

    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        captured.append(status)

    res = CloudResult(backtest_id="bt-2", progress=0.5, error="kaboom", raw={})
    with pytest.raises(CloudValidationError):
        _cloud_adapter(res, persist).fetch(_config(), W)
    assert captured == [RunStatus.CRASHED]  # archived BEFORE the winner is dropped


def test_empty_backtest_id_skips_persist_routine_drop_not_halt() -> None:
    # HQ edge: a deploy/submit FAILURE yields backtest_id="" (no run). persist MUST be SKIPPED
    # (nothing to archive) — not escalated into an ArchiveError data-integrity halt. The routine
    # CloudValidationError still re-raises (run-to-learn drops/retries it).
    called: list[RunStatus] = []

    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        called.append(status)  # must NOT be reached

    res = CloudResult(backtest_id="", progress=0.0, error="submit failed: ...", raw={})
    with pytest.raises(CloudValidationError):  # the routine dirty verdict, NOT ArchiveError
        _cloud_adapter(res, persist).fetch(_config(), W)
    assert called == [], "persist must be SKIPPED on an empty backtest_id (no run to archive)"


def test_degraded_cloud_run_persists_degraded_then_raises() -> None:
    captured: list[RunStatus] = []

    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        captured.append(status)

    res = CloudResult(backtest_id="bt-3", progress=1, error=None,
                      raw={"statistics": {"Total Orders": "0"}})
    with pytest.raises(CloudValidationError):
        _cloud_adapter(res, persist).fetch(_config(), W)
    assert captured == [RunStatus.COMPLETED_DEGRADED]


def test_cloud_run_without_persist_hook_still_works() -> None:
    # persist is OPTIONAL — a None hook must not break the run path.
    raw = {"statistics": _stats(), "progress": 1}
    res = CloudResult(backtest_id="bt-4", progress=1, error=None, raw=raw)
    CloudLeanRun(deploy=lambda c, w: "cid", run_backtest=lambda n, cid: res).fetch(_config(), W)


# --------------------------------------------------------------------------- #
# 4. persist FAILURE stays loud (not swallowed) — clean + dirty paths
# --------------------------------------------------------------------------- #
def test_persist_failure_on_clean_propagates() -> None:
    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        raise RuntimeError("archive disk full")

    raw = {"statistics": _stats(), "progress": 1}
    res = CloudResult(backtest_id="bt-5", progress=1, error=None, raw=raw)
    with pytest.raises(RuntimeError, match="archive disk full"):
        _cloud_adapter(res, persist).fetch(_config(), W)


def test_persist_failure_on_dirty_path_chains_onto_verdict() -> None:
    # The run is already dirty (CloudValidationError). A persist failure on the dirty path must
    # surface LOUD — chained onto the original verdict so neither is swallowed.
    def persist(*, config: SweepConfig, result: CloudResult, status: RunStatus) -> None:
        raise RuntimeError("archive write failed")

    res = CloudResult(backtest_id="bt-6", progress=0.3, error="crash", raw={})
    with pytest.raises(RuntimeError, match="archive write failed") as ei:
        _cloud_adapter(res, persist).fetch(_config(), W)
    assert isinstance(ei.value.__cause__, CloudValidationError)  # both preserved in the trace


# --------------------------------------------------------------------------- #
# 5. cloud orders_fetch closure pulls via the INJECTED qc orders fn (mocked) + persist_run wiring
# --------------------------------------------------------------------------- #
def _local_order_events(tmp_path: Path) -> Path:
    """A LEAN run dir with a *-order-events.json (events shape) + a result JSON carrying the tag."""
    rd = tmp_path / "backtests" / "2025-01-01_00-00-00"
    rd.mkdir(parents=True)
    events = [
        {"orderId": 1, "status": "submitted", "symbolValue": "AAPL", "fillPrice": 0.0,
         "fillQuantity": 0.0, "quantity": 100.0, "direction": "buy", "time": 1735794000.0},
        {"orderId": 1, "status": "filled", "symbolValue": "AAPL", "fillPrice": 100.0,
         "fillQuantity": 100.0, "quantity": 100.0, "direction": "buy", "time": 1735794000.0},
        {"orderId": 2, "status": "filled", "symbolValue": "AAPL", "fillPrice": 110.0,
         "fillQuantity": 100.0, "quantity": 100.0, "direction": "sell", "time": 1736196000.0},
    ]
    (rd / "123-order-events.json").write_text(json.dumps(events))
    result = {
        "statistics": _stats(),
        "orders": {
            "1": {"id": 1, "symbol": {"value": "AAPL"}, "tag":
                  "decision_score=8&decision_cond=11110111", "price": 100.0, "status": 3},
            "2": {"id": 2, "symbol": {"value": "AAPL"}, "tag": "stop hit", "price": 110.0,
                  "status": 3},
        },
    }
    rp = rd / "123.json"
    rp.write_text(json.dumps(result))
    return rp


def test_read_local_orders_reconstructs_order_shape(tmp_path: Path) -> None:
    rp = _local_order_events(tmp_path)
    orders = read_local_orders(rp)
    assert len(orders) == 2  # one buy order, one sell order (folded from filled events)
    buy = next(o for o in orders if o["quantity"] > 0)
    sell = next(o for o in orders if o["quantity"] < 0)
    assert buy["price"] == 100.0 and buy["status"] == "filled"
    assert sell["quantity"] == -100.0  # signed by direction
    assert "decision_score=8" in buy["tag"]  # tag merged in from the result JSON's orders map


def test_read_local_orders_missing_events_fails_loud(tmp_path: Path) -> None:
    rd = tmp_path / "backtests" / "x"
    rd.mkdir(parents=True)
    rp = rd / "1.json"
    rp.write_text(json.dumps({"statistics": _stats(), "orders": {}}))
    from sweeps.types import ResultParseError
    with pytest.raises(ResultParseError, match="order-events"):
        read_local_orders(rp)


def test_local_persist_closure_writes_durable_artifact(tmp_path: Path) -> None:
    rp = _local_order_events(tmp_path)
    dest = tmp_path / "archive"
    persist = make_local_persist(
        commit="abc1234", data_fingerprint="data-fp", objective_version="323.v1",
        dest_root=dest, clock=lambda: "2026-06-02T00:00:00+00:00",
    )
    cfg = _config()
    persist(config=cfg, result_path=rp, status=RunStatus.COMPLETED_CLEAN, window=W)

    run_dir = dest / cfg.config_hash / "123"  # backtest_id = result-JSON stem
    result_doc = json.loads((run_dir / "result.json").read_text())
    assert result_doc["env"] == "local"
    assert result_doc["status"] == "COMPLETED_CLEAN"
    assert result_doc["commit"] == "abc1234"
    assert result_doc["timestamp"] == "2026-06-02T00:00:00+00:00"
    assert result_doc["config"]["config_hash"] == cfg.config_hash
    # the trade paired from the reconstructed orders, with decision context from the merged tag
    lines = gzip.decompress((run_dir / "trades.jsonl.gz").read_bytes()).decode().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["symbol"] == "AAPL"
    assert row["decision_score"] == 8
    assert row["context_status"] == "OK"


def _local_all_open_events(tmp_path: Path) -> Path:
    """An ALL-OPEN backtest fixture: entries only, NO exits (the cut-losers/let-winners shape at a
    window that ends mid-trade — every winner is still open at end-of-data). 2 buys, 0 sells →
    0 CLOSED trades. Stats Total Orders=2. WITHOUT the censored-open wiring this is the
    EmptyTradesError (0 rows while orders>0); WITH it, the open lots become censored rows."""
    rd = tmp_path / "backtests" / "2025-06-02_00-00-00"
    rd.mkdir(parents=True)
    events = [
        {"orderId": 1, "status": "filled", "symbolValue": "AAPL", "fillPrice": 100.0,
         "fillQuantity": 100.0, "quantity": 100.0, "direction": "buy", "time": 1735794000.0},
        {"orderId": 2, "status": "filled", "symbolValue": "MSFT", "fillPrice": 200.0,
         "fillQuantity": 50.0, "quantity": 50.0, "direction": "buy", "time": 1736196000.0},
    ]
    (rd / "456-order-events.json").write_text(json.dumps(events))
    result = {
        "statistics": _stats(total_orders=2),
        "orders": {
            "1": {"id": 1, "symbol": {"value": "AAPL"}, "tag":
                  "decision_score=8&decision_cond=11110111", "price": 100.0, "status": 3},
            "2": {"id": 2, "symbol": {"value": "MSFT"}, "tag":
                  "decision_score=7&decision_cond=11110011", "price": 200.0, "status": 3},
        },
    }
    rp = rd / "456.json"
    rp.write_text(json.dumps(result))
    return rp


def test_local_persist_all_open_window_writes_censored_no_error(tmp_path: Path) -> None:
    """THE CENSORED-OPEN WIRING (#325 fix): an all-open window (entries, no exits) must NOT raise
    EmptyTradesError — make_local_persist derives end_of_data from the window + supplies an m2m_mark,
    so persist_run captures the open lots as CENSORED rows. (No local daily data on tmp_path → the
    mark is 'unavailable' / m2m_ret null — NEVER faked — but the censored rows ARE written, which is
    what defeats the silent-miss guard.)"""
    rp = _local_all_open_events(tmp_path)
    dest = tmp_path / "archive"
    persist = make_local_persist(
        commit="abc1234", data_fingerprint="data-fp", objective_version="323.v1",
        dest_root=dest, data_root=tmp_path / "data",  # no daily zips → m2m unavailable, not faked
        clock=lambda: "2026-06-02T00:00:00+00:00",
    )
    cfg = _config()
    # must NOT raise EmptyTradesError despite 0 closed trades + Total Orders=2
    persist(config=cfg, result_path=rp, status=RunStatus.COMPLETED_CLEAN, window=W)

    run_dir = dest / cfg.config_hash / "456"
    lines = gzip.decompress((run_dir / "trades.jsonl.gz").read_bytes()).decode().splitlines()
    assert len(lines) == 2, "both open lots must be captured as censored rows"
    rows = [json.loads(x) for x in lines]
    assert all(r["censored"] is True for r in rows), "all rows are open-at-end → censored"
    # m2m unavailable (no daily data) is recorded honestly, never faked
    assert all(r["m2m_ret"] is None for r in rows)
    result_doc = json.loads((run_dir / "result.json").read_text())
    assert result_doc["n_censored_trades"] == 2


# --------------------------------------------------------------------------- #
# 5b. make_cloud_run's persist closure: orders_fetch wraps the INJECTED qc orders fn (mocked),
#     and persist_run writes the durable artifact end-to-end with cloud provenance. ZERO real QC:
#     a fake qc_v2_cloud module is placed in sys.modules so the import inside make_cloud_run
#     resolves to it (the module reads the keychain at import — the fake has no such side effect).
# --------------------------------------------------------------------------- #
def test_make_cloud_run_persist_closure_uses_injected_orders_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    import types

    from build.cloud_package import BuildResult

    cfg = _config()
    orders_calls: list[str] = []

    # Fake qc_v2_cloud: `deploy()` (prod deploy closure calls it) + `orders(bid)` (the persist
    # closure's orders_fetch wraps it). No keychain side effect — the real module reads creds at
    # import; the fake does not.
    fake_q = types.ModuleType("qc_v2_cloud")

    def fake_orders(bid: str) -> list[dict]:
        orders_calls.append(bid)
        return [
            {"id": 1, "symbol": {"value": "AAPL"}, "price": 100.0, "quantity": 100.0,
             "status": 3, "type": 4, "tag": "decision_score=8&decision_cond=11110111",
             "lastFillTime": "2025-01-02T21:00:00Z",
             "events": [{"status": "filled", "fillPrice": 100.0, "fillQuantity": 100.0,
                         "direction": "buy"}]},
            {"id": 2, "symbol": {"value": "AAPL"}, "price": 110.0, "quantity": -100.0,
             "status": 3, "type": 2, "tag": "stop hit",
             "lastFillTime": "2025-01-05T21:00:00Z",
             "events": [{"status": "filled", "fillPrice": 110.0, "fillQuantity": -100.0,
                         "direction": "sell"}]},
        ]

    fake_q.orders = fake_orders          # type: ignore[attr-defined]
    fake_q.deploy = lambda: "compile-1"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "qc_v2_cloud", fake_q)

    # Mock build_sweep_dist so deploy() captures provenance WITHOUT building a real dist.
    br = BuildResult(config_hash=cfg.config_hash, data_fingerprint="data-fp",
                     git_commit="commit99", included=[], phase_markers={})
    import build.sweep_build as sb
    monkeypatch.setattr(sb, "build_sweep_dist", lambda config, *, dist_dir: br)

    from sweeps.adapters import qc_cloud_prod

    run = qc_cloud_prod.make_cloud_run(
        dist_root=tmp_path / "dists",
        archive_root=tmp_path / "archive",
        clock=lambda: "2026-06-02T12:00:00+00:00",
    )

    # Drive the PROD seam: deploy() (prod closure) captures provenance keyed by config_hash; then
    # the prod persist hook reads it back. (run_backtest's real poll loop sleeps 10s/iter — we
    # don't drive it; the persist hook is exercised directly with a clean CloudResult, exactly as
    # CloudLeanRun.fetch would call it on the clean path.)
    run.deploy(cfg, W)
    clean = CloudResult(backtest_id="bt-cloud-1", progress=1, error=None,
                        raw={"statistics": _stats()})
    run.persist(config=cfg, result=clean, status=RunStatus.COMPLETED_CLEAN)  # type: ignore[misc]

    assert orders_calls == ["bt-cloud-1"]  # orders_fetch wrapped q.orders(bid)
    run_dir = (tmp_path / "archive") / cfg.config_hash / "bt-cloud-1"
    doc = json.loads((run_dir / "result.json").read_text())
    assert doc["env"] == "cloud"
    assert doc["commit"] == "commit99"
    assert doc["data_fingerprint"] == "data-fp"
    assert doc["status"] == "COMPLETED_CLEAN"
    assert doc["config"]["config_hash"] == cfg.config_hash
    lines = gzip.decompress((run_dir / "trades.jsonl.gz").read_bytes()).decode().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["decision_score"] == 8


# --------------------------------------------------------------------------- #
# 6. LocalLeanRun calls the persist hook with the right status (clean + degraded)
# --------------------------------------------------------------------------- #
def _local_run(tmp_path: Path, *, persist, result_fixture: dict) -> LocalLeanRun:
    runs_root = tmp_path / "runs"
    data_root = tmp_path / "data"
    data_root.mkdir()

    def dist_builder(config: SweepConfig, window: Window, run_dir: Path) -> str:
        bt = run_dir / "backtests" / "ts"
        bt.mkdir(parents=True)
        (bt / "code").mkdir()
        (bt / "code" / "main.py").write_text("MARKER-OK")
        (bt / "999.json").write_text(json.dumps(result_fixture))
        return "MARKER-OK"

    def run_lean(run_dir: Path) -> int:
        return 0

    def find_result(run_dir: Path) -> Path:
        return run_dir / "backtests" / "ts" / "999.json"

    return LocalLeanRun(
        dist_builder=dist_builder, data_root=data_root, runs_root=runs_root,
        run_lean=run_lean, find_result=find_result, persist=persist,
    )


def test_local_clean_run_persists_completed_clean(tmp_path: Path) -> None:
    captured: list[RunStatus] = []

    def persist(*, config: SweepConfig, result_path: Path, status: RunStatus, window=None) -> None:
        captured.append(status)

    adapter = _local_run(tmp_path, persist=persist, result_fixture={"statistics": _stats()})
    adapter.run_result(_config(), W)
    assert captured == [RunStatus.COMPLETED_CLEAN]


def test_local_degraded_run_persists_degraded_then_raises(tmp_path: Path) -> None:
    from sweeps.types import DegradedDataError
    captured: list[RunStatus] = []

    def persist(*, config: SweepConfig, result_path: Path, status: RunStatus, window=None) -> None:
        captured.append(status)

    # 0-order result → parse_run_result flags is_degraded (full metric trio present so the parse
    # reaches the orders<=0 degraded check rather than raising on a missing metric).
    adapter = _local_run(tmp_path, persist=persist,
                         result_fixture={"statistics": _stats(total_orders=0)})
    with pytest.raises(DegradedDataError):
        adapter.run_result(_config(), W)
    assert captured == [RunStatus.COMPLETED_DEGRADED]


def test_local_persist_failure_propagates(tmp_path: Path) -> None:
    def persist(*, config: SweepConfig, result_path: Path, status: RunStatus, window=None) -> None:
        raise RuntimeError("local archive failed")

    adapter = _local_run(tmp_path, persist=persist, result_fixture={"statistics": _stats()})
    with pytest.raises(RuntimeError, match="local archive failed"):
        adapter.run_result(_config(), W)
