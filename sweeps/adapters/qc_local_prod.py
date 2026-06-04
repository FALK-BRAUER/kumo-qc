"""make_local_run — the production LOCAL adapter factory (#214/#325): wires LocalLeanRun with a
real DistBuilder so the sweep runs through `lean backtest` on the local intraday data (the #325
backfill). The local twin of qc_cloud_prod.make_cloud_run — SAME run_sweep/run_pool contract, SAME
persist_run archive, differing only in env='local' + the local toolchain (legitimate adapter
polymorphism, not a strategy branch).

THE DISTBUILDER (the piece that was missing): per (config, window) it builds the sweep-config's
flat dist into the isolated run_dir, injects the window as BCTAlgorithm class-attrs IDENTICALLY to
the cloud path (qc_v2_cloud.STEP_A_WINDOW — same Window→dates, so a local-vs-cloud diff reflects
data/skip, never a window-boundary mismatch), writes the minimal lean project config, and returns a
config-specific marker (the LocalLeanRun fabrication guard confirms THIS config's code ran).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sweeps.adapters.local_lean import (
    LocalLeanRun,
    WarmupGate,
    _default_find_result,
    _default_run_lean,
    make_gated_run_lean,
    make_local_persist,
)
from sweeps.objective.selector import OBJECTIVE_VERSION
from sweeps.provenance import git_commit
from sweeps.types import SweepConfig, Window

_REPO = Path(__file__).resolve().parents[2]


def _window_class_attrs(window: Window) -> str:
    """The cloud-PARITY window injection: BCTAlgorithm START_DATE/END_DATE class attrs from the
    Window's ISO start/end (same Window→dates mapping as qc_v2_cloud.STEP_A_WINDOW)."""
    sy, sm, sd = (int(x) for x in window.start.split("-"))
    ey, em, ed = (int(x) for x in window.end.split("-"))
    return (
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        f"    START_DATE = ({sy}, {sm}, {sd})\n"
        f"    END_DATE = ({ey}, {em}, {ed})\n"
    )


def local_dist_builder(config: SweepConfig, window: Window, run_dir: Path) -> str:
    """Build the sweep-config's dist into run_dir + inject window + lean.json; return the marker.

    The DistBuilder LocalLeanRun calls per cell. Idempotent window-inject (skips if already
    present). Marker = a config-hash comment injected into main.py so the fabrication guard
    confirms THIS exact config ran (cross-cell isolation on top of the per-(hash,window) run_dir)."""
    from build.sweep_build import build_sweep_dist

    import json as _json
    import os as _os

    build_sweep_dist(config, dist_dir=run_dir)  # flat dist (main.py + flat modules) into run_dir
    marker = f"SWEEP_MARKER {config.config_hash}"
    main = run_dir / "main.py"
    s = main.read_text()
    tail = s.split("class BCTAlgorithm")[-1]
    if "START_DATE" not in tail:
        # window dates + optional extra BCTAlgorithm class-attrs from env (the LOCAL flag mechanism —
        # LEAN reads get_parameter from config.json, not lean.json, so class-attr injection is the
        # reliable local lever; e.g. the #336 CONTINUOUS_WEEKLY flag). repr() → valid Python literals
        # (True/False, quoted str). Absent env → no extra attrs (byte-identical no-flag path).
        extra = _json.loads(_os.environ.get("SWEEP_CLASS_ATTRS", "{}"))
        # #336/#338: the config's continuous_weekly field is AUTHORITATIVE for the flag — it drives
        # BOTH the BCTAlgorithm behavior (this class-attr) AND the config_hash identity, so a flag-ON
        # archive can never be confused with flag-OFF. (Env SWEEP_CLASS_ATTRS stays for ad-hoc attrs.)
        if getattr(config, "continuous_weekly", False):
            extra.setdefault("CONTINUOUS_WEEKLY", True)
        # #368: warmup_days drives the WARMUP_DAYS class-attr (config IDENTITY → in config_hash). When
        # TRIMMED (<560), the weekly-cache is REQUIRED (else the 78wk weekly starves → 0 trades) — arm
        # WARMUP_WEEKLY_CACHE_FP to the data fingerprint so the weekly comes from cache, with the
        # #368 fail-loud guard catching any coverage gap. Default 560 → no injection (byte-untouched).
        _wd = getattr(config, "warmup_days", 560)
        if _wd != 560:
            extra.setdefault("WARMUP_DAYS", _wd)
            if _wd < 560:  # trimmed → the weekly-cache is mandatory
                manifest = _REPO / "data" / "MANIFEST.json"
                if manifest.exists():
                    fp = _json.loads(manifest.read_text()).get("fingerprint")
                    if fp:
                        extra.setdefault("WARMUP_WEEKLY_CACHE_FP", fp)
        attr_lines = "".join(f"    {k} = {v!r}\n" for k, v in extra.items())
        s = s.replace(
            "    STRATEGY_CONFIG = STRATEGY_CONFIG\n", _window_class_attrs(window) + attr_lines, 1
        )
    if marker not in s:
        s = f"# {marker}\n" + s
    main.write_text(s)
    (run_dir / "lean.json").write_text('{ "description": "sweep cell", "parameters": {} }\n')
    return marker


def make_local_run(
    *,
    data_root: Path | None = None,
    runs_root: Path | None = None,
    marker_check: bool = True,
    archive: bool = True,
    warmup_gate: WarmupGate | None = None,
) -> LocalLeanRun:
    """The production local RunConfig primitive: LocalLeanRun wired with the real DistBuilder +
    local toolchain (`lean backtest` w/ the Docker host fix) + the durable persist. Provenance
    (commit + data_fingerprint) is pinned once from a reference build (the data is identical across
    cells). `data_root` = the repo data tree (the #325 minute backfill lives there); `runs_root` =
    the gitignored isolation root (sweeps/runs/).

    `warmup_gate` (C): an OPTIONAL shared WarmupGate serializing the memory-heavy warmup phase across
    concurrent cells (the OOM control for parallel local sweeps — see local_lean.WarmupGate). Pass ONE
    gate instance shared across the run when max_workers>1; the SAME adapter is reused for every cell
    by run_pool, so the gate is shared naturally. None (default) = ungated (serial, or the caller
    accepts unbounded concurrent warmups). At workers=1 a gate is a harmless no-op."""
    data_root = data_root or (_REPO / "data")
    runs_root = runs_root or (_REPO / "sweeps" / "runs")
    runs_root.mkdir(parents=True, exist_ok=True)
    run_lean = make_gated_run_lean(warmup_gate) if warmup_gate is not None else _default_run_lean

    persist = None
    if archive:
        # provenance pin: git HEAD + the live data-MANIFEST fingerprint (identical across cells —
        # same data tree). No extra build needed; the dist_builder stamps each cell's config_hash.
        import json as _json

        manifest = _REPO / "data" / "MANIFEST.json"
        data_fp = (
            _json.loads(manifest.read_text()).get("fingerprint", "local-data")
            if manifest.exists() else "local-data"
        )
        persist = make_local_persist(
            commit=git_commit(_REPO),
            data_fingerprint=data_fp,
            objective_version=OBJECTIVE_VERSION,
            dest_root=_REPO / "results" / "archive",
            data_root=data_root,
            clock=lambda: datetime.now(timezone.utc).isoformat(),
        )

    return LocalLeanRun(
        dist_builder=local_dist_builder,
        data_root=data_root,
        runs_root=runs_root,
        marker_check=marker_check,
        run_lean=run_lean,
        find_result=_default_find_result,
        persist=persist,
    )
