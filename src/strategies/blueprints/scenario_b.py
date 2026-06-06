"""#386 Scenario B - "Sector Momentum / Vol-Risk".

The B composition proves the same engine can run a materially different module map:
sector-rotation universe, full BCT signal, VIX regime, composite ranking, risk/reward selection,
buy-stop intraday trigger, volatility-adjusted sizing, ATR stop, profit-tightening trail, and
multi-metric exits. The engine stays byte-identical; only this config changes.

is_fixture=True because the runtime data for sector/VIX/target/stop references is still partially
fail-open for the architecture proof. This is not a deployable champion.
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.arm.stub_arm.stub_arm import StubArm
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.risk_reward_filter.risk_reward_filter import RiskRewardFilter
from phases.entry_trigger.buy_stop_trigger.buy_stop_trigger import BuyStopTrigger
from phases.exit.multi_metric_confirm_exit.multi_metric_confirm_exit import MultiMetricConfirmExit
from phases.intraday_sizing.vol_adjusted_risk.vol_adjusted_risk import VolAdjustedRisk
from phases.ranking.composite_ranking.composite_ranking import CompositeRanking
from phases.regime.vix_regime.vix_regime import VixRegime
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.stops_initial.atr_stop.atr_stop import AtrStop
from phases.trail.tighten_after_profit.tighten_after_profit import TightenAfterProfit
from phases.universe.sector_rotation_universe.sector_rotation_universe import SectorRotationUniverse

CONFIG = StrategyConfig(
    name="scenario-b-sector-momentum",
    version="1.0.0",
    is_fixture=True,
    continuous_weekly=True,
    phases={
        "universe": Slot(impl=SectorRotationUniverse, params=SectorRotationUniverse.Params(top_sectors=3)),
        "signal": Slot(impl=BctScoreFull, params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25)),
        "regime": [Slot(impl=VixRegime, params=VixRegime.Params(high_threshold=28.0, missing_vix_blocks=False))],
        "ranking": Slot(impl=CompositeRanking, params=CompositeRanking.Params()),
        "entry_selection": Slot(impl=RiskRewardFilter, params=RiskRewardFilter.Params(min_rr=2.0)),
        "arm": Slot(impl=StubArm, params=StubArm.Params()),
        "entry_trigger": Slot(impl=BuyStopTrigger, params=BuyStopTrigger.Params(breakout_pct=0.0)),
        "intraday_sizing": Slot(impl=VolAdjustedRisk, params=VolAdjustedRisk.Params(risk_pct=0.01)),
        "stops_initial": Slot(impl=AtrStop, params=AtrStop.Params(atr_mult=2.5, fallback_stop_pct=0.10)),
        "trail": Slot(impl=TightenAfterProfit, params=TightenAfterProfit.Params(profit_trigger_pct=0.10)),
        "exit_hard": [Slot(impl=MultiMetricConfirmExit, params=MultiMetricConfirmExit.Params(confirm_n=2))],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)
LEAN_ENTRY = True
