"""#416 George-context local BT runner.

Runs the named George-context variants from `sweeps.grids.george_context` against local LEAN,
using `strategies.champion_george_context` as the base module. Start with the FY2025 six-pack,
then run the 30-pack waves.

Usage:
  python3 scripts/run_416_george_context_sweep.py --pack six --workers 6
  python3 scripts/run_416_george_context_sweep.py --pack thirty --wave 1 --workers 6
  python3 scripts/run_416_george_context_sweep.py --pack thirty --workers 6
  python3 scripts/run_416_george_context_sweep.py --pack six --data-folder /Users/falk/projects/kumo-qc/data
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

from build.sweep_build import build_sweep_dist  # noqa: E402
from scripts.run_408_george_range_30 import (  # noqa: E402
    _LeanCliWarmupGate,
    _make_logged_gated_run_lean,
)
from sweeps.adapters.local_lean import LocalLeanRun, _default_find_result  # noqa: E402
from sweeps.adapters.qc_local_prod import _link_repo_storage  # noqa: E402
from sweeps.grids.george_context import (  # noqa: E402
    BASE_MODULE,
    GEORGE_ATTENTION_SOURCE,
    GeorgeSweepVariant,
    SECURITY_PROFILE_SOURCE,
    six_pack,
    thirty_pack,
)
from sweeps.types import ResultMetrics, SweepConfig, Window  # noqa: E402
from sweeps.warmup_cache.ensure import ensure_weekly_cache  # noqa: E402

WINDOWS = {
    "fy": Window(name="fy2025_full", start="2025-01-01", end="2025-12-31"),
    "q1": Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    "jan": Window(name="jan2025_proof", start="2025-01-13", end="2025-01-31"),
}

DEFAULT_MARKET_DATA = Path("/Users/falk/projects/kumo-qc/data")
GEORGE_RUNTIME_INPUTS = (
    Path(SECURITY_PROFILE_SOURCE),
    Path(GEORGE_ATTENTION_SOURCE),
)

SUMMARY_COLUMNS = [
    "variant_id",
    "family",
    "wave",
    "hypothesis",
    "sweep_config_hash",
    "window",
    "ok",
    "sharpe",
    "ret_pct",
    "dd_pct",
    "orders",
    "run_dir",
    "result_path",
    "error",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", choices=("six", "thirty"), default="six")
    parser.add_argument("--wave", type=int, choices=(1, 2, 3, 4, 5), default=None)
    parser.add_argument("--window", choices=sorted(WINDOWS), default="fy")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sweep-id", default=None)
    parser.add_argument(
        "--data-folder",
        type=Path,
        default=DEFAULT_MARKET_DATA if DEFAULT_MARKET_DATA.exists() else ROOT / "data",
        help="Explicit LEAN market-data folder to write into each generated project lean.json.",
    )
    parser.add_argument(
        "--no-cache-ensure",
        action="store_true",
        help="Skip idempotent weekly-cache ensure before running.",
    )
    return parser.parse_args()


def _data_fingerprint() -> str:
    manifest = ROOT / "data" / "MANIFEST.json"
    if not manifest.exists():
        return ""
    return str(json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint") or "")


def _window_attrs(window: Window) -> str:
    sy, sm, sd = (int(x) for x in window.start.split("-"))
    ey, em, ed = (int(x) for x in window.end.split("-"))
    return (
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        f"    START_DATE = ({sy}, {sm}, {sd})\n"
        f"    END_DATE = ({ey}, {em}, {ed})\n"
        "    LOG_ONLY_ACTIVE_PHASES = True\n"
        "    LOG_PHASE_METRICS = False\n"
        "    LOG_PHASE_DECISIONS_ACTIVE = False\n"
        "    LOG_INTRADAY_INJECT_EVENTS = False\n"
        "    LOG_TICK_EVENTS = False\n"
    )


def _copy_runtime_inputs(run_dir: Path) -> None:
    """Copy George context CSVs into /LeanCLI/data so strategy inputs are project-local."""
    for rel in GEORGE_RUNTIME_INPUTS:
        src = ROOT / rel
        if not src.exists():
            continue
        dest = run_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _rewrite_runtime_sources_for_container(source: str) -> str:
    """LEAN runs from /LeanCLI; source CSV attrs need container-absolute project paths."""
    for rel in GEORGE_RUNTIME_INPUTS:
        attr = (
            "SECURITY_PROFILE_SOURCE"
            if rel == Path(SECURITY_PROFILE_SOURCE)
            else "GEORGE_ATTENTION_SOURCE"
        )
        source = source.replace(
            f"    {attr} = {str(rel)!r}\n",
            f"    {attr} = {'/LeanCLI/' + str(rel)!r}\n",
        )
    return source


def _dist_builder(window: Window, data_fp: str, data_folder: Path) -> Any:
    def build(config: SweepConfig, cell_window: Window, run_dir: Path) -> str:
        if cell_window != window:
            raise ValueError(f"unexpected window {cell_window}; runner is pinned to {window}")
        build_sweep_dist(config, dist_dir=run_dir, base_module=BASE_MODULE)
        _copy_runtime_inputs(run_dir)
        marker = f"GEORGE_CONTEXT_SWEEP_MARKER {config.config_hash}"
        main = run_dir / "main.py"
        source = main.read_text(encoding="utf-8")
        source = _rewrite_runtime_sources_for_container(source)
        tail = source.split("class BCTAlgorithm")[-1]
        if "START_DATE" not in tail:
            source = source.replace(
                "    STRATEGY_CONFIG = STRATEGY_CONFIG\n",
                _window_attrs(window),
                1,
            )
        if data_fp and "WARMUP_WEEKLY_CACHE_FP" not in source:
            source += f"\nBCTAlgorithm.WARMUP_WEEKLY_CACHE_FP = {data_fp!r}\n"
        if marker not in source:
            source = f"# {marker}\n" + source
        main.write_text(source, encoding="utf-8")
        _link_repo_storage(run_dir)
        (run_dir / "lean.json").write_text(
            json.dumps(
                {
                    "description": "george-context sweep cell",
                    "parameters": {},
                    "data-folder": str(data_folder.expanduser().resolve()),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return marker

    return build


def _variants(args: argparse.Namespace) -> tuple[GeorgeSweepVariant, ...]:
    variants = six_pack() if args.pack == "six" else thirty_pack()
    if args.wave is not None:
        variants = tuple(v for v in variants if v.wave == args.wave)
    if args.limit is not None:
        variants = variants[: args.limit]
    return variants


def _report_dirs(sweep_id: str) -> tuple[Path, Path]:
    runs_root = ROOT / "sweeps" / "runs" / sweep_id
    report_dir = ROOT / "sweeps" / "reports" / sweep_id
    runs_root.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    for path, label in (
        (runs_root, f"{sweep_id}/"),
        (report_dir, f"{sweep_id}/"),
    ):
        readme = path / "README.md"
        if not readme.exists():
            readme.write_text(
                f"# {label}\n\nGenerated George-context sweep artifacts. Do not hand-edit run outputs.\n",
                encoding="utf-8",
            )
    return runs_root, report_dir


def _run_variant(
    variant: GeorgeSweepVariant,
    *,
    adapter: LocalLeanRun,
    window: Window,
) -> dict[str, Any]:
    run_dir = adapter._run_dir(variant.config, window)
    result_path = ""
    error = ""
    metrics = ResultMetrics(sharpe=0.0, ret_pct=0.0, dd_pct=0.0, orders=0)
    try:
        metrics = adapter(variant.config, window)
        result_path = str(_default_find_result(run_dir))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "variant_id": variant.variant_id,
        "family": variant.family,
        "wave": variant.wave,
        "hypothesis": variant.hypothesis,
        "sweep_config_hash": variant.config_hash,
        "window": window.name,
        "ok": not error,
        "sharpe": metrics.sharpe,
        "ret_pct": metrics.ret_pct,
        "dd_pct": metrics.dd_pct,
        "orders": metrics.orders,
        "run_dir": str(run_dir),
        "result_path": result_path,
        "error": error,
    }


def _write_summary(report_dir: Path, rows: Sequence[dict[str, Any]], manifest: dict[str, Any]) -> None:
    summary = report_dir / "summary.csv"
    with summary.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=SUMMARY_COLUMNS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# George Context Sweep Summary", ""]
    lines.append("| variant | ok | ret_pct | dd_pct | orders | sharpe |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            "| {variant_id} | {ok} | {ret_pct:.3f} | {dd_pct:.3f} | {orders} | {sharpe:.3f} |".format(
                **row
            )
        )
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = _args()
    variants = _variants(args)
    window = WINDOWS[args.window]
    sweep_id = args.sweep_id or f"george_context_{args.pack}_{window.name}"
    runs_root, report_dir = _report_dirs(sweep_id)
    data_fp = _data_fingerprint()
    data_folder = args.data_folder.expanduser().resolve()

    if data_fp and not args.no_cache_ensure:
        ensure_weekly_cache(
            data_fp,
            storage_dir=ROOT / "storage",
            cache_root=ROOT / "results" / "warmup_cache",
        )

    gate = _LeanCliWarmupGate()
    adapter = LocalLeanRun(
        dist_builder=_dist_builder(window, data_fp, data_folder),
        data_root=data_folder,
        runs_root=runs_root,
        marker_check=True,
        run_lean=_make_logged_gated_run_lean(gate, use_project_lean_config=True),
        find_result=_default_find_result,
        persist=None,
    )

    print(
        f"=== #416 George context sweep | pack={args.pack} wave={args.wave} "
        f"variants={len(variants)} workers={args.workers} window={window.name} ===",
        flush=True,
    )
    print(f"data_fingerprint={data_fp or 'unknown'}", flush=True)
    print(f"data_folder={data_folder}", flush=True)
    for variant in variants:
        print(f"  {variant.variant_id}: {variant.config_hash}", flush=True)

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_variant, variant, adapter=adapter, window=window): variant
            for variant in variants
        }
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(
                f"DONE {row['variant_id']} ok={row['ok']} ret={row['ret_pct']:.3f} "
                f"dd={row['dd_pct']:.3f} orders={row['orders']} error={row['error'][:120]}",
                flush=True,
            )

    rows.sort(key=lambda row: [v.variant_id for v in variants].index(str(row["variant_id"])))
    manifest = {
        "sweep_id": sweep_id,
        "pack": args.pack,
        "wave": args.wave,
        "window": asdict(window),
        "workers": args.workers,
        "variant_count": len(variants),
        "ok_count": sum(1 for row in rows if row["ok"]),
        "data_fingerprint": data_fp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports": {
            "summary_csv": str(report_dir / "summary.csv"),
            "summary_md": str(report_dir / "summary.md"),
        },
    }
    _write_summary(report_dir, rows, manifest)
    print(f"REPORT {report_dir}", flush=True)


if __name__ == "__main__":
    main()
