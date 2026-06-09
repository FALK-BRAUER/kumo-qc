"""Scanner-ranker local LEAN sweep runner.

Runs the #446/#448 scanner-ranker first pack against local LEAN. The learned model is expected
in repo storage as `storage/bct_lambdamart_qc_safe_v1.json`, which the local adapter symlinks into
the generated project ObjectStore path.

Usage:
  python3 scripts/run_scanner_ranker_sweep.py --window jan --workers 1 --only scanner_lambdamart_top10
  python3 scripts/run_scanner_ranker_sweep.py --window fy --workers 1
  python3 scripts/run_scanner_ranker_sweep.py --window fy --data-folder /Users/falk/projects/kumo-qc/data
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
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
from sweeps.grids.scanner_ranker import (  # noqa: E402
    BASE_MODULE,
    DEFAULT_MODEL_KEY,
    ScannerRankerVariant,
    first_pack,
)
from sweeps.types import ResultMetrics, SweepConfig, Window  # noqa: E402
from sweeps.warmup_cache.ensure import ensure_weekly_cache  # noqa: E402

WINDOWS = {
    "fy": Window(name="fy2025_full", start="2025-01-01", end="2025-12-31"),
    "q1": Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    "jan": Window(name="jan2025_proof", start="2025-01-13", end="2025-01-31"),
}

DEFAULT_MARKET_DATA = Path("/Users/falk/projects/kumo-qc/data")
DEFAULT_ARTIFACT_PATH = ROOT / "storage" / "bct_lambdamart_qc_safe_v1.json"

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
    "artifact_path",
    "artifact_sha256",
    "run_dir",
    "result_path",
    "error",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=sorted(WINDOWS), default="jan")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated variant ids to run; useful for smoke runs or retries.",
    )
    parser.add_argument("--sweep-id", default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=DEFAULT_ARTIFACT_PATH,
        help="Local JSON artifact path for variants using the default ObjectStore model key.",
    )
    parser.add_argument(
        "--allow-missing-artifact",
        action="store_true",
        help="Allow LambdaMART variants to run without the default artifact; useful only for fail-open tests.",
    )
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


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _dist_builder(window: Window, data_fp: str, data_folder: Path) -> Any:
    def build(config: SweepConfig, cell_window: Window, run_dir: Path) -> str:
        if cell_window != window:
            raise ValueError(f"unexpected window {cell_window}; runner is pinned to {window}")
        build_sweep_dist(config, dist_dir=run_dir, base_module=BASE_MODULE)
        marker = f"SCANNER_RANKER_SWEEP_MARKER {config.config_hash}"
        main = run_dir / "main.py"
        source = main.read_text(encoding="utf-8")
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
                    "description": "scanner-ranker sweep cell",
                    "parameters": {},
                    "data-folder": str(data_folder.expanduser().resolve()),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return marker

    return build


def _variants(args: argparse.Namespace) -> tuple[ScannerRankerVariant, ...]:
    variants = tuple(first_pack())
    if args.only:
        wanted = {part.strip() for part in args.only.split(",") if part.strip()}
        found = {v.variant_id for v in variants}
        missing = sorted(wanted - found)
        if missing:
            raise SystemExit(f"--only requested unknown variants: {', '.join(missing)}")
        variants = tuple(v for v in variants if v.variant_id in wanted)
    if args.limit is not None:
        variants = variants[: args.limit]
    return variants


def _needs_default_artifact(variant: ScannerRankerVariant) -> bool:
    runtime = variant.config.runtime_dict()
    return (
        bool(runtime.get("scanner_ranker_enabled"))
        and str(runtime.get("scanner_ranker_model_path") or "") == DEFAULT_MODEL_KEY
    )


def _validate_artifact(args: argparse.Namespace, variants: Sequence[ScannerRankerVariant]) -> tuple[Path, str]:
    artifact = args.artifact.expanduser().resolve()
    if not args.allow_missing_artifact and any(_needs_default_artifact(variant) for variant in variants):
        if not artifact.exists():
            raise SystemExit(
                f"scanner ranker artifact missing: {artifact}. "
                "Export it first or pass --allow-missing-artifact for a fallback-only smoke."
            )
        expected = DEFAULT_ARTIFACT_PATH.resolve()
        if artifact != expected:
            raise SystemExit(
                f"artifact must live at {expected} for {DEFAULT_MODEL_KEY}; got {artifact}"
            )
    return artifact, _file_sha256(artifact)


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
                f"# {label}\n\nGenerated scanner-ranker sweep artifacts. Do not hand-edit run outputs.\n",
                encoding="utf-8",
            )
    return runs_root, report_dir


def _run_variant(
    variant: ScannerRankerVariant,
    *,
    adapter: LocalLeanRun,
    window: Window,
    artifact_path: Path,
    artifact_sha256: str,
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
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha256,
        "run_dir": str(run_dir),
        "result_path": result_path,
        "error": error,
    }


def _write_summary(report_dir: Path, rows: Sequence[dict[str, Any]], manifest: dict[str, Any]) -> None:
    summary = report_dir / "summary.csv"
    with summary.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=SUMMARY_COLUMNS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    lines = ["# Scanner Ranker Sweep Summary", ""]
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
    artifact_path, artifact_sha256 = _validate_artifact(args, variants)
    window = WINDOWS[args.window]
    sweep_id = args.sweep_id or f"scanner_ranker_first_pack_{window.name}"
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
        f"=== scanner-ranker sweep | variants={len(variants)} workers={args.workers} "
        f"window={window.name} ===",
        flush=True,
    )
    print(f"artifact={artifact_path} sha256={artifact_sha256[:12] or 'missing'}", flush=True)
    print(f"data_fingerprint={data_fp or 'unknown'}", flush=True)
    print(f"data_folder={data_folder}", flush=True)
    for variant in variants:
        print(f"  {variant.variant_id}: {variant.config_hash}", flush=True)

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_variant,
                variant,
                adapter=adapter,
                window=window,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
            ): variant
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

    order = {variant.variant_id: idx for idx, variant in enumerate(variants)}
    rows.sort(key=lambda row: order[str(row["variant_id"])])
    manifest = {
        "sweep_id": sweep_id,
        "window": asdict(window),
        "workers": args.workers,
        "variant_count": len(variants),
        "ok_count": sum(1 for row in rows if row["ok"]),
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha256,
        "default_model_key": DEFAULT_MODEL_KEY,
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
