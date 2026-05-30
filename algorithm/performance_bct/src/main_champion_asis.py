"""
champion-asis-v1 STRATEGY_CONFIG

Faithful carve of baseline-oracle-v0 (G3/flat-10%/E40d).
Target: ±0.01 Sharpe vs oracle local FY2025 (1.079 / +33.3% / 232 orders).
ARCH-C parity gate: this config passed = carve correct.

DO NOT add/modify phases here without updating the parity gate result.
"""
from engine.engine import StrategyEngine
from phases.universe.polygon_local.polygon_local import PolygonLocal
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.vix_ichimoku_tier.vix_ichimoku_tier import VixIchimokuTier
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.flat_pct_heatcap.flat_pct_heatcap import FlatPctHeatcap
from phases.diagnostics.version_marker.version_marker import VersionMarker

STRATEGY_CONFIG = {
    "name": "champion-asis-v1",
    "version": "1.0.0",
    "description": "Faithful carve of baseline-oracle-v0 (G3/flat-10%/E40d). Parity reference.",
    "phases": {
        "universe": {"module": "phases.universe.polygon_local", "enabled": True, "params": {}},
        "exit_hard": [
            {"module": "phases.exit.kijun_g3_exits", "enabled": True, "params": {
                "cloud_exit_enabled": False,
                "weekly_kijun_exit_enabled": False,
                "phase3_days": 56,
                "phase3_pnl": 0.15,
            }},
        ],
        "regime": [
            {"module": "phases.regime.vix_ichimoku_tier", "enabled": True, "params": {}},
            {"module": "phases.regime.spy_200ma",         "enabled": True, "params": {}},
            {"module": "phases.regime.vix_percentile",    "enabled": True, "params": {"vix_percentile_enabled": False}},
        ],
        "signal": {"module": "phases.signal.bct_score_full", "enabled": True, "params": {
            "min_score": 7,
            "parabolic_threshold": 0.25,
        }},
        "sizing": {"module": "phases.sizing.flat_pct_heatcap", "enabled": True, "params": {
            "position_pct": 0.10,
        }},
        "diagnostics": [
            {"module": "phases.diagnostics.version_marker", "enabled": True, "params": {}},
        ],
    },
    "invariants": {
        "no_count_caps": True,
        "no_time_exits": True,
        "explicit_exposure_only": True,
    },
}


def build_engine(qc) -> StrategyEngine:
    """Wire phase instances for champion-asis-v1."""
    phase_instances = {
        "universe": [PolygonLocal(params={}, logger=None)],
        "exit_hard": [KijunG3Exits(params={
            "cloud_exit_enabled": False,
            "weekly_kijun_exit_enabled": False,
            "phase3_days": 56,
            "phase3_pnl": 0.15,
        }, logger=None)],
        "regime": [
            VixIchimokuTier(params={}, logger=None),
            SpySma200(params={}, logger=None),
            VixPercentile(params={"vix_percentile_enabled": False}, logger=None),
        ],
        "signal": [BctScoreFull(params={"min_score": 7, "parabolic_threshold": 0.25}, logger=None)],
        "sizing": [FlatPctHeatcap(params={"position_pct": 0.10}, logger=None)],
        "diagnostics": [VersionMarker(params={}, logger=None)],
    }
    return StrategyEngine(config=STRATEGY_CONFIG, qc=qc, phase_instances=phase_instances)
