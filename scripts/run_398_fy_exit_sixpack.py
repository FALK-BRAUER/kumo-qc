"""#398 FY2025 George-style exit six-pack.

Runs the six exit-management blueprints in one process so the existing WarmupGate is actually
shared across all concurrent LEAN jobs. The six cells are submitted together; the gate meters only
the memory-heavy warmup phase, then post-warmup execution overlaps.

Usage:
  python3 scripts/run_398_fy_exit_sixpack.py
  WARMUP_GATE_CAPACITY=2 python3 scripts/run_398_fy_exit_sixpack.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.cloud_package as cp  # noqa: E402
from scripts.run_386_arm_direct import WINDOWS, _cache_attrs  # noqa: E402
from sweeps.adapters.local_lean import WarmupGate, _default_find_result  # noqa: E402


MODULES = (
    "strategies.blueprints.scenario_exit_proactive",
    "strategies.blueprints.scenario_exit_proactive_giveback_tight",
    "strategies.blueprints.scenario_exit_proactive_scratch",
    "strategies.blueprints.scenario_exit_proactive_scratch_fast",
    "strategies.blueprints.scenario_exit_proactive_scratch_patient",
    "strategies.blueprints.scenario_exit_proactive_scratch_tight_risk",
)


def _selected_modules() -> tuple[str, ...]:
    raw = os.environ.get("KUMO_398_MODULES", "").strip()
    if not raw:
        return MODULES
    names = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = sorted(set(names).difference(MODULES))
    if unknown:
        raise SystemExit(f"unknown KUMO_398_MODULES entries: {unknown}")
    return names


@dataclass(frozen=True, slots=True)
class PreparedRun:
    module: str
    tag: str
    config_hash: str
    data_fingerprint: str
    run_dir: Path


@dataclass(frozen=True, slots=True)
class RunOutcome:
    module: str
    tag: str
    config_hash: str
    run_dir: Path
    result_path: Path | None
    rc: int
    status: str
    net_profit: str | None
    drawdown: str | None
    total_orders: str | None
    sharpe: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.rc == 0 and self.status == "Completed" and self.net_profit is not None


class _LoggedPopen:
    def __init__(self, argv: list[str], env: dict[str, str], stdout_path: Path) -> None:
        self._fh = stdout_path.open("w", encoding="utf-8")
        self._proc = subprocess.Popen(
            argv,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.stdout = self._tee_stdout()
        self.returncode: int | None = None

    def _tee_stdout(self) -> Any:
        try:
            stream = self._proc.stdout
            if stream is not None:
                for line in stream:
                    self._fh.write(line)
                    self._fh.flush()
                    yield line
        finally:
            self._fh.close()

    def wait(self) -> int:
        self.returncode = int(self._proc.wait())
        return self.returncode


def _make_logged_gated_run_lean(gate: WarmupGate) -> Any:
    def run_lean(project_dir: Path) -> int:
        env = dict(os.environ)
        env.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
        argv = ["lean", "backtest", "--no-update", str(project_dir)]
        return gate.run(
            argv,
            env,
            popen=lambda: _LoggedPopen(argv, env, project_dir / "lean-stdout.txt"),
        )

    return run_lean


def _prepare(module: str, *, warmup_days: int, full_warmup: bool) -> PreparedRun:
    win = WINDOWS["fy"]
    tag = module.split(".")[-1]
    run = _ROOT / "sweeps" / "runs" / f"direct_{tag}" / win.name
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)

    res = cp.build(module, dist_dir=run)
    arm_files = [f for f in res.included if "arm" in f.lower()]
    if not arm_files:
        raise RuntimeError(f"{module}: arm phase missing from dist; aborting non-live proof")

    extra_attrs = _cache_attrs(res, warmup_days=warmup_days, full_warmup=full_warmup)
    sy, sm, sd = (int(x) for x in win.start.split("-"))
    ey, em, ed = (int(x) for x in win.end.split("-"))
    inject = (
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        f"    START_DATE = ({sy}, {sm}, {sd})\n"
        f"    END_DATE = ({ey}, {em}, {ed})\n"
        "    CONTINUOUS_WEEKLY = True\n"
    )
    for key, value in extra_attrs.items():
        inject += f"    {key} = {value!r}\n"
    inject += "    LOG_ONLY_ACTIVE_PHASES = True\n"
    inject += "    LOG_TICK_EVENTS = False\n"

    main_py = run / "main.py"
    source = main_py.read_text(encoding="utf-8")
    anchor = "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
    if anchor not in source:
        raise RuntimeError(f"{module}: inject anchor missing in {main_py}")
    main_py.write_text(source.replace(anchor, inject, 1), encoding="utf-8")

    (run / "lean.json").write_text('{ "description": "398 fy exit sixpack", "parameters": {} }\n')
    data = run / "data"
    if not data.exists():
        data.symlink_to(_ROOT / "data")
    return PreparedRun(
        module=module,
        tag=tag,
        config_hash=res.config_hash,
        data_fingerprint=res.data_fingerprint,
        run_dir=run,
    )


def _result_status(doc: dict[str, Any]) -> str:
    state = doc.get("state") or doc.get("State") or {}
    if isinstance(state, dict):
        raw = state.get("Status") or state.get("status")
        if raw:
            return str(raw)
    if doc.get("statistics") or doc.get("Statistics"):
        return "Completed"
    return "Unknown"


def _statistics(doc: dict[str, Any]) -> dict[str, Any]:
    stats = doc.get("statistics") or doc.get("Statistics") or {}
    return stats if isinstance(stats, dict) else {}


def _summarize(prepared: PreparedRun, *, rc: int) -> RunOutcome:
    result_path: Path | None = None
    try:
        result_path = _default_find_result(prepared.run_dir)
        doc = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return RunOutcome(
            module=prepared.module,
            tag=prepared.tag,
            config_hash=prepared.config_hash,
            run_dir=prepared.run_dir,
            result_path=result_path,
            rc=rc,
            status="MissingResult",
            net_profit=None,
            drawdown=None,
            total_orders=None,
            sharpe=None,
            error=str(exc),
        )

    stats = _statistics(doc)
    state = doc.get("state") or doc.get("State") or {}
    runtime_error = state.get("RuntimeError") if isinstance(state, dict) else None
    stacktrace = state.get("StackTrace") if isinstance(state, dict) else None
    error = runtime_error or stacktrace or doc.get("error") or doc.get("Error")
    return RunOutcome(
        module=prepared.module,
        tag=prepared.tag,
        config_hash=prepared.config_hash,
        run_dir=prepared.run_dir,
        result_path=result_path,
        rc=rc,
        status=_result_status(doc),
        net_profit=str(stats.get("Net Profit")) if stats.get("Net Profit") is not None else None,
        drawdown=str(stats.get("Drawdown")) if stats.get("Drawdown") is not None else None,
        total_orders=str(stats.get("Total Orders")) if stats.get("Total Orders") is not None else None,
        sharpe=str(stats.get("Sharpe Ratio")) if stats.get("Sharpe Ratio") is not None else None,
        error=str(error) if error else None,
    )


def _run_one(prepared: PreparedRun, run_lean: Any) -> RunOutcome:
    print(f"START|{prepared.tag}|hash={prepared.config_hash}|dir={prepared.run_dir}", flush=True)
    rc = int(run_lean(prepared.run_dir))
    outcome = _summarize(prepared, rc=rc)
    print(
        "RESULT|"
        f"{outcome.tag}|rc={outcome.rc}|status={outcome.status}|"
        f"net={outcome.net_profit}|dd={outcome.drawdown}|orders={outcome.total_orders}|"
        f"path={outcome.result_path}",
        flush=True,
    )
    return outcome


def main() -> None:
    modules = _selected_modules()
    warmup_days = int(os.environ.get("KUMO_386_WARMUP_DAYS", "320"))
    full_warmup = os.environ.get("KUMO_398_FULL_WARMUP", "0") == "1"
    workers = int(os.environ.get("KUMO_398_WORKERS", str(len(modules))))
    if not 1 <= workers <= len(modules):
        raise SystemExit(f"KUMO_398_WORKERS must be between 1 and {len(modules)}, got {workers}")

    print(
        "=== #398 FY2025 EXIT SIXPACK | "
        f"modules={len(modules)} | workers={workers} | warmup_days={warmup_days} | "
        f"full_warmup={full_warmup} | gate_capacity={os.environ.get('WARMUP_GATE_CAPACITY', '1')} ===",
        flush=True,
    )
    prepared = [
        _prepare(module, warmup_days=warmup_days, full_warmup=full_warmup)
        for module in modules
    ]
    fps = sorted({p.data_fingerprint for p in prepared})
    print(f"DATA_FP|{','.join(fps)}", flush=True)
    for p in prepared:
        print(f"PREPARED|{p.tag}|hash={p.config_hash}|fp={p.data_fingerprint}", flush=True)

    gate = WarmupGate()
    run_lean = _make_logged_gated_run_lean(gate)
    outcomes: list[RunOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_one, p, run_lean) for p in prepared]
        for fut in as_completed(futures):
            outcomes.append(fut.result())

    outcomes.sort(key=lambda o: modules.index(o.module))
    print("\n=== FY2025 EXIT SIXPACK RESULTS ===", flush=True)
    print("tag,hash,rc,status,net_profit,drawdown,total_orders,sharpe,result_path", flush=True)
    for out in outcomes:
        print(
            f"{out.tag},{out.config_hash},{out.rc},{out.status},"
            f"{out.net_profit},{out.drawdown},{out.total_orders},{out.sharpe},{out.result_path}",
            flush=True,
        )
    failures = [o for o in outcomes if not o.ok]
    if failures:
        print("\n=== FAILURES ===", flush=True)
        for out in failures:
            print(f"{out.tag}: rc={out.rc} status={out.status} error={out.error}", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
