"""#408 George-range FY2025 local BT sweep: 30 variants, 6 workers.

This is the local-LEAN proof harness for the George-style intraday architecture work:
generate thirty real StrategyConfig variants from the current phase catalog, run them through
the direct local BT path, and preserve order/trade artifacts for later analysis.

Usage:
  python3 scripts/run_408_george_range_30.py --workers 6
  python3 scripts/run_408_george_range_30.py --window jan --limit 1 --workers 1 --sweep-id george_range_30_smoke
  python3 scripts/run_408_george_range_30.py --data-folder /Users/falk/projects/kumo-qc/data --full-warmup --workers 6
  WARMUP_GATE_CAPACITY=2 python3 scripts/run_408_george_range_30.py --workers 6
  python3 scripts/run_408_george_range_30.py --symlink-data --workers 6
  python3 scripts/run_408_george_range_30.py --rebuild-artifacts
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict, deque
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "scripts")]
os.environ.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")

import build.cloud_package as cp  # noqa: E402
from engine.config import Slot, StrategyConfig  # noqa: E402
from phases.arm.stub_arm.stub_arm import StubArm  # noqa: E402
from phases.diagnostics.chart_emit.chart_emit import ChartEmit  # noqa: E402
from phases.diagnostics.version_marker.version_marker import VersionMarker  # noqa: E402
from phases.entry_selection.resistance_proximity_filter.resistance_proximity_filter import (  # noqa: E402
    ResistanceProximityFilter,
)
from phases.entry_trigger.buy_stop_trigger.buy_stop_trigger import BuyStopTrigger  # noqa: E402
from phases.entry_trigger.stub_trigger.stub_trigger import StubEntryTrigger  # noqa: E402
from phases.exit.proactive_strength_exit.proactive_strength_exit import ProactiveStrengthExit  # noqa: E402
from phases.exit.scratch_flat_exit.scratch_flat_exit import ScratchFlatExit  # noqa: E402
from phases.intraday_sizing.stub_intraday_sizer.stub_intraday_sizer import StubIntradaySizer  # noqa: E402
from phases.intraday_sizing.vol_adjusted_risk.vol_adjusted_risk import VolAdjustedRisk  # noqa: E402
from phases.ranking.score_dv_ranking.score_dv_ranking import ScoreDvRanking  # noqa: E402
from phases.regime.market_breadth_gate.market_breadth_gate import MarketBreadthGate  # noqa: E402
from phases.signal.tier1_high_conviction.tier1_high_conviction import Tier1HighConviction  # noqa: E402
from phases.stops_initial.support_atr_stop.support_atr_stop import SupportAtrStop  # noqa: E402
from phases.trail.position_path_tracker.position_path_tracker import PositionPathTracker  # noqa: E402
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap  # noqa: E402
from scripts.run_386_arm_direct import WINDOWS, _cache_attrs  # noqa: E402
from sweeps.adapters.local_lean import WarmupGate, _default_find_result, read_local_orders  # noqa: E402
from sweeps.types import Window  # noqa: E402


@dataclass(frozen=True, slots=True)
class VariantSpec:
    variant_id: str
    family: str
    hypothesis: str
    target_pct: float = 0.06
    min_peak_pct: float = 0.05
    giveback_from_peak_pct: float = 0.025
    require_still_bullish: bool = True
    proactive_min_hold_days: int = 0
    scratch: dict[str, Any] | None = None
    entry_trigger: str = "stub"
    entry_trigger_params: dict[str, Any] = field(default_factory=lambda: {"near_pct": 0.015})
    sizer: str = "flat"
    sizer_params: dict[str, Any] = field(
        default_factory=lambda: {"position_pct": 0.04, "max_gross_pct": 1.0}
    )
    resistance_buffer_pct: float = 0.02
    atr_mult: float = 0.50
    breadth_threshold: float = 0.40
    missing_breadth_blocks: bool = False


@dataclass(frozen=True, slots=True)
class PreparedRun:
    spec: VariantSpec
    window: Window
    config_hash: str
    data_fingerprint: str
    git_commit: str
    run_dir: Path


@dataclass(frozen=True, slots=True)
class RunOutcome:
    variant_id: str
    family: str
    hypothesis: str
    config_hash: str
    run_dir: Path
    result_path: Path | None
    rc: int
    status: str
    net_profit: str | None
    drawdown: str | None
    total_orders: str | None
    sharpe: str | None
    trades_csv: Path | None
    orders_csv: Path | None
    exit_events_csv: Path | None
    artifact_error: str | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.rc == 0 and self.status == "Completed" and self.net_profit is not None


def _v(
    variant_id: str,
    family: str,
    hypothesis: str,
    **overrides: Any,
) -> VariantSpec:
    data = asdict(VariantSpec(variant_id=variant_id, family=family, hypothesis=hypothesis))
    data.update(overrides)
    return VariantSpec(**data)


def _scratch(
    no_progress_days: int,
    min_mfe_pct: float,
    scratch_band_pct: float,
    max_loss_after_mfe_pct: float,
) -> dict[str, Any]:
    return {
        "no_progress_days": no_progress_days,
        "min_mfe_pct": min_mfe_pct,
        "scratch_band_pct": scratch_band_pct,
        "max_loss_after_mfe_pct": max_loss_after_mfe_pct,
    }


VARIANTS: tuple[VariantSpec, ...] = (
    _v("p_only_base", "anchor", "Prior proactive-only anchor from #398."),
    _v(
        "p_only_tight_giveback",
        "anchor",
        "Prior proactive anchor with tighter giveback capture.",
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.015,
    ),
    _v(
        "scratch_base",
        "anchor",
        "Prior scratch baseline: no-progress and round-trip-to-flat management.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
    ),
    _v(
        "scratch_fast",
        "anchor",
        "Fast scratch: test whether early stalled trades should be cut sooner.",
        scratch=_scratch(2, 0.015, 0.004, 0.015),
    ),
    _v(
        "scratch_patient",
        "anchor",
        "Patient scratch: allow more time and more MFE before judging the path.",
        scratch=_scratch(5, 0.03, 0.0075, 0.025),
    ),
    _v(
        "scratch_tight_risk",
        "anchor",
        "Tight risk scratch: same no-progress window, smaller flat band and loss cap.",
        scratch=_scratch(3, 0.02, 0.003, 0.01),
    ),
    _v("target_04_fast_take", "exit_target", "Take strength earlier at +4%.", target_pct=0.04),
    _v("target_08_let_run", "exit_target", "Let winners run to +8% before target exit.", target_pct=0.08),
    _v(
        "target_10_patient_giveback",
        "exit_target",
        "High target plus looser giveback to see whether big trend holds offset noise.",
        target_pct=0.10,
        min_peak_pct=0.08,
        giveback_from_peak_pct=0.04,
    ),
    _v(
        "giveback_loose_04",
        "exit_target",
        "Proactive winner handling with a wider giveback band.",
        giveback_from_peak_pct=0.04,
    ),
    _v(
        "giveback_tight_no_bull",
        "exit_target",
        "Tight giveback without requiring the daily structure to remain bullish.",
        min_peak_pct=0.04,
        giveback_from_peak_pct=0.015,
        require_still_bullish=False,
    ),
    _v(
        "minpeak_low_03",
        "exit_target",
        "Treat smaller MFE peaks as actionable for giveback exits.",
        min_peak_pct=0.03,
    ),
    _v(
        "scratch_1d_low_mfe",
        "scratch_grid",
        "One-day low-MFE scratch: aggressive stale-trade removal.",
        scratch=_scratch(1, 0.01, 0.003, 0.01),
    ),
    _v(
        "scratch_2d_low_mfe",
        "scratch_grid",
        "Two-day low-MFE scratch: less harsh than same-day, still early.",
        scratch=_scratch(2, 0.01, 0.005, 0.015),
    ),
    _v(
        "scratch_5d_wide_band",
        "scratch_grid",
        "Five-day scratch with wider round-trip-to-flat band.",
        scratch=_scratch(5, 0.02, 0.01, 0.02),
    ),
    _v(
        "scratch_7d_patient",
        "scratch_grid",
        "Very patient scratch: preserve slower-developing winners.",
        scratch=_scratch(7, 0.03, 0.0075, 0.03),
    ),
    _v(
        "scratch_losscap_03",
        "scratch_grid",
        "Loose post-MFE loss cap tests whether exits were premature.",
        scratch=_scratch(3, 0.02, 0.005, 0.03),
    ),
    _v(
        "scratch_roundtrip_wide_01",
        "scratch_grid",
        "Wide flat band catches more round trips after initial MFE.",
        scratch=_scratch(3, 0.02, 0.01, 0.02),
    ),
    _v(
        "entry_near_010",
        "entry_trigger",
        "Tighter proximity trigger: fewer but cleaner intraday fires.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger_params={"near_pct": 0.010},
    ),
    _v(
        "entry_near_020",
        "entry_trigger",
        "Wider proximity trigger: test whether scanner is good but entry waits too long.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger_params={"near_pct": 0.020},
    ),
    _v(
        "entry_near_025",
        "entry_trigger",
        "Very wide proximity trigger: intentionally permissive entry timing.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger_params={"near_pct": 0.025},
    ),
    _v(
        "buy_stop_flat",
        "entry_trigger",
        "Breakout-through-zone trigger with no extra breakout offset.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger="buy_stop",
        entry_trigger_params={"breakout_pct": 0.0},
    ),
    _v(
        "buy_stop_005",
        "entry_trigger",
        "Breakout trigger requiring +0.5% through the armed zone.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger="buy_stop",
        entry_trigger_params={"breakout_pct": 0.005},
    ),
    _v(
        "buy_stop_010",
        "entry_trigger",
        "Breakout trigger requiring +1.0% through the armed zone.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        entry_trigger="buy_stop",
        entry_trigger_params={"breakout_pct": 0.010},
    ),
    _v(
        "pos_03_atr_075",
        "risk_stack",
        "Smaller flat sizing with looser ATR stop cushion.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        sizer_params={"position_pct": 0.03, "max_gross_pct": 1.0},
        atr_mult=0.75,
    ),
    _v(
        "pos_05_atr_050",
        "risk_stack",
        "Larger flat sizing at the baseline stop.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        sizer_params={"position_pct": 0.05, "max_gross_pct": 1.0},
    ),
    _v(
        "volrisk_075",
        "risk_stack",
        "Vol-adjusted risk sizing, conservative risk budget.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        sizer="vol_risk",
        sizer_params={
            "risk_pct": 0.0075,
            "fallback_stop_pct": 0.06,
            "max_position_pct": 0.06,
            "vix_baseline": 20.0,
            "vix_slope": 0.02,
            "min_scale": 0.40,
        },
    ),
    _v(
        "volrisk_125",
        "risk_stack",
        "Vol-adjusted risk sizing, less conservative risk budget.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        sizer="vol_risk",
        sizer_params={
            "risk_pct": 0.0125,
            "fallback_stop_pct": 0.08,
            "max_position_pct": 0.08,
            "vix_baseline": 20.0,
            "vix_slope": 0.02,
            "min_scale": 0.40,
        },
    ),
    _v(
        "resistance_loose_010",
        "risk_stack",
        "Looser resistance filter: allow entries closer to 52-week highs.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        resistance_buffer_pct=0.01,
    ),
    _v(
        "breadth_050_strict",
        "risk_stack",
        "Stricter breadth gate: fewer entries in weaker market regimes.",
        scratch=_scratch(3, 0.02, 0.005, 0.02),
        breadth_threshold=0.50,
    ),
)


if len(VARIANTS) != 30:
    raise RuntimeError(f"expected exactly 30 variants, got {len(VARIANTS)}")
if len({v.variant_id for v in VARIANTS}) != len(VARIANTS):
    raise RuntimeError("variant_id values must be unique")


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


class _LeanCliWarmupGate(WarmupGate):
    """WarmupGate variant that tolerates LEAN CLI's wrapped stdout marker.

    The base gate looks for the exact marker inside one line. The local LEAN CLI can wrap
    `Algorithm finished warming up.` across two emitted lines, which keeps the gate closed until
    process exit and accidentally serializes a multi-worker sweep. Keep a small normalized tail so
    the release still happens at the warmup boundary.
    """

    def _stream(self, lines: Any, wait: Any, proc: Any) -> int:
        released = False
        tail = ""
        try:
            for line in lines:
                tail = " ".join((tail + " " + str(line)).split())[-240:]
                if not released and self.DONE_MARKER in tail:
                    self._sem.release()
                    released = True
            wait()
            return getattr(proc, "returncode", 0)
        finally:
            if not released:
                self._sem.release()


def _make_logged_gated_run_lean(gate: WarmupGate, *, use_project_lean_config: bool = False) -> Any:
    def run_lean(project_dir: Path) -> int:
        env = dict(os.environ)
        env.setdefault("DOCKER_HOST", "unix:///Users/falk/.docker/run/docker.sock")
        argv = ["lean", "backtest", "--no-update"]
        if use_project_lean_config:
            argv.extend(["--lean-config", str(project_dir / "lean.json")])
        argv.append(str(project_dir))
        return gate.run(
            argv,
            env,
            popen=lambda: _LoggedPopen(argv, env, project_dir / "lean-stdout.txt"),
        )

    return run_lean


def _strategy_config(spec: VariantSpec) -> StrategyConfig:
    proactive = ProactiveStrengthExit.Params(
        target_pct=spec.target_pct,
        min_peak_pct=spec.min_peak_pct,
        giveback_from_peak_pct=spec.giveback_from_peak_pct,
        require_still_bullish=spec.require_still_bullish,
        min_hold_days=spec.proactive_min_hold_days,
    )
    exits: list[Slot[object]] = []
    if spec.scratch is not None:
        exits.append(Slot(impl=ScratchFlatExit, params=ScratchFlatExit.Params(**spec.scratch)))
    exits.append(Slot(impl=ProactiveStrengthExit, params=proactive))

    if spec.entry_trigger == "stub":
        trigger_slot: Slot[object] = Slot(
            impl=StubEntryTrigger,
            params=StubEntryTrigger.Params(**spec.entry_trigger_params),
        )
    elif spec.entry_trigger == "buy_stop":
        trigger_slot = Slot(
            impl=BuyStopTrigger,
            params=BuyStopTrigger.Params(**spec.entry_trigger_params),
        )
    else:
        raise ValueError(f"unknown entry_trigger={spec.entry_trigger!r}")

    if spec.sizer == "flat":
        sizer_slot: Slot[object] = Slot(
            impl=StubIntradaySizer,
            params=StubIntradaySizer.Params(**spec.sizer_params),
        )
    elif spec.sizer == "vol_risk":
        sizer_slot = Slot(
            impl=VolAdjustedRisk,
            params=VolAdjustedRisk.Params(**spec.sizer_params),
        )
    else:
        raise ValueError(f"unknown sizer={spec.sizer!r}")

    return StrategyConfig(
        name=f"george_range_30_{spec.variant_id}",
        version="1.0.0",
        is_fixture=True,
        continuous_weekly=True,
        phases={
            "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
            "signal": Slot(impl=Tier1HighConviction, params=Tier1HighConviction.Params()),
            "regime": [
                Slot(
                    impl=MarketBreadthGate,
                    params=MarketBreadthGate.Params(
                        pct_threshold=spec.breadth_threshold,
                        missing_breadth_blocks=spec.missing_breadth_blocks,
                    ),
                )
            ],
            "ranking": Slot(impl=ScoreDvRanking, params=ScoreDvRanking.Params()),
            "entry_selection": Slot(
                impl=ResistanceProximityFilter,
                params=ResistanceProximityFilter.Params(buffer_pct=spec.resistance_buffer_pct),
            ),
            "arm": Slot(impl=StubArm, params=StubArm.Params()),
            "entry_trigger": trigger_slot,
            "intraday_sizing": sizer_slot,
            "stops_initial": Slot(impl=SupportAtrStop, params=SupportAtrStop.Params(atr_mult=spec.atr_mult)),
            "trail": Slot(impl=PositionPathTracker, params=PositionPathTracker.Params()),
            "exit_hard": exits,
            "diagnostics": [
                Slot(impl=VersionMarker, params=VersionMarker.Params()),
                Slot(impl=ChartEmit, params=ChartEmit.Params()),
            ],
        },
    )


def _ensure_readme(path: Path, title: str, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    readme = path / "README.md"
    if not readme.exists():
        readme.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")


def _prepare(
    spec: VariantSpec,
    *,
    window: Window,
    sweep_id: str,
    warmup_days: int,
    full_warmup: bool,
    symlink_data: bool,
    data_folder: Path | None,
) -> PreparedRun:
    sweep_root = _ROOT / "sweeps" / "runs" / sweep_id
    _ensure_readme(
        sweep_root,
        f"{sweep_id}/",
        "Generated local LEAN projects for the George-range backtest sweep. "
        "Each child folder is one strategy variation; do not hand-edit generated dist files.",
    )
    variant_root = sweep_root / spec.variant_id
    _ensure_readme(
        variant_root,
        f"{spec.variant_id}/",
        "Generated run windows and artifacts for this George-range variation. "
        "The `variant.json` file records the phase parameters that created it.",
    )
    run = variant_root / window.name
    if run.exists():
        shutil.rmtree(run)
    run.mkdir(parents=True)

    config = _strategy_config(spec)
    res = cp.build_from_config(config, deployable=True, dist_dir=run)
    arm_files = [f for f in res.included if "arm" in f.lower()]
    if not arm_files:
        raise RuntimeError(f"{spec.variant_id}: arm phase missing from dist; aborting non-live proof")

    extra_attrs = _cache_attrs(res, warmup_days=warmup_days, full_warmup=full_warmup)
    sy, sm, sd = (int(x) for x in window.start.split("-"))
    ey, em, ed = (int(x) for x in window.end.split("-"))
    inject = (
        "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        f"    START_DATE = ({sy}, {sm}, {sd})\n"
        f"    END_DATE = ({ey}, {em}, {ed})\n"
        "    CONTINUOUS_WEEKLY = True\n"
    )
    for key, value in extra_attrs.items():
        inject += f"    {key} = {value!r}\n"
    inject += f"    RUN_LABEL = {spec.variant_id!r}\n"
    inject += "    LOG_ONLY_ACTIVE_PHASES = True\n"
    inject += "    LOG_TICK_EVENTS = False\n"

    main_py = run / "main.py"
    source = main_py.read_text(encoding="utf-8")
    anchor = "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
    if anchor not in source:
        raise RuntimeError(f"{spec.variant_id}: inject anchor missing in {main_py}")
    marker = f"# GEORGE_RANGE_30_VARIANT {spec.variant_id} {res.config_hash}\n"
    main_py.write_text(marker + source.replace(anchor, inject, 1), encoding="utf-8")

    lean_config: dict[str, Any] = {
        "description": f"#408 George-range 30 FY2025 {spec.variant_id}",
        "parameters": {},
    }
    if data_folder is not None:
        lean_config["data-folder"] = str(data_folder.expanduser().resolve())
    (run / "lean.json").write_text(json.dumps(lean_config) + "\n", encoding="utf-8")
    data = run / "data"
    if symlink_data:
        if not data.exists():
            data.symlink_to(_ROOT / "data")
    elif data.exists() or data.is_symlink():
        if data.is_symlink() or data.is_file():
            data.unlink()
        else:
            shutil.rmtree(data)
    (run / "variant.json").write_text(
        json.dumps(
            {
                "variant": asdict(spec),
                "window": asdict(window),
                "config_hash": res.config_hash,
                "data_fingerprint": res.data_fingerprint,
                "git_commit": res.git_commit,
                "phase_markers": res.phase_markers,
                "included": res.included,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _ensure_readme(
        run,
        f"{window.name}/",
        "Generated LEAN project for one George-range strategy variation/window. "
        "`orders.csv`, `trades.csv`, and `exit_events.csv` are written after the local BT completes.",
    )
    return PreparedRun(
        spec=spec,
        window=window,
        config_hash=res.config_hash,
        data_fingerprint=res.data_fingerprint,
        git_commit=res.git_commit,
        run_dir=run,
    )


def _result_status(doc: Mapping[str, Any]) -> str:
    state = doc.get("state") or doc.get("State") or {}
    if isinstance(state, Mapping):
        raw = state.get("Status") or state.get("status")
        if raw:
            return str(raw)
    if doc.get("statistics") or doc.get("Statistics"):
        return "Completed"
    return "Unknown"


def _statistics(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    stats = doc.get("statistics") or doc.get("Statistics") or {}
    return stats if isinstance(stats, Mapping) else {}


def _csv_write(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _symbol_value(order: Mapping[str, Any]) -> str:
    symbol = order.get("symbol")
    if isinstance(symbol, Mapping):
        value = symbol.get("value") or symbol.get("Value") or symbol.get("symbol")
    else:
        value = symbol
    return str(value or "")


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        pass
    text = text.replace("Z", "+00:00")
    for candidate in (text, text.split(".")[0]):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def _order_time(order: Mapping[str, Any]) -> str:
    return str(order.get("lastFillTime") or order.get("time") or "")


def _date_iso(value: Any) -> str:
    parsed = _parse_dt(value)
    return parsed.date().isoformat() if parsed is not None else ""


def _orders_to_rows(
    orders: list[Mapping[str, Any]],
    *,
    prepared: PreparedRun,
    result_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order in orders:
        rows.append(
            {
                "variant_id": prepared.spec.variant_id,
                "config_hash": prepared.config_hash,
                "result_path": str(result_path),
                "order_id": order.get("id"),
                "date": _date_iso(_order_time(order)),
                "symbol": _symbol_value(order),
                "quantity": order.get("quantity"),
                "price": order.get("price"),
                "status": order.get("status"),
                "time": order.get("time"),
                "last_fill_time": order.get("lastFillTime"),
                "tag": order.get("tag"),
                "type": order.get("type"),
            }
        )
    return rows


EXIT_RE = re.compile(
    r"(?:(?P<prefix>EXIT_EVENT)|(?P<legacy>SCRATCH_FLAT_EXIT|PROACTIVE_STRENGTH_EXIT))\|"
    r"(?P<date>\d{4}-\d{2}-\d{2})\|(?P<symbol>[A-Za-z0-9.\-]+)\|(?P<rest>[^\n\r]*)"
)
EXIT_EVENT_DONE_RE = re.compile(r"(?:^|\|)giveback_from_peak_pct=-?\d+(?:\.\d+)?$")
LEAN_LOG_PREFIX_RE = re.compile(r"^\d{8}\s+\d{2}:\d{2}:\d{2}\.\d+\s+\w+::")


def _exit_record_complete(record: str) -> bool:
    if record.startswith("EXIT_EVENT|"):
        return EXIT_EVENT_DONE_RE.search(record) is not None
    return True


def _exit_event_records(text: str) -> list[str]:
    records: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = EXIT_RE.search(line)
        if match is not None:
            if pending:
                records.append(pending)
            pending = line[match.start():]
            if _exit_record_complete(pending):
                records.append(pending)
                pending = ""
            continue
        if pending:
            if LEAN_LOG_PREFIX_RE.match(line):
                records.append(pending)
                pending = ""
                continue
            pending += line
            if _exit_record_complete(pending):
                records.append(pending)
                pending = ""
    if pending:
        records.append(pending)
    return records


def _parse_exit_events(stdout_path: Path, prepared: PreparedRun) -> list[dict[str, Any]]:
    if not stdout_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for record in _exit_event_records(stdout_path.read_text(encoding="utf-8", errors="replace")):
        match = EXIT_RE.search(record)
        if not match:
            continue
        fields: dict[str, str] = {}
        for part in match.group("rest").split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
        rows.append(
            {
                "variant_id": prepared.spec.variant_id,
                "config_hash": prepared.config_hash,
                "event": fields.get("event") or match.group("legacy") or "EXIT_EVENT",
                "date": match.group("date"),
                "symbol": match.group("symbol"),
                "module": fields.get("module"),
                "reason": fields.get("reason"),
                "order_id": fields.get("order_id"),
                "days_held": fields.get("days_held") or fields.get("days"),
                "qty": fields.get("qty"),
                "entry_price": fields.get("entry_price"),
                "exit_price": fields.get("exit_price"),
                "pnl": fields.get("pnl"),
                "return_pct": fields.get("return_pct"),
                "mfe_pct": fields.get("mfe_pct"),
                "mae_pct": fields.get("mae_pct"),
                "peak_return_pct": fields.get("peak_return_pct") or fields.get("peak"),
                "giveback_from_peak_pct": fields.get("giveback_from_peak_pct") or fields.get("giveback"),
                "raw": record,
            }
        )
    return rows


def _exit_reason_queues(exit_events: list[dict[str, Any]]) -> dict[tuple[str, str], deque[dict[str, Any]]]:
    queues: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for event in exit_events:
        queues[(str(event["symbol"]).upper(), str(event["date"]))].append(event)
    return queues


def _pair_trades(
    orders: list[Mapping[str, Any]],
    *,
    prepared: PreparedRun,
    result_path: Path,
    exit_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lots: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    trades: list[dict[str, Any]] = []
    reason_queues = _exit_reason_queues(exit_events)
    sorted_orders = sorted(orders, key=lambda o: (_order_time(o), str(o.get("id") or "")))

    for order in sorted_orders:
        symbol = _symbol_value(order).upper()
        if not symbol:
            continue
        qty = float(order.get("quantity") or 0.0)
        price = float(order.get("price") or 0.0)
        if qty == 0.0 or price <= 0.0:
            continue
        if qty > 0:
            lots[symbol].append(
                {
                    "entry_order_id": order.get("id"),
                    "entry_time": _order_time(order),
                    "entry_dt": _parse_dt(_order_time(order)),
                    "entry_price": price,
                    "qty": qty,
                    "entry_tag": order.get("tag"),
                }
            )
            continue

        remaining = abs(qty)
        exit_dt = _parse_dt(_order_time(order))
        exit_date = exit_dt.date().isoformat() if exit_dt is not None else ""
        exit_event = reason_queues.get((symbol, exit_date), deque())
        reason_row = exit_event[0] if exit_event else None
        while remaining > 0 and lots[symbol]:
            lot = lots[symbol][0]
            close_qty = min(float(lot["qty"]), remaining)
            pnl = (price - float(lot["entry_price"])) * close_qty
            ret = price / float(lot["entry_price"]) - 1.0
            entry_dt = lot.get("entry_dt")
            duration_days = ""
            if isinstance(entry_dt, datetime) and isinstance(exit_dt, datetime):
                duration_days = (exit_dt - entry_dt).total_seconds() / 86400.0
            trades.append(
                {
                    "variant_id": prepared.spec.variant_id,
                    "family": prepared.spec.family,
                    "config_hash": prepared.config_hash,
                    "result_path": str(result_path),
                    "status": "closed",
                    "symbol": symbol,
                    "qty": close_qty,
                    "entry_order_id": lot.get("entry_order_id"),
                    "exit_order_id": order.get("id"),
                    "entry_time": lot.get("entry_time"),
                    "exit_time": _order_time(order),
                    "entry_date": entry_dt.date().isoformat()
                    if isinstance(entry_dt, datetime)
                    else "",
                    "exit_date": exit_dt.date().isoformat() if isinstance(exit_dt, datetime) else "",
                    "duration_days": duration_days,
                    "entry_price": lot.get("entry_price"),
                    "exit_price": price,
                    "pnl": pnl,
                    "return_pct": ret,
                    "entry_tag": lot.get("entry_tag"),
                    "exit_tag": order.get("tag"),
                    "exit_event": reason_row.get("event") if reason_row else "",
                    "exit_reason": reason_row.get("reason") if reason_row else "",
                    "censored": False,
                }
            )
            lot["qty"] = float(lot["qty"]) - close_qty
            remaining -= close_qty
            if float(lot["qty"]) <= 1e-9:
                lots[symbol].popleft()
            if remaining <= 1e-9 and reason_row and exit_event:
                exit_event.popleft()

        if remaining > 1e-9:
            trades.append(
                {
                    "variant_id": prepared.spec.variant_id,
                    "family": prepared.spec.family,
                    "config_hash": prepared.config_hash,
                    "result_path": str(result_path),
                    "status": "unmatched_exit",
                    "symbol": symbol,
                    "qty": remaining,
                    "entry_order_id": "",
                    "exit_order_id": order.get("id"),
                    "entry_time": "",
                    "exit_time": _order_time(order),
                    "entry_date": "",
                    "exit_date": exit_date,
                    "duration_days": "",
                    "entry_price": "",
                    "exit_price": price,
                    "pnl": "",
                    "return_pct": "",
                    "entry_tag": "",
                    "exit_tag": order.get("tag"),
                    "exit_event": reason_row.get("event") if reason_row else "",
                    "exit_reason": reason_row.get("reason") if reason_row else "",
                    "censored": False,
                }
            )

    for symbol, queue in lots.items():
        for lot in queue:
            trades.append(
                {
                    "variant_id": prepared.spec.variant_id,
                    "family": prepared.spec.family,
                    "config_hash": prepared.config_hash,
                    "result_path": str(result_path),
                    "status": "open",
                    "symbol": symbol,
                    "qty": lot.get("qty"),
                    "entry_order_id": lot.get("entry_order_id"),
                    "exit_order_id": "",
                    "entry_time": lot.get("entry_time"),
                    "exit_time": "",
                    "entry_date": _date_iso(lot.get("entry_time")),
                    "exit_date": "",
                    "duration_days": "",
                    "entry_price": lot.get("entry_price"),
                    "exit_price": "",
                    "pnl": "",
                    "return_pct": "",
                    "entry_tag": lot.get("entry_tag"),
                    "exit_tag": "",
                    "exit_event": "",
                    "exit_reason": "",
                    "censored": True,
                }
            )
    return trades


ORDER_FIELDS = [
    "variant_id",
    "config_hash",
    "result_path",
    "order_id",
    "date",
    "symbol",
    "quantity",
    "price",
    "status",
    "time",
    "last_fill_time",
    "tag",
    "type",
]

TRADE_FIELDS = [
    "variant_id",
    "family",
    "config_hash",
    "result_path",
    "status",
    "symbol",
    "qty",
    "entry_order_id",
    "exit_order_id",
    "entry_time",
    "exit_time",
    "entry_date",
    "exit_date",
    "duration_days",
    "entry_price",
    "exit_price",
    "pnl",
    "return_pct",
    "entry_tag",
    "exit_tag",
    "exit_event",
    "exit_reason",
    "censored",
]

EXIT_EVENT_FIELDS = [
    "variant_id",
    "config_hash",
    "event",
    "date",
    "symbol",
    "module",
    "reason",
    "order_id",
    "days_held",
    "qty",
    "entry_price",
    "exit_price",
    "pnl",
    "return_pct",
    "mfe_pct",
    "mae_pct",
    "peak_return_pct",
    "giveback_from_peak_pct",
    "raw",
]

SUMMARY_FIELDS = [
    "variant_id",
    "family",
    "hypothesis",
    "config_hash",
    "rc",
    "status",
    "ok",
    "net_profit",
    "drawdown",
    "total_orders",
    "sharpe",
    "trades_csv",
    "orders_csv",
    "exit_events_csv",
    "artifact_error",
    "error",
    "run_dir",
    "result_path",
]


def _export_artifacts(prepared: PreparedRun, result_path: Path) -> tuple[Path, Path, Path, str | None]:
    artifact_error: str | None = None
    try:
        orders = list(read_local_orders(result_path))
    except Exception as exc:  # noqa: BLE001 - artifact failure should not hide the BT result.
        orders = []
        artifact_error = str(exc)

    exit_events = _parse_exit_events(prepared.run_dir / "lean-stdout.txt", prepared)
    order_rows = _orders_to_rows(orders, prepared=prepared, result_path=result_path)
    trade_rows = _pair_trades(
        orders,
        prepared=prepared,
        result_path=result_path,
        exit_events=exit_events,
    )

    orders_csv = prepared.run_dir / "orders.csv"
    trades_csv = prepared.run_dir / "trades.csv"
    exit_events_csv = prepared.run_dir / "exit_events.csv"
    _csv_write(orders_csv, order_rows, ORDER_FIELDS)
    _csv_write(trades_csv, trade_rows, TRADE_FIELDS)
    _csv_write(exit_events_csv, exit_events, EXIT_EVENT_FIELDS)
    return trades_csv, orders_csv, exit_events_csv, artifact_error


def _summarize(prepared: PreparedRun, *, rc: int) -> RunOutcome:
    result_path: Path | None = None
    trades_csv: Path | None = None
    orders_csv: Path | None = None
    exit_events_csv: Path | None = None
    artifact_error: str | None = None
    try:
        result_path = _default_find_result(prepared.run_dir)
        doc = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return RunOutcome(
            variant_id=prepared.spec.variant_id,
            family=prepared.spec.family,
            hypothesis=prepared.spec.hypothesis,
            config_hash=prepared.config_hash,
            run_dir=prepared.run_dir,
            result_path=result_path,
            rc=rc,
            status="MissingResult",
            net_profit=None,
            drawdown=None,
            total_orders=None,
            sharpe=None,
            trades_csv=None,
            orders_csv=None,
            exit_events_csv=None,
            artifact_error=None,
            error=str(exc),
        )

    if result_path is not None:
        trades_csv, orders_csv, exit_events_csv, artifact_error = _export_artifacts(prepared, result_path)

    stats = _statistics(doc)
    state = doc.get("state") or doc.get("State") or {}
    runtime_error = state.get("RuntimeError") if isinstance(state, Mapping) else None
    stacktrace = state.get("StackTrace") if isinstance(state, Mapping) else None
    error = runtime_error or stacktrace or doc.get("error") or doc.get("Error")
    return RunOutcome(
        variant_id=prepared.spec.variant_id,
        family=prepared.spec.family,
        hypothesis=prepared.spec.hypothesis,
        config_hash=prepared.config_hash,
        run_dir=prepared.run_dir,
        result_path=result_path,
        rc=rc,
        status=_result_status(doc),
        net_profit=str(stats.get("Net Profit")) if stats.get("Net Profit") is not None else None,
        drawdown=str(stats.get("Drawdown")) if stats.get("Drawdown") is not None else None,
        total_orders=str(stats.get("Total Orders")) if stats.get("Total Orders") is not None else None,
        sharpe=str(stats.get("Sharpe Ratio")) if stats.get("Sharpe Ratio") is not None else None,
        trades_csv=trades_csv,
        orders_csv=orders_csv,
        exit_events_csv=exit_events_csv,
        artifact_error=artifact_error,
        error=str(error) if error else None,
    )


def _run_one(prepared: PreparedRun, run_lean: Any) -> RunOutcome:
    print(
        f"START|{prepared.spec.variant_id}|family={prepared.spec.family}|"
        f"hash={prepared.config_hash}|dir={prepared.run_dir}",
        flush=True,
    )
    rc = int(run_lean(prepared.run_dir))
    outcome = _summarize(prepared, rc=rc)
    print(
        "RESULT|"
        f"{outcome.variant_id}|rc={outcome.rc}|status={outcome.status}|"
        f"net={outcome.net_profit}|dd={outcome.drawdown}|orders={outcome.total_orders}|"
        f"trades={outcome.trades_csv}|path={outcome.result_path}",
        flush=True,
    )
    return outcome


def _read_csv_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_reports(sweep_id: str, outcomes: list[RunOutcome], variants: tuple[VariantSpec, ...]) -> Path:
    reports = _ROOT / "sweeps" / "reports" / sweep_id
    _ensure_readme(
        reports,
        f"{sweep_id}/",
        "Aggregated outputs from the George-range local BT sweep. "
        "Summary rows point back to generated run folders; aggregate order/trade CSVs are analysis inputs.",
    )

    summary_rows = [
        {
            "variant_id": out.variant_id,
            "family": out.family,
            "hypothesis": out.hypothesis,
            "config_hash": out.config_hash,
            "rc": out.rc,
            "status": out.status,
            "ok": out.ok,
            "net_profit": out.net_profit,
            "drawdown": out.drawdown,
            "total_orders": out.total_orders,
            "sharpe": out.sharpe,
            "trades_csv": str(out.trades_csv) if out.trades_csv else "",
            "orders_csv": str(out.orders_csv) if out.orders_csv else "",
            "exit_events_csv": str(out.exit_events_csv) if out.exit_events_csv else "",
            "artifact_error": out.artifact_error,
            "error": out.error,
            "run_dir": str(out.run_dir),
            "result_path": str(out.result_path) if out.result_path else "",
        }
        for out in outcomes
    ]
    _csv_write(reports / "summary.csv", summary_rows, SUMMARY_FIELDS)

    order_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    for out in outcomes:
        order_rows.extend(_read_csv_rows(out.orders_csv))
        trade_rows.extend(_read_csv_rows(out.trades_csv))
        exit_rows.extend(_read_csv_rows(out.exit_events_csv))
    _csv_write(reports / "orders_all.csv", order_rows, ORDER_FIELDS)
    _csv_write(reports / "trades_all.csv", trade_rows, TRADE_FIELDS)
    _csv_write(reports / "exit_events_all.csv", exit_rows, EXIT_EVENT_FIELDS)
    (reports / "manifest.json").write_text(
        json.dumps(
            {
                "sweep_id": sweep_id,
                "variant_count": len(variants),
                "ok_count": sum(1 for o in outcomes if o.ok),
                "variants": [asdict(v) for v in variants],
                "reports": {
                    "summary_csv": str(reports / "summary.csv"),
                    "orders_all_csv": str(reports / "orders_all.csv"),
                    "trades_all_csv": str(reports / "trades_all.csv"),
                    "exit_events_all_csv": str(reports / "exit_events_all.csv"),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_summary_md(reports / "summary.md", outcomes)
    return reports


def _write_summary_md(path: Path, outcomes: list[RunOutcome]) -> None:
    lines = [
        "# George Range 30 Local BT Summary",
        "",
        "| variant | family | net | dd | orders | sharpe | ok |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for out in outcomes:
        lines.append(
            f"| {out.variant_id} | {out.family} | {out.net_profit or ''} | "
            f"{out.drawdown or ''} | {out.total_orders or ''} | {out.sharpe or ''} | {out.ok} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rebuild_artifacts_from_summary(
    sweep_id: str,
    *,
    window: Window,
    variants: tuple[VariantSpec, ...],
) -> list[RunOutcome]:
    summary_path = _ROOT / "sweeps" / "reports" / sweep_id / "summary.csv"
    if not summary_path.exists():
        raise SystemExit(f"missing summary for rebuild: {summary_path}")
    with summary_path.open("r", encoding="utf-8", newline="") as fh:
        by_id = {row["variant_id"]: row for row in csv.DictReader(fh)}

    outcomes: list[RunOutcome] = []
    for spec in variants:
        row = by_id.get(spec.variant_id)
        if row is None:
            raise SystemExit(f"summary missing variant for rebuild: {spec.variant_id}")
        prepared = PreparedRun(
            spec=spec,
            window=window,
            config_hash=row.get("config_hash") or "",
            data_fingerprint="",
            git_commit="",
            run_dir=Path(row["run_dir"]),
        )
        outcomes.append(_summarize(prepared, rc=int(row.get("rc") or 0)))
    return outcomes


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=sorted(WINDOWS), default="fy")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N selected variants.")
    parser.add_argument(
        "--variants",
        default="",
        help="Comma-separated variant ids. Defaults to all 30 in declared order.",
    )
    parser.add_argument("--sweep-id", default="george_range_30")
    parser.add_argument(
        "--warmup-days",
        type=int,
        default=int(os.environ.get("KUMO_386_WARMUP_DAYS", "320")),
    )
    parser.add_argument("--full-warmup", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--symlink-data",
        action="store_true",
        help=(
            "Create a per-project data symlink. Default is off because in-workspace LEAN "
            "projects use the root lean.json data-folder; project-level data symlinks can hang."
        ),
    )
    parser.add_argument(
        "--data-folder",
        type=Path,
        help="Explicit LEAN data-folder for generated projects; useful when running from a worktree.",
    )
    parser.add_argument(
        "--rebuild-artifacts",
        action="store_true",
        help="Refresh per-run and aggregate CSV artifacts from existing completed local BT JSONs.",
    )
    return parser.parse_args()


def _select_variants(raw: str, limit: int) -> tuple[VariantSpec, ...]:
    selected = VARIANTS
    if raw.strip():
        wanted = [part.strip() for part in raw.split(",") if part.strip()]
        by_id = {variant.variant_id: variant for variant in VARIANTS}
        unknown = sorted(set(wanted).difference(by_id))
        if unknown:
            raise SystemExit(f"unknown variant id(s): {unknown}")
        selected = tuple(by_id[item] for item in wanted)
    if limit:
        selected = selected[:limit]
    return selected


def main() -> None:
    args = _args()
    window = WINDOWS[args.window]
    variants = _select_variants(args.variants, args.limit)
    if not variants:
        raise SystemExit("no variants selected")
    if args.symlink_data and args.data_folder is not None:
        raise SystemExit("--symlink-data and --data-folder are mutually exclusive")
    if not args.rebuild_artifacts and not 1 <= args.workers <= len(variants):
        raise SystemExit(f"--workers must be between 1 and {len(variants)}, got {args.workers}")

    print(
        "=== #408 GEORGE RANGE LOCAL BT | "
        f"sweep_id={args.sweep_id} | window={window.name} {window.start}->{window.end} | "
        f"variants={len(variants)} | workers={args.workers} | warmup_days={args.warmup_days} | "
        f"full_warmup={args.full_warmup} | gate_capacity={os.environ.get('WARMUP_GATE_CAPACITY', '1')} ===",
        flush=True,
    )

    if args.rebuild_artifacts:
        outcomes = _rebuild_artifacts_from_summary(args.sweep_id, window=window, variants=variants)
        outcomes.sort(key=lambda outcome: {v.variant_id: i for i, v in enumerate(variants)}[outcome.variant_id])
        reports = _write_reports(args.sweep_id, outcomes, variants)
        print(f"REBUILD_ARTIFACTS|done|reports={reports}", flush=True)
        return

    prepared = [
        _prepare(
            spec,
            window=window,
            sweep_id=args.sweep_id,
            warmup_days=args.warmup_days,
            full_warmup=args.full_warmup,
            symlink_data=args.symlink_data,
            data_folder=args.data_folder,
        )
        for spec in variants
    ]
    fps = sorted({p.data_fingerprint for p in prepared})
    print(f"DATA_FP|{','.join(fps)}", flush=True)
    for item in prepared:
        print(
            f"PREPARED|{item.spec.variant_id}|family={item.spec.family}|"
            f"hash={item.config_hash}|fp={item.data_fingerprint}",
            flush=True,
        )
    if args.prepare_only:
        print("PREPARE_ONLY|done", flush=True)
        return

    gate = _LeanCliWarmupGate()
    run_lean = _make_logged_gated_run_lean(
        gate,
        use_project_lean_config=bool(args.symlink_data or args.data_folder is not None),
    )
    outcomes: list[RunOutcome] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(_run_one, item, run_lean) for item in prepared]
        for future in as_completed(futures):
            outcomes.append(future.result())

    order = {variant.variant_id: idx for idx, variant in enumerate(variants)}
    outcomes.sort(key=lambda outcome: order[outcome.variant_id])
    reports = _write_reports(args.sweep_id, outcomes, variants)

    print("\n=== GEORGE RANGE LOCAL BT RESULTS ===", flush=True)
    print(",".join(SUMMARY_FIELDS), flush=True)
    for out in outcomes:
        print(
            ",".join(
                [
                    out.variant_id,
                    out.family,
                    out.hypothesis.replace(",", ";"),
                    out.config_hash,
                    str(out.rc),
                    out.status,
                    str(out.ok),
                    str(out.net_profit or ""),
                    str(out.drawdown or ""),
                    str(out.total_orders or ""),
                    str(out.sharpe or ""),
                    str(out.trades_csv or ""),
                    str(out.orders_csv or ""),
                    str(out.exit_events_csv or ""),
                    str(out.artifact_error or ""),
                    str(out.error or ""),
                    str(out.run_dir),
                    str(out.result_path or ""),
                ]
            ),
            flush=True,
        )
    print(f"REPORT_DIR|{reports}", flush=True)

    failures = [out for out in outcomes if not out.ok]
    if failures:
        print("\n=== FAILURES ===", flush=True)
        for out in failures:
            print(
                f"{out.variant_id}: rc={out.rc} status={out.status} "
                f"error={out.error} artifact_error={out.artifact_error}",
                flush=True,
            )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
