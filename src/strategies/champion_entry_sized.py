"""champion-entry-sized — champion-entry + the score-aware sizer (the X/4 finally BINDS on SIZE).

The score-binding measurement config: the EXACT champion-entry phase stack (champion-asis +
the §4 Gate-2 entry trigger) with ONE delta — the sizing phase swaps flat_pct_heatcap for
ScoreTierHeatcap, so the X/4 entry-confirm score now DRIVES position size (the methodology
sizing tiers) instead of being published and ignored:

    universe (dv_rank_cap) -> signal (bct_score_full)
    -> regime (spy_200ma, vix_percentile)
    -> entry_selection (bct_entry_confirm)   [publishes X/4 on qc._entry_confirm]
    -> entry_timing (market_on_open_entry)
    -> sizing (score_tier_heatcap)           [DELTA — X/4 -> tier (4/4 full . 3/4 75% . 2/4 50%)]
    -> exit_hard (kijun_g3_exits) -> diagnostics (version_marker, chart_emit)

WHY a NEW config (not a champion-entry edit): champion-entry (−1.016) GATES on the X/4 but sizes
every confirmed name FLAT (10% PV regardless of 4/4 vs 2/4). This config makes the score BIND on
SIZE — 4/4 names get full capital, 2/4 names half. It is the controlled test of "does score-driven
sizing improve risk-adjusted return over flat sizing". Every phase except sizing is champion-entry
VERBATIM (same impl, same params) so the ONLY behavioral delta is the tier sizing.

champion-asis stays UNCHANGED (config_hash e573e84b1ce1 — flat_pct_heatcap, the −0.616 baseline);
champion-entry stays UNCHANGED (its own hash, the −1.016 flat-sized entry-confirm). champion-entry-
sized is its OWN config with its OWN config_hash, judged on its OWN MERITS — NEVER vs the 0.778
adjusted-data champion.

Tier defaults are methodology-canonical (4/4=1.00, 3/4=0.75, 2/4=0.50, min_score=2, base
position_pct=0.10 == champion's flat size, so a 4/4 name sizes IDENTICALLY to flat — the delta is
that 3/4 and 2/4 names size DOWN).

Single code path (local == cloud); RAW; no count caps / time exits / fixed slots. Pins to
(git commit + this config hash + substrate fingerprint).
"""
from __future__ import annotations

from engine.config import Slot, StrategyConfig
from phases.diagnostics.chart_emit.chart_emit import ChartEmit
from phases.diagnostics.version_marker.version_marker import VersionMarker
from phases.entry_selection.bct_entry_confirm.bct_entry_confirm import BctEntryConfirm
from phases.entry_timing.market_on_open_entry.market_on_open_entry import MarketOnOpenEntry
from phases.exit.kijun_g3_exits.kijun_g3_exits import KijunG3Exits
from phases.regime.spy_200ma.spy_200ma import SpySma200
from phases.regime.vix_percentile.vix_percentile import VixPercentile
from phases.signal.bct_score_full.bct_score_full import BctScoreFull
from phases.sizing.score_tier_heatcap.score_tier_heatcap import ScoreTierHeatcap
from phases.universe.dv_rank_cap.dv_rank_cap import DvRankCap

CONFIG = StrategyConfig(
    name="champion-entry-sized",
    # 1.0.0: first cut of the score-aware sizing config. champion-entry stack VERBATIM with the
    # sizing phase swapped flat_pct_heatcap -> score_tier_heatcap (the X/4 binds on size).
    version="1.0.0",
    phases={
        # --- champion-entry stack, VERBATIM (the controlled-measurement invariant) ---
        "universe": Slot(impl=DvRankCap, params=DvRankCap.Params()),
        "signal": Slot(
            impl=BctScoreFull,
            params=BctScoreFull.Params(min_score=7, parabolic_threshold=0.25),
        ),
        "regime": [
            Slot(impl=SpySma200, params=SpySma200.Params()),
            Slot(impl=VixPercentile, params=VixPercentile.Params(vix_percentile_enabled=False)),
        ],
        "entry_selection": Slot(
            impl=BctEntryConfirm,
            params=BctEntryConfirm.Params(),
        ),
        "entry_timing": Slot(
            impl=MarketOnOpenEntry,
            params=MarketOnOpenEntry.Params(),
        ),
        # --- DELTA: score-aware tier sizing (the only behavioral change vs champion-entry) ---
        # Methodology-canonical tiers: 4/4=full, 3/4=0.75, 2/4=0.50, min_score=2. Base
        # position_pct=0.10 == champion-entry's flat size (so 4/4 sizes IDENTICALLY; 3/4 & 2/4 down).
        "sizing": Slot(
            impl=ScoreTierHeatcap,
            params=ScoreTierHeatcap.Params(
                position_pct=0.10, full=1.00, three_quarter=0.75, half=0.50, min_score=2,
            ),
        ),
        # --- champion-entry stack, VERBATIM (continued) ---
        "exit_hard": [
            Slot(impl=KijunG3Exits, params=KijunG3Exits.Params(
                cloud_exit_enabled=False, weekly_kijun_exit_enabled=False,
                phase3_days=56, phase3_pnl=0.15,
            )),
        ],
        "diagnostics": [
            Slot(impl=VersionMarker, params=VersionMarker.Params()),
            Slot(impl=ChartEmit, params=ChartEmit.Params()),
        ],
    },
)

# LEAN-deployable (#238): same live-coarse universe + entry wiring as champion-entry. The build
# seeds runtime.lean_entry + the entry/sizing phase modules into dist/.
LEAN_ENTRY = True
