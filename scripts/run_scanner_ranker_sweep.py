"""Scanner-ranker local LEAN sweep runner.

Runs the #446/#448 scanner-ranker first pack against local LEAN. The learned model is expected
in repo storage as `storage/bct_lambdamart_qc_safe_v1.json`, which the local adapter symlinks into
the generated project ObjectStore path.

Usage:
  python3 scripts/run_scanner_ranker_sweep.py --window jan --workers 1 --only scanner_lambdamart_top10
  python3 scripts/run_scanner_ranker_sweep.py --window fy --workers 1
  python3 scripts/run_scanner_ranker_sweep.py --pack top_x_expansion --window fy --workers 1
  KUMO_QC_DATA_FOLDER=~/projects/kumo-qc/data python3 scripts/run_scanner_ranker_sweep.py --window fy
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
os.environ.setdefault("DOCKER_HOST", f"unix://{Path.home() / '.docker' / 'run' / 'docker.sock'}")

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
    PACKS,
    ScannerRankerVariant,
)
from sweeps.types import ResultMetrics, SweepConfig, Window  # noqa: E402
from sweeps.warmup_cache.ensure import ensure_weekly_cache  # noqa: E402
from runtime.scanner_ranker import (  # noqa: E402
    ScannerCandidateRow,
    ScannerRankerError,
    load_scanner_model_artifact,
    rank_scanner_panel,
)

WINDOWS = {
    "fy": Window(name="fy2025_full", start="2025-01-01", end="2025-12-31"),
    "q1": Window(name="w1_2025q1", start="2025-01-01", end="2025-03-31"),
    "jan": Window(name="jan2025_proof", start="2025-01-13", end="2025-01-31"),
}

DEFAULT_MARKET_DATA = Path(
    os.environ.get("KUMO_QC_DATA_FOLDER", str(Path.home() / "projects" / "kumo-qc" / "data"))
)
DEFAULT_ARTIFACT_PATH = ROOT / "storage" / "bct_lambdamart_qc_safe_v1.json"

SUMMARY_COLUMNS = [
    "variant_id",
    "family",
    "wave",
    "base_module",
    "hypothesis",
    "sweep_config_hash",
    "window",
    "ok",
    "sharpe",
    "ret_pct",
    "dd_pct",
    "orders",
    "realized_net",
    "unrealized",
    "closed_trades",
    "closed_wins",
    "closed_losses",
    "closed_win_rate",
    "artifact_path",
    "artifact_sha256",
    "run_dir",
    "result_path",
    "error",
]


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", choices=sorted(PACKS), default="first")
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


def _repo_ref(path: Path | str) -> str:
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _data_fingerprint(data_folder: Path) -> str:
    manifest = data_folder.expanduser().resolve() / "MANIFEST.json"
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


def _dist_builder(
    window: Window,
    data_fp: str,
    data_folder: Path,
    base_module: str = BASE_MODULE,
) -> Any:
    def build(config: SweepConfig, cell_window: Window, run_dir: Path) -> str:
        if cell_window != window:
            raise ValueError(f"unexpected window {cell_window}; runner is pinned to {window}")
        build_sweep_dist(config, dist_dir=run_dir, base_module=base_module)
        marker = f"SCANNER_RANKER_SWEEP_MARKER {config.config_hash} {base_module}"
        main = run_dir / "main.py"
        source = main.read_text(encoding="utf-8")
        tail = source.split("class BCTAlgorithm")[-1]
        if "START_DATE" not in tail:
            anchor = "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
            if anchor not in source:
                raise RuntimeError(f"window injection anchor missing in {main}")
            source = source.replace(
                anchor,
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
    variants = tuple(PACKS[args.pack]())
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
    needs_default = any(_needs_default_artifact(variant) for variant in variants)
    if needs_default:
        if not artifact.exists():
            if args.allow_missing_artifact:
                return artifact, ""
            raise SystemExit(
                f"scanner ranker artifact missing: {artifact}. "
                "Export it first or pass --allow-missing-artifact for a fallback-only smoke."
            )
        expected = DEFAULT_ARTIFACT_PATH.resolve()
        if artifact != expected:
            raise SystemExit(
                f"artifact must live at {expected} for {DEFAULT_MODEL_KEY}; got {artifact}"
            )
        try:
            model = load_scanner_model_artifact(str(artifact))
            zero_features = {name: 0.0 for name in model.feature_names}
            rank_scanner_panel(
                [ScannerCandidateRow(ticker="ARTIFACT_PRECHECK", features=zero_features)],
                model,
                top_x=1,
            )
        except ScannerRankerError as exc:
            raise SystemExit(f"scanner ranker artifact invalid: {exc}") from exc
    return artifact, _file_sha256(artifact)


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value)


def _needs_variant_run_roots(variants: Sequence[ScannerRankerVariant]) -> bool:
    config_hashes = [variant.config_hash for variant in variants]
    return (
        len({variant.base_module for variant in variants}) > 1
        or len(set(config_hashes)) != len(config_hashes)
    )


def _variant_runs_root(
    runs_root: Path,
    variant: ScannerRankerVariant,
    *,
    isolate_run_dirs: bool,
) -> Path:
    if not isolate_run_dirs:
        return runs_root
    variant_root = runs_root / _safe_path_part(variant.variant_id)
    variant_root.mkdir(parents=True, exist_ok=True)
    readme = variant_root / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {variant.variant_id}\n\nGenerated isolated LEAN run artifacts for this scanner sweep cell.\n",
            encoding="utf-8",
        )
    return variant_root


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


def _lookup_path(doc: dict[str, Any], *path: str) -> Any:
    current: Any = doc
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _first_value(doc: dict[str, Any], paths: Sequence[tuple[str, ...]]) -> Any:
    for path in paths:
        value = _lookup_path(doc, *path)
        if value not in (None, ""):
            return value
    return ""


def _as_int(value: Any) -> int | str:
    if value in (None, ""):
        return ""
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return ""


def _closed_win_rate(wins: int | str, trades: int | str) -> float | str:
    if not isinstance(wins, int) or not isinstance(trades, int) or trades <= 0:
        return ""
    return wins / trades * 100.0


def _empty_diagnostics() -> dict[str, Any]:
    return {
        "realized_net": "",
        "unrealized": "",
        "closed_trades": "",
        "closed_wins": "",
        "closed_losses": "",
        "closed_win_rate": "",
    }


def _result_diagnostics(result_path: Path | str) -> dict[str, Any]:
    if not result_path:
        return _empty_diagnostics()
    path = Path(result_path)
    if not path.exists():
        return _empty_diagnostics()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_diagnostics()
    closed_trades = _as_int(
        _first_value(
            doc,
            (
                ("totalPerformance", "tradeStatistics", "totalNumberOfTrades"),
                ("totalPerformance", "tradeStatistics", "TotalNumberOfTrades"),
                ("n_closed_trades",),
            ),
        )
    )
    closed_wins = _as_int(
        _first_value(
            doc,
            (
                ("totalPerformance", "tradeStatistics", "numberOfWinningTrades"),
                ("totalPerformance", "tradeStatistics", "NumberOfWinningTrades"),
                ("totalPerformance", "tradeStatistics", "winningTrades"),
            ),
        )
    )
    closed_losses = _as_int(
        _first_value(
            doc,
            (
                ("totalPerformance", "tradeStatistics", "numberOfLosingTrades"),
                ("totalPerformance", "tradeStatistics", "NumberOfLosingTrades"),
                ("totalPerformance", "tradeStatistics", "losingTrades"),
            ),
        )
    )
    return {
        "realized_net": _first_value(
            doc,
            (
                ("totalPerformance", "tradeStatistics", "totalNetProfit"),
                ("totalPerformance", "tradeStatistics", "TotalNetProfit"),
                ("totalPerformance", "tradeStatistics", "totalProfitLoss"),
                ("totalPerformance", "tradeStatistics", "netProfit"),
            ),
        ),
        "unrealized": _first_value(
            doc,
            (
                ("runtimeStatistics", "Unrealized"),
                ("runtime_statistics", "Unrealized"),
                ("statistics", "Unrealized"),
            ),
        ),
        "closed_trades": closed_trades,
        "closed_wins": closed_wins,
        "closed_losses": closed_losses,
        "closed_win_rate": _closed_win_rate(closed_wins, closed_trades),
    }


def _run_variant(
    variant: ScannerRankerVariant,
    *,
    window: Window,
    artifact_path: Path,
    artifact_sha256: str,
    data_fp: str,
    data_folder: Path,
    runs_root: Path,
    run_lean: Any,
    isolate_run_dirs: bool,
) -> dict[str, Any]:
    uses_default_artifact = _needs_default_artifact(variant)
    variant_runs_root = _variant_runs_root(runs_root, variant, isolate_run_dirs=isolate_run_dirs)
    adapter = LocalLeanRun(
        dist_builder=_dist_builder(window, data_fp, data_folder, variant.base_module),
        data_root=data_folder,
        runs_root=variant_runs_root,
        marker_check=True,
        run_lean=run_lean,
        find_result=_default_find_result,
        persist=None,
    )
    run_dir = adapter._run_dir(variant.config, window)
    result_path = ""
    error = ""
    metrics = ResultMetrics(sharpe=0.0, ret_pct=0.0, dd_pct=0.0, orders=0)
    diagnostics: dict[str, Any] = _empty_diagnostics()
    try:
        metrics = adapter(variant.config, window)
        found_result = _default_find_result(run_dir)
        result_path = str(found_result)
        diagnostics = _result_diagnostics(found_result)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "variant_id": variant.variant_id,
        "family": variant.family,
        "wave": variant.wave,
        "base_module": variant.base_module,
        "hypothesis": variant.hypothesis,
        "sweep_config_hash": variant.config_hash,
        "window": window.name,
        "ok": not error,
        "sharpe": metrics.sharpe,
        "ret_pct": metrics.ret_pct,
        "dd_pct": metrics.dd_pct,
        "orders": metrics.orders,
        **diagnostics,
        "artifact_path": _repo_ref(artifact_path) if uses_default_artifact else "",
        "artifact_sha256": artifact_sha256 if uses_default_artifact else "",
        "run_dir": _repo_ref(run_dir),
        "result_path": _repo_ref(result_path) if result_path else "",
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
    lines.append(
        "| variant | base | ok | ret_pct | dd_pct | orders | realized_net | unrealized | "
        "closed_win_rate | closed_trades | sharpe |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        display_row = dict(row)
        if isinstance(row.get("closed_win_rate"), float):
            display_row["closed_win_rate"] = f"{row['closed_win_rate']:.1f}"
        lines.append(
            "| {variant_id} | {base_module} | {ok} | {ret_pct:.3f} | {dd_pct:.3f} | {orders} | "
            "{realized_net} | {unrealized} | {closed_win_rate} | {closed_trades} | "
            "{sharpe:.3f} |".format(
                **display_row
            )
        )
    (report_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _raise_on_failures(rows: Sequence[dict[str, Any]]) -> None:
    failures = [row for row in rows if not row.get("ok")]
    if not failures:
        return
    print("\n=== FAILURES ===", flush=True)
    for row in failures:
        print(f"{row['variant_id']}: {row.get('error', '')}", flush=True)
    raise SystemExit(1)


def main() -> None:
    args = _args()
    variants = _variants(args)
    if not variants:
        raise SystemExit("no variants selected")
    if not 1 <= args.workers <= len(variants):
        raise SystemExit(f"--workers must be between 1 and {len(variants)}, got {args.workers}")
    artifact_path, artifact_sha256 = _validate_artifact(args, variants)
    window = WINDOWS[args.window]
    sweep_id = args.sweep_id or f"scanner_ranker_{args.pack}_{window.name}"
    runs_root, report_dir = _report_dirs(sweep_id)
    data_folder = args.data_folder.expanduser().resolve()
    if not data_folder.exists():
        raise SystemExit(f"--data-folder does not exist: {data_folder}")
    data_fp = _data_fingerprint(data_folder)

    if data_fp and not args.no_cache_ensure:
        ensure_weekly_cache(
            data_fp,
            storage_dir=ROOT / "storage",
            cache_root=ROOT / "results" / "warmup_cache",
        )

    gate = _LeanCliWarmupGate()
    run_lean = _make_logged_gated_run_lean(gate, use_project_lean_config=True)
    isolate_run_dirs = _needs_variant_run_roots(variants)

    print(
        f"=== scanner-ranker sweep | pack={args.pack} variants={len(variants)} workers={args.workers} "
        f"window={window.name} ===",
        flush=True,
    )
    print(f"artifact={artifact_path} sha256={artifact_sha256[:12] or 'missing'}", flush=True)
    print(f"data_fingerprint={data_fp or 'unknown'}", flush=True)
    print(f"data_folder={data_folder}", flush=True)
    print(f"isolate_run_dirs={isolate_run_dirs}", flush=True)
    for variant in variants:
        print(f"  {variant.variant_id}: {variant.config_hash} base={variant.base_module}", flush=True)

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                _run_variant,
                variant,
                window=window,
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha256,
                data_fp=data_fp,
                data_folder=data_folder,
                runs_root=runs_root,
                run_lean=run_lean,
                isolate_run_dirs=isolate_run_dirs,
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
        "artifact_path": _repo_ref(artifact_path) if any(_needs_default_artifact(v) for v in variants) else "",
        "artifact_sha256": artifact_sha256,
        "default_model_key": DEFAULT_MODEL_KEY,
        "data_fingerprint": data_fp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reports": {
            "summary_csv": _repo_ref(report_dir / "summary.csv"),
            "summary_md": _repo_ref(report_dir / "summary.md"),
        },
    }
    _write_summary(report_dir, rows, manifest)
    print(f"REPORT {report_dir}", flush=True)
    _raise_on_failures(rows)


if __name__ == "__main__":
    main()
